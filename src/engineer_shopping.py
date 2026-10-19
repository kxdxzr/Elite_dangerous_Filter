"""Unified multi-jump shopping estimates, not a verified route planner."""
import copy
from dataclasses import dataclass
import math

import filter_engine as eng
from engineer_destinations import destination_system


@dataclass
class Criteria:
    origin: str
    destination: str
    jump_range: float
    max_extra_jumps: int
    conditions: list
    landing_pad: str = ''
    pledged_power: str = ''
    assume_max_rank: bool = True


def build_criteria(origin, destination, jump_range, arrival_ls, module,
                   ignore_carriers=True, max_extra_jumps=1, ignore_planetary=False, landing_pad='',
                   pledged_power='', assume_max_rank=True):
    origin, destination = origin.strip(), destination.strip()
    if not origin or not destination:
        raise ValueError('请填写出发星系和工程师星系')
    destination = destination_system(destination)
    try:
        jump_range = float(jump_range)
        arrival_ls = float(arrival_ls) if str(arrival_ls).strip() else None
    except (TypeError, ValueError):
        raise ValueError('航程须为正数，到站距离须为非负数或留空') from None
    if not math.isfinite(jump_range) or jump_range <= 0 or (
            arrival_ls is not None and (not math.isfinite(arrival_ls) or arrival_ls < 0)):
        raise ValueError('航程须为正数，到站距离须为非负数或留空')
    extra_text = str(max_extra_jumps).strip()
    if isinstance(max_extra_jumps, bool) or not extra_text.isascii() or not extra_text.isdigit():
        raise ValueError('最多额外跳数须为非负整数')
    max_extra_jumps = int(max_extra_jumps)
    if not isinstance(landing_pad, str) or landing_pad.strip() not in ('', '不限', 'S', 'M', 'L'):
        raise ValueError('停机坪请选择不限、S、M或L')
    landing_pad = landing_pad.strip()
    if landing_pad == '不限':
        landing_pad = ''
    from powerplay_tool import normalize_power
    pledged_power = '' if pledged_power in ('', '无') else normalize_power(pledged_power)
    if not isinstance(assume_max_rank, bool):
        raise ValueError('满级优惠选项须为布尔值')
    modules = [module] if isinstance(module, dict) else module
    if not isinstance(modules, list) or not modules:
        raise ValueError('请至少添加一项采购模组／舰载武器')
    conditions = []
    for item in modules:
        if not isinstance(item, dict) or item.get('field') != 'modules' or item.get('op') not in ('in', '=', 'contains'):
            raise ValueError('请选择要采购的模组／舰载武器')
        # The shopping list means ALL named products, not an OR over names.
        # The ordinary main-window "in" semantics remain unchanged.
        if item['op'] == 'in':
            if not isinstance(item.get('values'), list) or not item['values']:
                raise ValueError('请选择要采购的模组／舰载武器')
            for name in dict.fromkeys(item['values']):
                conditions.append(dict(copy.deepcopy(item), values=[name]))
        else:
            conditions.append(copy.deepcopy(item))
    if arrival_ls is not None:
        conditions.append(dict(type='field', field='distance_to_arrival', op='<', text=arrival_ls))
    if ignore_carriers:
        conditions.append(dict(type='field', field='type', op='not in', values=['Drake-Class Carrier']))
    if ignore_planetary:
        conditions.append(dict(type='field', field='is_planetary', op='false'))
    for condition in conditions:
        # Never inherit a stale personal bonus from imported purchase conditions.
        condition.pop('personal_power', None)
        if condition.get('field') == 'modules' and pledged_power and assume_max_rank:
            condition['personal_power'] = pledged_power
    return Criteria(origin, destination, jump_range, max_extra_jumps,
                    eng.normalize_conditions('stations', conditions), landing_pad,
                    pledged_power, assume_max_rank)


def confirmed_pad(row):
    """Largest positively evidenced pad, not proof that an unknown larger pad is absent."""
    if row.get('has_large_pad') is True:
        return 'L'
    for size, field in (('L', 'large_pads'), ('M', 'medium_pads'), ('S', 'small_pads')):
        count = row.get(field)
        if isinstance(count, bool):
            continue
        try:
            count = float(count)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(count) and count.is_integer() and count > 0:
            return size
    return None


def estimated_jumps(distance, jump_range):
    # Avoid an extra jump due solely to a one-ULP floating-point boundary error.
    return max(1, math.ceil(math.nextafter(distance / jump_range, -math.inf))) if distance > 0 else 0


def route_metrics(origin, destination, point, jump_range):
    direct = eng.dist3(origin, destination)
    first, second = eng.dist3(origin, point), eng.dist3(point, destination)
    direct_jumps = estimated_jumps(direct, jump_range)
    first_jumps, second_jumps = estimated_jumps(first, jump_range), estimated_jumps(second, jump_range)
    return dict(origin_jumps=first_jumps, destination_jumps=second_jumps,
                total_jumps=first_jumps + second_jumps, direct_jumps=direct_jumps,
                extra_jumps=max(0, first_jumps + second_jumps - direct_jumps),
                detour_ly=max(0.0, first + second - direct))


def search(criteria, want=100, max_pages=25, progress=None, stop=None):
    criteria = copy.deepcopy(criteria)
    conditions = criteria.conditions
    notes, corrections = [], []
    if criteria.pledged_power and criteria.assume_max_rank:
        notes.append('个人优惠按满级假设计算，未核验实际等级或结算价。')
    cancelled = lambda: stop is not None and stop.is_set()
    result = dict(rows=[], conditions=conditions, landing_pad=criteria.landing_pad,
                  pledged_power=criteria.pledged_power, assume_max_rank=criteria.assume_max_rank,
                  total=0, scanned=0, notes=notes, stopped=False)
    if cancelled():
        notes.append('已手动停止，尚未发送请求')
        result['stopped'] = True
        return result
    origin_name, origin, _ = eng.resolve_ref(criteria.origin)
    if cancelled():
        notes.append('已手动停止')
        result['stopped'] = True
        return result
    destination_name, destination, _ = eng.resolve_ref(criteria.destination)
    direct_distance = eng.dist3(origin, destination)
    if not all(math.isfinite(value) for point in (origin, destination) for value in point):
        raise ValueError('星系坐标无效')
    budget = estimated_jumps(direct_distance, criteria.jump_range) + criteria.max_extra_jumps
    # Any qualifying point has d1+d2 <= budget*range. By the triangle
    # inequality, each leg is <= (budget*range + direct_distance)/2.
    # These safe endpoint spheres bound the search; they are NOT single jumps.
    try:
        radius = (budget * criteria.jump_range + direct_distance) / 2
    except OverflowError:
        raise ValueError('航程或额外跳数过大') from None
    if not math.isfinite(radius):
        raise ValueError('航程或额外跳数过大')
    radius += max(1e-7, math.ulp(radius) * 4)
    for name in dict.fromkeys((origin_name, destination_name)):
        conditions.append(dict(type='distance', ref_system=name, min_ly=None, max_ly=radius, mode='inside'))

    def on_route(row):
        pad = confirmed_pad(row)
        if criteria.landing_pad and (pad is None or 'SML'.index(pad) < 'SML'.index(criteria.landing_pad)):
            return False
        point = eng.result_coords('stations', row)
        if point is None or not all(math.isfinite(value) for value in point):
            return False
        metrics = route_metrics(origin, destination, point, criteria.jump_range)
        if metrics['extra_jumps'] > criteria.max_extra_jumps:
            return False
        row['_shopping_route'] = metrics
        return True

    rows, total, scanned = eng.search('stations', conditions, want=want, max_pages=max_pages,
                                      progress=progress, stop=stop, notes=notes, corrections=corrections,
                                      row_filter=on_route)
    fixed = dict(corrections)
    for condition in conditions:
        for key in ('ref_system', 'text'):
            if isinstance(condition.get(key), str):
                condition[key] = fixed.get(condition[key], condition[key])
        if 'values' in condition:
            condition['values'] = [fixed.get(value, value) for value in condition['values']]

    def order(row):
        route = row['_shopping_route']
        # No price-weighted basket saving can be inferred. Use the weakest
        # confirmed item discount as the final tie-breaker across the full list.
        discounts = [max((info.get('percent') or 0 for _, info in
                         eng.matching_sale_items('stations', row, condition)), default=0)
                     for condition in conditions if condition.get('field') == 'modules']
        return route['extra_jumps'], route['detour_ly'], -min(discounts, default=0)

    rows.sort(key=order)
    notes.append('跳数仅按距离估算，未验证实际航线；排序仅针对已取回的命中。')
    result.update(rows=rows, total=total, scanned=scanned, stopped=cancelled())
    return result


def export_table(result, language, tr):
    from main_csv import export_table as station_table
    from result_format import format_ly

    headers, records = station_table(result['rows'] if result else [], 'stations',
                                     result['conditions'] if result else [], language, tr)
    headers.append('Confirmed landing pad' if language == 'en' else '已确认停机坪')
    for row, record in zip(result['rows'] if result else [], records):
        record.append(confirmed_pad(row) or tr('情况未知'))
    columns = (('direct_jumps', '直达估算跳数', 'Estimated direct jumps'),
               ('origin_jumps', '到采购点估算跳数', 'Estimated jumps to shop'),
               ('destination_jumps', '到工程师估算跳数', 'Estimated jumps to engineer'),
               ('total_jumps', '经采购点估算总跳数', 'Estimated total jumps via shop'),
               ('extra_jumps', '额外估算跳数', 'Estimated extra jumps'),
               ('detour_ly', '绕行距离 ly', 'Detour distance ly'))
    headers.extend(en if language == 'en' else zh for _, zh, en in columns)
    for row, record in zip(result['rows'] if result else [], records):
        metrics = row.get('_shopping_route', {})
        record.extend((format_ly(metrics[key]) if key == 'detour_ly' else str(metrics[key]))
                      if key in metrics else tr('情况未知') for key, _, _ in columns)
    return headers, records
