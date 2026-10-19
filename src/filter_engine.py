"""筛选引擎:支持重复条件 + 多参考点距离(范围内/范围外),全部 AND 逻辑本地精确过滤."""
import json
import math
import copy
import re
from datetime import datetime, timedelta, timezone
import urllib.parse
import urllib.request
import gzip

import field_options as fo
from system_filter_fields import COUNT_FIELDS

SPansh_BASE = "https://spansh.co.uk/api"
EDSM_SYSTEM_URL = "https://www.edsm.net/api-v1/system"

_coords_cache = {}
_ref_cache = {}


def is_excluded_system(kind, row):
    """Exclude Spansh's anomalous Test record, including its stations."""
    name = row.get("system_name") if kind == "stations" else row.get("name")
    ident = row.get("system_id64") if kind == "stations" else row.get("id64")
    return (str(ident) == "7780433924818"
            or str(name or "").strip().casefold() == "test")


def _http_json(url, payload=None, timeout=60, compressed=False):
    if payload is None:
        req = urllib.request.Request(url, headers={"User-Agent": "elite-filter/1.0"})
    else:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "elite-filter/1.0"})
    if compressed:
        req.add_header('Accept-Encoding', 'gzip')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        if compressed and r.headers.get('Content-Encoding', '').casefold() == 'gzip':
            body = gzip.decompress(body)
        return json.loads(body.decode("utf-8"))


def _lookup_exact(name):
    """精确查星系坐标, 返回 (库中标准名, (x,y,z)) 或 None。"""
    q = urllib.parse.urlencode({"systemName": name.strip(), "showCoordinates": 1})
    try:
        d = _http_json(f"{EDSM_SYSTEM_URL}?{q}", timeout=30)
    except Exception:
        d = {}
    c = d.get("coords") if isinstance(d, dict) else None
    if c:
        return d.get("name") or name.strip(), (float(c["x"]), float(c["y"]), float(c["z"]))
    # 回退: 用 spansh 按名搜
    p = {"filters": {"name": {"value": name.strip()}}, "size": 1, "page": 0}
    try:
        s = _http_json(f"{SPansh_BASE}/systems/search", p)
        r0 = (s.get("results") or [None])[0]
        if (r0 and str(r0.get("name", "")).casefold() == name.strip().casefold()
                and all(k in r0 for k in ("x", "y", "z"))):
            return (r0.get("name") or name.strip(),
                    (float(r0["x"]), float(r0["y"]), float(r0["z"])))
    except Exception:
        pass
    return None


def get_system_coords(name):
    """星系名 -> (x,y,z), 带缓存。打错会自动纠正, 不存在抛 ValueError(带建议)。"""
    return resolve_ref(name)[1]


def resolve_ref(name, auto_threshold=0.85):
    """解析参考星系, 返回 (标准名, 坐标, 是否被自动纠正)。
    打错且与某星系相似度>=阈值则自动纠正; 否则抛 ValueError(附带候选建议)。"""
    raw = (name or "").strip()
    if not raw:
        raise ValueError("距离条件未填写参考星系")
    key = raw.lower()
    if key in _ref_cache:
        canon, coords = _ref_cache[key]
        return canon, coords, raw.casefold() != canon.casefold()
    if key in _coords_cache:
        return raw, _coords_cache[key], False
    hit = _lookup_exact(raw)
    if hit:
        canon, coords = hit
        _coords_cache[key] = coords
        _coords_cache.setdefault(canon.lower(), coords)
        _ref_cache[key] = (canon, coords)
        _ref_cache[canon.lower()] = (canon, coords)
        return canon, coords, False
    sims = fo.similar_systems(raw)
    if sims and sims[0][1] >= auto_threshold:
        canon = sims[0][0]
        hit = _lookup_exact(canon)
        if hit:
            _, coords = hit
            _coords_cache[key] = coords
            _coords_cache.setdefault(canon.lower(), coords)
            _ref_cache[key] = (canon, coords)
            _ref_cache[canon.lower()] = (canon, coords)
            return canon, coords, True
    sug = "、".join(n for n, _ in sims[:5]) or "无(请检查拼写)"
    raise ValueError(f"星系不存在: '{raw}'，你是不是想找: {sug}")


def dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def result_coords(kind, row):
    try:
        if kind == "stations":
            return (float(row["system_x"]), float(row["system_y"]), float(row["system_z"]))
        return (float(row["x"]), float(row["y"]), float(row["z"]))
    except (KeyError, TypeError, ValueError):
        return None


# ---- 服务器字段名映射 (UI名 -> 官网searchable_fields原名) ----
STATION_SERVER_NAMES = {
    "controlling_faction": "controlling_minor_faction",
    "controlling_faction_state": "controlling_minor_faction_state",
    "controlling_faction_influence": "controlling_minor_faction_influence",
    "system_colonised": "system_is_colonised",
    "system_being_colonised": "system_is_being_colonised",
    "dssa_carrier": "is_dssa_carrier",
    "last_updated_at": "updated_at",
    "market_last_updated_at": "market_updated_at",
    "shipyard_last_updated_at": "shipyard_updated_at",
    "outfitting_last_updated_at": "outfitting_updated_at",
    "population": "system_population",
    "economy": "primary_economy",
    "planetary": "is_planetary",
    "colonised": "system_is_colonised",
}
SYSTEM_SERVER_NAMES = {
    "faction_presence": "minor_faction_presences",
    "being_colonised": "is_being_colonised",
    "colonised": "is_colonised",
    "controlling_faction": "controlling_minor_faction",
    "controlling_faction_state": "controlling_minor_faction_state",
    "distance_to_nearest_populated_system": "nearest_populated_distance",
    "last_updated_at": "updated_at",
    "economy": "primary_economy",
}

# ---- 服务器字段类型 (决定过滤写法; 不在表里的推不动, 只本地过滤) ----
_ST_GROUP = {"allegiance", "government", "state", "primary_economy",
             "secondary_economy", "type", "material_trader", "technology_broker",
             "carrier_docking_access", "body_type", "body_subtype", "system_power",
             "system_power_state", "system_controlling_power",
             "system_primary_economy", "system_secondary_economy",
              "controlling_minor_faction_state", "controlling_minor_faction"}
_ST_COMBINED = {"services", "ships", "modules", "export_commodities",
                "import_commodities", "prohibited_commodities"}
_ST_BOOL = {"has_market", "has_shipyard", "has_outfitting", "has_large_pad",
            "is_planetary", "body_has_atmosphere", "body_has_rings",
            "system_is_colonised", "system_is_being_colonised", "is_dssa_carrier"}
_ST_NUM = {"distance_to_arrival", "system_population", "large_pads", "medium_pads",
           "small_pads", "body_gravity", "controlling_minor_faction_influence"}
_ST_STR = {"name", "real_name", "system_name", "body_name", "carrier_name"}
_ST_TS = {"updated_at", "market_updated_at", "shipyard_updated_at",
          "outfitting_updated_at"}

_SYS_GROUP = {"allegiance", "government", "state", "primary_economy", "secondary_economy",
              "security", "region", "power", "power_state", "controlling_power",
              "controlling_minor_faction", "controlling_minor_faction_state",
              "thargoid_war_state", "thargoid_war_success_state", "thargoid_war_failure_state"}
_SYS_BOOL = {"needs_permit", "known_permit", "is_colonised", "is_being_colonised",
             "thargoid_war_success_reached"}
_SYS_NUM = {"population", "body_count", "nearest_populated_distance",
            "landmark_value", "estimated_scan_value", "estimated_mapping_value",
            "power_state_control_progress", "power_state_reinforcement",
            "power_state_undermining", "thargoid_war_progress",
            "thargoid_war_days_remaining", "thargoid_war_ports_remaining",
            "x", "y", "z"}
_SYS_STR = {"name"}
_SYS_TS = {"updated_at"}
_SYS_NUM.update(COUNT_FIELDS)

BIG = 10 ** 15  # 开口区间的哨兵 (服务器不接受null端)


def _server_name(kind, field):
    m = STATION_SERVER_NAMES if kind == "stations" else SYSTEM_SERVER_NAMES
    return m.get(field, field)


def _server_type(kind, sfield):
    if kind == "stations":
        if sfield in _ST_GROUP:
            return "group"
        if sfield in _ST_COMBINED:
            return "combined_name"
        if sfield == "marketplace":
            return "combined_commodity"
        if sfield in _ST_BOOL:
            return "boolean"
        if sfield in _ST_NUM or sfield == "distance":
            return "numeric"
        if sfield in _ST_STR:
            return "string"
        if sfield in _ST_TS:
            return "timestamp"
        return None
    if sfield in _SYS_GROUP:
        return "group"
    if sfield in _SYS_BOOL:
        return "boolean"
    if sfield in _SYS_NUM or sfield == "distance":
        return "numeric"
    if sfield in _SYS_STR:
        return "string"
    if sfield in _SYS_TS:
        return "timestamp"
    if sfield in ("minor_faction_presences", "synthesis_recipes"):
        return "combined_name"
    return None


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


_FRESH_RE = re.compile(r"^近(\d+)天$")
_MODULE_CLASS_RE = re.compile(r"^([0-8])\s*(?:级|类)?$")
_MODULE_RATING_RE = re.compile(r"^([A-Ia-i])\s*(?:级)?$")


def resolve_freshness(v):
    """相对新鲜度标记 (近N天) -> UTC ISO 时间字符串; 其他原样返回。"""
    if isinstance(v, str):
        m = _FRESH_RE.match(v.strip())
        if m:
            dt = datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return v


def parse_module_class(v, label):
    """等级: 0~8, 接受 '5'/'5级'/'5类'。"""
    m = _MODULE_CLASS_RE.match(str(v).strip())
    if not m:
        raise ValueError(f"{label}: 模块等级必须是0~8 (如 5/5级)")
    return int(m.group(1))


def parse_module_rating(v, label):
    """级别: 单个字母, 接受大小写 (I 表示无级别装备, 如装甲)。"""
    m = _MODULE_RATING_RE.match(str(v).strip())
    if not m:
        raise ValueError(f"{label}: 模块级别必须是单个字母 (如 A/B, I表示无级别)")
    return m.group(1).upper()


OPTION_AUTOCORRECT = {("stations", "ships"), ("stations", "modules")}


def resolve_option(kind, field, text, auto_threshold=0.85):
    """船/模块名解析: 精确命中(大小写不敏感)用库中原名;
    打错且与某候选相似度>=阈值则自动纠正; 否则抛 ValueError(附带候选建议)。
    返回 (标准名, 是否被自动纠正)。候选全量本地, 无网络。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("选项值为空")
    opts = fo.get_options(kind, field)
    low = raw.casefold()
    for o in opts:
        if o.casefold() == low:
            return o, False
    sims = fo.similar_in(opts, raw, 5)
    if sims and sims[0][1] >= auto_threshold:
        return sims[0][0], True
    sug = "、".join(n for n, _ in sims[:5]) or "无(请检查拼写)"
    raise ValueError(f"未知选项: '{raw}'，你是不是想找: {sug}")


def resolve_option_cond(kind, c, corrections):
    """解析一条船/模块条件的选项值 (精确命中/自动纠正/无解抛错)。返回 True 表示处理过。"""
    if (c.get("type", "field") == "distance"
            or (kind, c.get("field")) not in OPTION_AUTOCORRECT
            or c.get("op") not in ("in", "not in", "=", "!=")):
        return False
    if c["op"] in ("in", "not in"):
        fixed_vals = []
        for v in c.get("values", []):
            canon, fixed = resolve_option(kind, c["field"], v)
            if fixed or v != canon:
                corrections.append((v, canon))
            fixed_vals.append(canon)
        c["values"] = fixed_vals
    else:
        canon, fixed = resolve_option(kind, c["field"], c.get("text", ""))
        if fixed or str(c.get("text", "")) != canon:
            corrections.append((str(c.get("text", "")), canon))
        c["text"] = canon
    return True


def normalize_conditions(kind, conditions):
    """校验并复制输入，搜索过程中不修改 GUI/调用者的条件。"""
    if kind not in ("stations", "systems"):
        raise ValueError("检索类型必须是 stations 或 systems")
    result = copy.deepcopy(conditions)
    for i, c in enumerate(result, 1):
        label = f"第{i}条条件"
        if c.get('type') == 'system_details':
            if kind != 'systems':
                raise ValueError('天体／最近有人条件仅用于星系查询')
            import system_filters
            c.update(system_filters.validate(c))
            continue
        if c.get('field') in COUNT_FIELDS:
            if kind != 'systems':
                raise ValueError('星系派生数量仅用于星系查询')
            if c.get('op') not in ('=', '!=', 'in', 'not in', '<', '<=', '>', '>=', 'between', 'outside'):
                raise ValueError('派生数量条件需要数值操作')
        if c.get("type", "field") == "distance":
            c["ref_system"] = str(c.get("ref_system", "")).strip()
            if not c["ref_system"]:
                raise ValueError(f"{label}: 请填写参考星系")
            if c.get("mode", "inside") not in ("inside", "outside"):
                raise ValueError(f"{label}: 未知距离模式")
            keys = ("min_ly", "max_ly")
        else:
            if not c.get("field"):
                raise ValueError(f"{label}: 缺少字段")
            op = c.get("op")
            if op not in ("in", "not in", "=", "!=", "contains", "true", "false",
                          "<", "<=", ">", ">=", "between", "outside"):
                raise ValueError(f"{label}: 未知比较操作")
            if op in ("in", "not in"):
                c["values"] = list(dict.fromkeys(str(v).strip() for v in c.get("values", [])
                                                if str(v).strip()))
                if not c["values"]:
                    raise ValueError(f"{label}: 至少选择一个值")
            if op in ("=", "!=", "contains", "<", "<=", ">", ">="):
                if c.get("text") in (None, ""):
                    raise ValueError(f"{label}: 缺少比较值")
            numeric = _server_type(kind, _server_name(kind, c["field"])) == "numeric"
            if numeric and op in ("<", "<=", ">", ">=", "=", "!="):
                v = _num(c["text"])
                if v is None or not math.isfinite(v):
                    raise ValueError(f"{label}: 数字必须有限")
                c["text"] = v
            if numeric and op in ("in", "not in"):
                for raw in c["values"]:
                    value = _num(raw)
                    if value is None or not math.isfinite(value):
                        raise ValueError(f"{label}: 数字必须有限")
            if _server_type(kind, _server_name(kind, c["field"])) == "timestamp":
                # 新鲜度相对标记在这里解析成绝对时间 (search/diagnose 都走这里, 口径一致)
                for key in ("min", "max"):
                    if c.get(key) not in (None, ""):
                        c[key] = resolve_freshness(c[key])
                if op in ("<", "<=", ">", ">=", "=", "!=", "contains") and c.get("text") not in (None, ""):
                    c["text"] = resolve_freshness(c["text"])
            if c.get("field") == "modules" and op in ("in", "=", "contains"):
                # 模块规格: 同一件在售条目必须同时满足名/等级/级别
                raw_classes = [v for v in (c.get("class") or []) if str(v).strip()]
                raw_ratings = [v for v in (c.get("rating") or []) if str(v).strip()]
                classes = list(dict.fromkeys(parse_module_class(v, label) for v in raw_classes))
                ratings = list(dict.fromkeys(parse_module_rating(v, label) for v in raw_ratings))
                if classes:
                    c["class"] = classes
                else:
                    c.pop("class", None)
                if ratings:
                    c["rating"] = ratings
                else:
                    c.pop("rating", None)
            if c.get("field") in ("ships", "modules") and c.get("fresh_days") is not None:
                # 新鲜度集成在船/模块条件行里 (卖X且数据N天内新), 只本地复核
                flabel, raw_fd = f"{label}: 新鲜度", c["fresh_days"]
                if isinstance(raw_fd, bool):
                    raise ValueError(f"{flabel}天数必须是正整数")
                try:
                    fd = int(raw_fd)
                except (TypeError, ValueError):
                    raise ValueError(f"{flabel}天数必须是正整数")
                if fd < 1:
                    raise ValueError(f"{flabel}天数必须是正整数")
                c["fresh_days"] = fd
            if c.get('discounted') is not None:
                if (kind != 'stations' or c.get('field') not in ('ships', 'modules')
                        or op not in ('in', '=', 'contains') or not isinstance(c['discounted'], bool)):
                    raise ValueError('折扣仅支持出售舰船／模组的属于其一、等于或包含条件，值必须为布尔值')
                if c['discounted'] is False:
                    c.pop('discounted')  # Legacy unfinished UI: no longer a "No" restriction.
            if c.get('personal_power'):
                if kind != 'stations' or c.get('field') != 'modules' or op not in ('in', '=', 'contains'):
                    raise ValueError('个人优惠仅支持采购模组／舰载武器')
                from powerplay_tool import normalize_power
                c['personal_power'] = normalize_power(c['personal_power'])
            keys = ("min", "max") if numeric and op in ("between", "outside") else ()
        for key in keys:
            raw = c.get(key)
            value = _num(raw)
            if raw not in (None, "") and (value is None or not math.isfinite(value)):
                raise ValueError(f"{label}: {key} 必须是有限数字")
            c[key] = value
        if keys:
            lo, hi = (c.get(k) for k in keys)
            if lo is not None and hi is not None and lo > hi:
                raise Contradiction(f"{label}: 最小值大于最大值")
            outside = c.get("mode") == "outside" if c.get("type") == "distance" else c.get("op") == "outside"
            if outside and (lo is None and hi is None or
                            c.get("type") == "distance" and lo in (None, 0) and hi is None):
                raise Contradiction(f"{label}: 无边界的范围外没有可满足的结果")
    return result


def _module_entry(names, classes, ratings):
    """单个模块条目: 同一件在售条目必须同时满足名/等级/级别 (已实测服务端语义)。
    names 为 None 表示只按规格缩小候选 (名包含走本地)。"""
    entry = {}
    if names:
        entry["name"] = {"value": sorted(names)}
    if classes:
        entry["class"] = {"value": sorted(classes)}
    if ratings:
        entry["rating"] = {"value": sorted(ratings)}
    return entry


def plan_server_filters(kind, conditions):
    """把条件翻译成官网过滤格式。返回 (filters, pushed数, notes, impossible原因|None)。
    官方格式: group {value:[...]} / numeric {comparison:'<=>',value:[lo,hi]} /
    boolean {value:true} / string {value:'x'} / combined [{name:{value:[...]}}] /
    distance {min,max}。推不动的只本地过滤。"""
    groups = {}    # sf -> [set(), ...] 求交
    bounds = {}    # sf -> [lo, lo_inc, hi, hi_inc]
    bools = {}     # sf -> True/False
    strings = {}   # sf -> text
    combined = {}  # (sf, sub) -> [set(), ...] (非模块: 并集超集+本地逐行AND)
    module_entries = []  # 模块: 每行一个条目 (服务端条目间AND, 与本地逐行AND同义)
    timestamps = {}  # sf -> [lo_str|None, hi_str|None]
    notes = []
    local_only = 0

    def add_bound(sf, lo, lo_inc, hi, hi_inc):
        b = bounds.setdefault(sf, [None, True, None, True])
        if lo is not None and (b[0] is None or lo > b[0] or (lo == b[0] and not lo_inc)):
            b[0], b[1] = lo, lo_inc
        if hi is not None and (b[2] is None or hi < b[2] or (hi == b[2] and not hi_inc)):
            b[2], b[3] = hi, hi_inc

    # 标量取交集；集合字段每一行是独立的存在性条件，不能取交集。
    seen_bools = {}
    seen_strings = {}
    for c in conditions:
        if c.get("type") == "distance":
            continue
        if c.get('type') == 'system_details' or c.get('field') in COUNT_FIELDS:
            local_only += 1
            continue
        f, op = c["field"], c["op"]
        if c.get('discounted') is not None:
            local_only += 1
            notes.append('折扣按势力／地点已知规则核对同件商品；未确认规则不命中，不含个人优惠')
        sf = _server_name(kind, f)
        st = _server_type(kind, sf)
        if st is None:
            local_only += 1
            continue
        if st == "group":
            if op == "in" and c.get("values"):
                groups.setdefault(sf, []).append(set(c["values"]))
            elif op == "=" and c.get("text", "") != "":
                groups.setdefault(sf, []).append({c["text"]})
            else:
                local_only += 1
        elif st in ("combined_name", "combined_commodity"):
            sub = "commodity" if st == "combined_commodity" else "name"
            if op == "in" and c.get("values"):
                names = set(c["values"])
                if sf == "modules":
                    module_entries.append(_module_entry(names, c.get("class"), c.get("rating")))
                else:
                    combined.setdefault((sf, sub), []).append(names)
            elif op == "=" and c.get("text", "") != "":
                if sf == "modules":
                    module_entries.append(_module_entry({c["text"]}, c.get("class"), c.get("rating")))
                else:
                    combined.setdefault((sf, sub), []).append({c["text"]})
            elif sf == "modules" and op == "contains" and (c.get("class") or c.get("rating")):
                # 名含糊匹配推不动, 但等级/级别可下推缩小候选 (本地仍逐件精确复核)
                module_entries.append(_module_entry(None, c.get("class"), c.get("rating")))
                local_only += 1
                notes.append("模块名包含只本地过滤 (等级/级别已下推)")
            else:
                local_only += 1
        elif st == "boolean":
            if op in ("true", "false"):
                value = op == "true"
                if sf in seen_bools and seen_bools[sf] != value:
                    return {}, 0, notes, f"矛盾: {sf} 同时要求是和否"
                seen_bools[sf] = value
            if op == "true":
                bools[sf] = True
            elif op == "false":
                # 服务器对false返回空(后端bug), 只本地过滤保证正确
                local_only += 1
                notes.append(f"{f}=否由本地过滤 (服务器不支持)")
            else:
                local_only += 1
        elif st == "string":
            if op == "=" and c.get("text", "") != "":
                text = str(c["text"]).casefold()
                if sf in seen_strings and seen_strings[sf] != text:
                    return {}, 0, notes, f"矛盾: {sf} 同时要求不同的等于值"
                seen_strings[sf] = text
                strings[sf] = c["text"]
            else:
                local_only += 1
        elif st == "numeric":
            if op == "=":
                v = _num(c.get("text"))
                if v is None:
                    raise ValueError(f"{f}: 等于条件需要数字")
                add_bound(sf, v, True, v, True)
            elif op == "between":
                add_bound(sf, _num(c.get("min")), True, _num(c.get("max")), True)
            elif op == "outside":
                lo, hi = _num(c.get("min")), _num(c.get("max"))
                if lo is None and hi is None:
                    local_only += 1
                elif lo is None:
                    add_bound(sf, hi, False, None, True)  # x>hi
                elif hi is None:
                    add_bound(sf, None, True, lo, False)  # x<lo
                else:
                    local_only += 1  # 两边开口去不掉中间, 本地过滤
                    notes.append(f"{f}中间挖空只本地过滤")
            elif op in ("<", "<=", ">", ">="):
                v = _num(c.get("text"))
                if v is None:
                    local_only += 1
                elif op == "<":
                    add_bound(sf, None, True, v, False)
                elif op == "<=":
                    add_bound(sf, None, True, v, True)
                elif op == ">":
                    add_bound(sf, v, False, None, True)
                else:
                    add_bound(sf, v, True, None, True)
            else:
                local_only += 1
        elif st == "timestamp":
            # 日期格式/时区由本地解释，不依赖后端的未验证格式。
            local_only += 1
        else:
            local_only += 1

    for fld in sorted({c.get("field") for c in conditions
                       if c.get("type", "field") != "distance"
                       and c.get("field") in FRESH_TS_KEY and c.get("fresh_days")}):
        notes.append(f"{'船厂' if fld == 'ships' else '改装'}新鲜度本地复核")

    filters, pushed = {}, 0
    for sf, sets in groups.items():
        spellings = {str(v).casefold(): v for values in sets for v in values}
        inter = set.intersection(*(set(str(v).casefold() for v in values) for values in sets))
        for c in conditions:
            if c.get("type") == "distance" or _server_name(kind, c["field"]) != sf:
                continue
            if c["op"] == "not in":
                inter.difference_update(str(v).casefold() for v in c.get("values", []))
            elif c["op"] == "!=":
                inter.discard(str(c.get("text", "")).casefold())
        if not inter:
            return {}, 0, notes, f"矛盾: {sf} 的多个属于条件无交集, 无需检索"
        filters[sf] = {"value": sorted(spellings[v] for v in inter)}
        pushed += 1
    for (sf, sub), sets in combined.items():
        # OR 候选集是 AND 目标集的超集；逐行 AND 在本地精确复核。
        values = set.union(*sets)
        filters[sf] = [{sub: {"value": sorted(values)}}]
        if len(sets) > 1:
            notes.append(f"{sf} 多行条件由本地逐行 AND 复核")
        pushed += 1
    if module_entries:
        # 每行一个条目, 服务端条目间 AND == 本地逐行 AND, 精确无需超集
        filters["modules"] = module_entries
        pushed += len(module_entries)
    for sf, b in bounds.items():
        lo, lo_inc, hi, hi_inc = b
        if lo is not None and hi is not None and (lo > hi or (lo == hi and not (lo_inc and hi_inc))):
            return {}, 0, notes, f"矛盾: {sf} 区间无交集, 无需检索"
        filters[sf] = {"comparison": "<=>",
                       "value": [lo if lo is not None else -BIG,
                                 hi if hi is not None else BIG]}
        pushed += 1
    for sf, v in bools.items():
        filters[sf] = {"value": v}
        pushed += 1
    for sf, t in strings.items():
        filters[sf] = {"value": t}
        pushed += 1
    for sf, (lo, hi) in timestamps.items():
        filters[sf] = {"comparison": "<=>", "value": [lo, hi]}
        pushed += 1
    if local_only:
        notes.append(f"{local_only} 条条件需本地复核")
    return filters, pushed, notes, None


LIST_NAME_KEYS = {"services", "ships", "economies", "marketplace", "export_commodities",
                  "import_commodities", "prohibited_commodities", "modules",
                  "system_power", "power", "minor_faction_presences"}

TIMESTAMP_KEYS = {"updated_at", "market_updated_at", "shipyard_updated_at",
                  "outfitting_updated_at", "last_updated_at",
                  "market_last_updated_at", "shipyard_last_updated_at",
                  "outfitting_last_updated_at"}


def _match_text_range(s, op, lo, hi):
    def date(value):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    try:
        s = date(s)
        lo = date(lo) if lo not in (None, "") else None
        hi = date(hi) if hi not in (None, "") else None
    except (ValueError, TypeError):
        return False
    if op in ("<", "<=", ">", ">="):
        t = lo if lo is not None else hi
        if op == "<":
            return s < t
        if op == "<=":
            return s <= t
        if op == ">":
            return s > t
        return s >= t
    inside = True
    if lo not in (None, ""):
        inside = inside and s >= lo
    if hi not in (None, ""):
        inside = inside and s <= hi
    return inside if op == "between" else (not inside)


def _names(v, key_hint=""):
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                if key_hint == "marketplace":
                    out.append(str(x.get("commodity", "")))
                else:
                    out.append(str(x.get("name", x.get("symbol", x))))
            else:
                out.append(str(x))
        return out
    return [str(v)] if v is not None else []


def field_raw(kind, row, field):
    # 本地复核必须读与服务器同名的键 (行数据键名==服务器字段名)
    if field == "marketplace":
        return row.get("market")
    return row.get(_server_name(kind, field))


def _item_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# 船/模块新鲜度看的行数据时间键 (集成在各自条件行里, 不再需要独立时间条件)
FRESH_TS_KEY = {"ships": "shipyard_updated_at", "modules": "outfitting_updated_at"}
FRESH_TS_CN = {"ships": "船厂数据时间", "modules": "改装数据时间"}


def fresh_ok(row, ts_key, days):
    """行数据时间键距今是否在 days 天内 (缺失/非法/未来都算无法确认=False)。"""
    ts = row.get(ts_key)
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    return 0 <= secs <= days * 86400


def _match_module_item(raw, cond, op):
    """模块逐件匹配: 存在一件条目, 名命中且等级/级别(如有限制)都符合。"""
    items = raw if isinstance(raw, list) else []
    if op == "in":
        want = {str(v).lower() for v in cond.get("values", [])}
    elif op == "=":
        want = {str(cond.get("text", "")).lower()}
    else:
        want = None
        substr = str(cond.get("text", "")).lower()
    classes = set(cond.get("class") or [])
    ratings = {str(v).upper() for v in (cond.get("rating") or [])}
    for it in items:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name", "")).lower()
        if want is not None:
            if nm not in want:
                continue
        elif substr not in nm:
            continue
        if classes and _item_int(it.get("class")) not in classes:
            continue
        if ratings and str(it.get("rating", "")).upper() not in ratings:
            continue
        return True
    return False


def matching_sale_items(kind, row, cond):
    """Return same-item name/specification/discount matches and their evidence."""
    field = cond['field']
    from station_discounts import discount_info
    basic = dict(cond)
    basic.pop('discounted', None)
    basic.pop('fresh_days', None)
    for item in field_raw(kind, row, field) or []:
        info = discount_info(row, item, field, personal_power=cond.get('personal_power', ''))
        if cond.get('discounted') is True and info['discounted'] is not True:
            continue
        single = dict(row, **{_server_name(kind, field): [item]})
        if match_field(kind, single, basic):
            yield item, info


def match_field(kind, row, cond):
    """单个普通条件, cond: {field, op, values/min/max/text}."""
    f, op = cond["field"], cond["op"]
    raw = field_raw(kind, row, f)
    if cond.get('discounted') is not None:
        if f not in ('ships', 'modules') or op not in ('in', '=', 'contains'):
            return False
        if cond.get('fresh_days') and not fresh_ok(row, FRESH_TS_KEY[f], cond['fresh_days']):
            return False
        return next(matching_sale_items(kind, row, cond), None) is not None

    if _server_type(kind, _server_name(kind, f)) == "numeric" and op in ("=", "!=", "in", "not in"):
        number = _num(raw)
        if number is None:
            return False
        values = cond.get("values", []) if op in ("in", "not in") else [cond.get("text")]
        hit = any(number == _num(value) for value in values)
        return hit if op in ("=", "in") else not hit

    if op in ("true", "false"):
        want = (op == "true")
        if raw is None:
            return False
        return raw in (True, 1, "true") if want else raw in (False, 0, "false")

    if f in LIST_NAME_KEYS or isinstance(raw, list):
        if f in FRESH_TS_KEY and cond.get("fresh_days"):
            # 集成新鲜度: 先卡数据年龄, 不新鲜直接淘汰
            if not fresh_ok(row, FRESH_TS_KEY[f], cond["fresh_days"]):
                return False
        if (f == "modules" and (cond.get("class") or cond.get("rating"))
                and op in ("in", "=", "contains")):
            return _match_module_item(raw, cond, op)
        names = [n.lower() for n in _names(raw, f)]
        want = [str(v).lower() for v in cond.get("values", [])]
        if op == "in":
            return any(w in names for w in want)
        if op == "not in":
            return all(w not in names for w in want)
        if op == "contains":
            t = cond.get("text", "").lower()
            return any(t in n for n in names)
        if op in ("=", "!="):
            t = str(cond.get("text", "")).lower()
            hit = t in names
            return hit if op == "=" else not hit
        return False

    if op in ("in", "not in", "=", "!=", "contains"):
        s = "" if raw is None else str(raw).lower()
        if op == "contains":
            return cond.get("text", "").lower() in s
        vals = [str(v).lower() for v in cond.get("values", [])]
        if op in ("=", "!="):
            vals = [str(cond.get("text", "")).lower()]
        if op == "in" or op == "=":
            return s in vals
        return s not in vals

    # 数值比较 (时间字段按ISO字符串比较)
    if f in TIMESTAMP_KEYS:
        s = "" if raw is None else str(raw)
        if op in ("<", "<=", ">", ">=", "between", "outside"):
            if op in ("<", "<=", ">", ">="):
                return _match_text_range(s, op, cond.get("text"), None)
            return _match_text_range(s, op, cond.get("min"), cond.get("max"))
        return False
    try:
        num = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return False
    if num is None:
        return False
    lo, hi = cond.get("min"), cond.get("max")
    if op == "<":
        return num < float(cond.get("text", 0))
    if op == "<=":
        return num <= float(cond.get("text", 0))
    if op == ">":
        return num > float(cond.get("text", 0))
    if op == ">=":
        return num >= float(cond.get("text", 0))
    if op == "between":
        ok = True
        if lo not in (None, ""):
            ok = ok and num >= float(lo)
        if hi not in (None, ""):
            ok = ok and num <= float(hi)
        return ok
    if op == "outside":
        inside = True
        if lo not in (None, ""):
            inside = inside and num >= float(lo)
        if hi not in (None, ""):
            inside = inside and num <= float(hi)
        return not inside
    return False


def match_distance(kind, row, cond, coord_cache):
    """cond: {ref_system, min_ly, max_ly, mode inside/outside}."""
    rc = result_coords(kind, row)
    if rc is None:
        return False
    ref = cond["ref_system"].strip()
    if not ref:
        return False
    ck = ref.lower()
    if ck not in coord_cache:
        coord_cache[ck] = get_system_coords(ref)
    d = dist3(rc, coord_cache[ck])
    lo = cond.get("min_ly")
    hi = cond.get("max_ly")
    inside = True
    if lo not in (None, ""):
        inside = inside and d >= float(lo)
    if hi not in (None, ""):
        inside = inside and d <= float(hi)
    row.setdefault("_distances", {})[ref] = round(d, 2)
    return inside if cond.get("mode", "inside") == "inside" else (not inside)


def match_all(kind, row, conditions, coord_cache):
    for c in conditions:
        if c.get("type") == "distance":
            if not match_distance(kind, row, c, coord_cache):
                return False
        elif c.get('type') == 'system_details':
            import system_filters
            if system_filters.outcome(row, c) is not True:
                return False
        else:
            if not match_field(kind, row, c):
                return False
    return True


def match_candidate(kind, row, conditions, coord_cache, filters, missing):
    """后端有些字段仅可筛选、未返回。精确下推的条件信任后端。
    无法复核的本地条件不冒充通过，并汇总缺失字段供用户诊断。
    """
    for c in sorted(conditions, key=lambda c: 2 if c.get('type') == 'system_details' else 1 if c.get('field') in COUNT_FIELDS else 0):
        if c.get('type') == 'system_details':
            import system_filters
            hit = system_filters.outcome(row, c)
            if hit is None:
                missing.add('天体／最近有人条件')
            if hit is not True:
                return False
            continue
        if c.get("type") == "distance":
            if not match_distance(kind, row, c, coord_cache):
                return False
            continue
        f, op = c["field"], c["op"]
        sf = _server_name(kind, f)
        if field_raw(kind, row, f) is None:
            st = _server_type(kind, sf)
            exact = (st == "group" and op in ("in", "=")) or (st == "boolean" and op == "true")
            if st in ("combined_name", "combined_commodity") and op in ("in", "="):
                positive = [x for x in conditions if x.get("type") != "distance"
                            and _server_name(kind, x["field"]) == sf and x["op"] in ("in", "=")]
                exact = len(positive) == 1
            if sf in filters and exact and not c.get("fresh_days") and c.get('discounted') is None:
                # 有集成新鲜度时服务端没筛过时间, 不能信任, 必须本地复核
                continue
            missing.add(f)
            return False
        if f in FRESH_TS_KEY and c.get("fresh_days") and row.get(FRESH_TS_KEY[f]) is None:
            missing.add(FRESH_TS_CN[f])
            return False
        if not match_field(kind, row, c):
            return False
    return True


def _dist_bound(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def pick_server_ref(conditions):
    """选对服务器最有用的参考点: 范围内+上限最小的优先 (交集一定在它圈内)。
    返回 (ref_system, min_ly, max_ly, sort_only_bool)。"""
    candidates = []
    for c in conditions:
        if c.get("type") != "distance":
            continue
        lo, hi = _dist_bound(c.get("min_ly")), _dist_bound(c.get("max_ly"))
        if c.get("mode", "inside") == "inside":
            candidates.append((c["ref_system"], lo, hi, False))
        elif hi is None and lo is not None:
            candidates.append((c["ref_system"], None, lo, False))
        elif lo in (None, 0) and hi is not None:
            candidates.append((c["ref_system"], hi, None, False))
    if candidates:
        return min(candidates, key=lambda v: (v[2] is None, v[2] or 0))
    anyd = [c for c in conditions
            if c.get("type") == "distance" and (c.get("ref_system") or "").strip()]
    if anyd:
        return (anyd[0]["ref_system"].strip(), None, None, True)
    return (None, None, None, True)


def build_server_payload(kind, conditions, size=100, page=0):
    """组装官网格式的单次请求。距离取最紧的范围内条件推 reference+范围。
    返回 payload (impossible时抛 Contradiction)。"""
    conditions = normalize_conditions(kind, conditions)
    filters, _pushed, _notes, impossible = plan_server_filters(kind, conditions)
    if impossible:
        raise Contradiction(impossible)
    ref_system, rmin, rmax, sort_only = pick_server_ref(conditions)
    if ref_system and not sort_only:
        # 只推与该参考点相关的范围: 范围内交集 + 同点的单边范围外转换
        eff = [None, True, None, True]
        for c in conditions:
            if c.get("type") != "distance" or (c.get("ref_system") or "").strip().casefold() != ref_system.casefold():
                continue
            if c.get("mode", "inside") == "inside":
                lo, hi = _dist_bound(c.get("min_ly")), _dist_bound(c.get("max_ly"))
                if lo is not None and (eff[0] is None or lo > eff[0]):
                    eff[0] = lo
                if hi is not None and (eff[2] is None or hi < eff[2]):
                    eff[2] = hi
            else:
                lo, hi = _dist_bound(c.get("min_ly")), _dist_bound(c.get("max_ly"))
                if lo in (None, 0) and hi is not None and (eff[0] is None or hi >= eff[0]):
                    eff[0] = hi  # 范围外0~X ≡ >X
                    eff[1] = False
                elif hi is None and lo is not None and (eff[2] is None or lo <= eff[2]):
                    eff[2] = lo  # 范围外X~∞ ≡ <X
                    eff[3] = False
        if eff[0] is not None and eff[2] is not None and (
                eff[0] > eff[2] or (eff[0] == eff[2] and not (eff[1] and eff[3]))):
            raise Contradiction(f"矛盾: 距 {ref_system} 的范围无交集")
        dd = {}
        if eff[0] is not None:
            dd["min"] = eff[0]
        if eff[2] is not None:
            dd["max"] = eff[2]
        if dd:
            filters["distance"] = dd
    payload = {"filters": filters, "size": size, "page": page,
               "sort": [{"distance": {"direction": "asc"}}] if ref_system else [{"updated_at": {"direction": "desc"}}]}
    if ref_system:
        payload["reference_system"] = ref_system
    return payload


class Contradiction(Exception):
    pass


def _report(progress, message, **info):
    """进度回调保持兼容: 新式回调收 (message, info), 老式单参数回调只收 message。"""
    if not progress:
        return
    try:
        progress(message, info)
    except TypeError:
        progress(message)


def sphere_intersection_box(a, ra, b, rb):
    """两球交集的精确轴对齐包围盒（忽略距离下限，仅缩小候选）。"""
    d = dist3(a, b)
    if d > ra + rb or min(ra, rb) < 0:
        raise Contradiction("距离圈不相交")
    if d + min(ra, rb) <= max(ra, rb):
        center, radius = (a, ra) if ra <= rb else (b, rb)
        return [(v - radius, v + radius) for v in center]
    unit = [(b[i] - a[i]) / d for i in range(3)]
    along = (ra * ra - rb * rb + d * d) / (2 * d)
    center = [a[i] + along * unit[i] for i in range(3)]
    radius = math.sqrt(max(0, ra * ra - along * along))
    bounds = []
    for axis in range(3):
        span = radius * math.sqrt(max(0, 1 - unit[axis] ** 2))
        extrema = [center[axis] - span, center[axis] + span]
        # 极值要么落在两球面的交圆上，要么是某个球在该轴的极点。
        for c, r, other, other_r in ((a, ra, b, rb), (b, rb, a, ra)):
            for sign in (-1, 1):
                pole = list(c)
                pole[axis] += sign * r
                if dist3(pole, other) <= other_r + 1e-9:
                    extrema.append(pole[axis])
        bounds.append((min(extrema), max(extrema)))
    return bounds


def tighten_distance_payload(kind, payload, conditions, coord_cache, notes):
    """将多距离条件的安全包围体下推；最终仍按所有原始距离条件复核。"""
    circles = [(c, coord_cache[c["ref_system"].lower()], c["max_ly"])
               for c in conditions if c.get("type") == "distance"
               and c.get("mode", "inside") == "inside" and c.get("max_ly") is not None]
    if len(circles) < 2:
        return payload
    payload = copy.deepcopy(payload)
    boxes = [(max(p[axis] - r for _, p, r in circles),
              min(p[axis] + r for _, p, r in circles)) for axis in range(3)]
    best = None
    for i, (ca, a, ra) in enumerate(circles):
        for cb, b, rb in circles[i + 1:]:
            try:
                pair_box = sphere_intersection_box(a, ra, b, rb)
            except Contradiction:
                raise Contradiction(f"矛盾: {ca['ref_system']} 与 {cb['ref_system']} 的距离圈不相交")
            boxes = [(max(lo, pair_box[k][0]), min(hi, pair_box[k][1]))
                     for k, (lo, hi) in enumerate(boxes)]
            # 恒等式 |P-M|²=(|P-A|²+|P-B|²)/2-|A-B|²/4。
            # 两球交集一定落在此中点球内，包括半径不等的情况。
            radius = math.sqrt(max(0, (ra * ra + rb * rb) / 2 - dist3(a, b) ** 2 / 4))
            if best is None or radius < best[0]:
                best = (radius, tuple((a[k] + b[k]) / 2 for k in range(3)))
    eps = 1e-7  # 扩张浮点计算边界，避免把刚好在球面上的结果裁掉。
    filters = payload["filters"]
    if kind == "systems":
        for axis, (lo, hi) in zip(("x", "y", "z"), boxes):
            existing = filters.get(axis, {}).get("value", [-BIG, BIG])
            lo, hi = max(lo - eps, existing[0]), min(hi + eps, existing[1])
            if lo > hi:
                raise Contradiction(f"矛盾: 多距离交集与 {axis} 坐标条件不相交")
            filters[axis] = {"comparison": "<=>", "value": [lo, hi]}
        notes.append("多距离交集坐标包围盒已下推")
    # 普通 distance 字段相对于原参考点，存在时保留该参考点的语义。
    ordinary_distance = any(c.get("type") != "distance" and c.get("field") == "distance"
                            for c in conditions)
    old_max = filters.get("distance", {}).get("max", BIG)
    if not ordinary_distance and best[0] + eps < old_max:
        radius, center = best
        payload.pop("reference_system", None)
        payload["reference_coords"] = dict(zip(("x", "y", "z"), center))
        filters["distance"] = {"max": radius + eps}
        notes.append(f"从交集中心检索，候选球半径 {radius:.2f}ly")
    return payload


def search(kind, conditions, want=200, max_pages=25, progress=None,
            corrections=None, stop=None, notes=None, page_size=500, row_filter=None, http=None):
    """一次规划 -> 流式分页 -> 去重 -> 精确复核。
    返回 (rows, total_server, scanned)，终止原因记录在 notes。
    count 是后端封顶的候选数，不能据此判断已遍历全库。
    """
    if notes is None:
        notes = []
    if want < 1 or max_pages < 1 or not 1 <= page_size <= 500:
        raise ValueError("结果数和页数必须大于零，每页数量必须在 1~500 之间")
    cancelled = lambda: stop is not None and stop.is_set()
    if cancelled():
        notes.append("已手动停止，尚未发送请求")
        return [], 0, 0
    try:
        conditions = normalize_conditions(kind, conditions)
        template = build_server_payload(kind, conditions)
    except Contradiction as exc:
        notes.append(str(exc))
        return [], 0, 0
    filters, pushed, pnotes, _ = plan_server_filters(kind, conditions)
    detailed = kind == 'systems' and any(c.get('type') == 'system_details' or c.get('field') in COUNT_FIELDS for c in conditions)
    cheap = [c for c in conditions if c.get('type') != 'system_details' and c.get('field') not in COUNT_FIELDS]
    notes.extend(pnotes)
    per = page_size
    coord_cache = {}
    if corrections is None:
        corrections = []
    for c in conditions:
        if cancelled():
            notes.append("已手动停止")
            return [], 0, 0
        if c.get("type") == "distance" and c.get("ref_system"):
            _report(progress, f"正在解析参考星系: {c['ref_system']}...",
                    phase="resolve", scanned=0, hits=0, total=0,
                    page=0, pages=max_pages, want=want)
            canon, coords, fixed = resolve_ref(c["ref_system"].strip())
            old = c["ref_system"].strip()
            if fixed or old != canon:
                corrections.append((c["ref_system"].strip(), canon))
            c["ref_system"] = canon
            coord_cache[old.lower()] = coords
            coord_cache.setdefault(canon.lower(), coords)
        else:
            # 船/模块名解析纠正 (本地候选, 无网络): 精确命中用库原名,
            # 打错自动纠正并记入 corrections, 无解抛错附带建议。
            resolve_option_cond(kind, c, corrections)
    try:
        template = build_server_payload(kind, conditions, size=per)
        template = tighten_distance_payload(kind, template, conditions, coord_cache, notes)
    except Contradiction as exc:
        notes.append(str(exc))
        return [], 0, 0
    notes.append(f"{pushed} 个条件服务器直查"
                 + (" + 距离范围" if "distance" in template["filters"] else ""))
    out, total, scanned, page = [], 0, 0, 0
    seen = set()
    missing = set()
    reason = "达到翻页上限，检索未完成；当前命中数不是全库结果数"
    while len(out) < want and page < max_pages:
        if cancelled():
            reason = "已手动停止，返回部分结果"
            break
        p = dict(template, page=page)
        _report(progress, f"正在请求第{page + 1}页 (每页{per}条)，已命中 {len(out)}...",
                phase="fetch", scanned=scanned, hits=len(out), total=total,
                page=page, pages=max_pages, per=per, want=want)
        d = (http or _http_json)(f"{SPansh_BASE}/{kind}/search", p)
        if not isinstance(d, dict) or not isinstance(d.get("results"), list):
            raise ValueError(f"服务器响应无效: {str(d)[:300]}")
        if page == 0:
            total = d.get("count", 0)
        rs = d.get("results", [])
        if not rs:
            reason = "候选分页已取完"
            break
        if detailed:
            import system_filters
            rs = [dict(r) for r in rs]
            survivors, pending = [], set()
            for r in rs:
                ident = (kind, r.get('id64'))
                if ident[1] is None:
                    ident = (kind, r.get('system_name'), r.get('name'), result_coords(kind, r))
                if ident in seen or ident in pending:
                    continue
                pending.add(ident)
                if not is_excluded_system(kind, r) and match_candidate(kind, r, cheap, coord_cache, template['filters'], missing):
                    survivors.append(r)
            try:
                system_filters.prepare(survivors, conditions, stop=stop, max_pages=max_pages,
                                       progress=lambda: _report(progress, '正在复核星系详细条件…',
                                                                phase='fetch', scanned=scanned, hits=len(out),
                                                                total=total, page=page, pages=max_pages, want=want))
            except InterruptedError:
                reason = '已手动停止，返回部分结果'
                break
        new_count = 0
        for r in rs:
            if cancelled():
                reason = "已手动停止，返回部分结果"
                break
            ident = (kind, r.get("id") if kind == "stations" else r.get("id64"))
            if ident[1] is None:
                ident = (kind, r.get("system_name"), r.get("name"), result_coords(kind, r))
            if ident in seen:
                continue
            seen.add(ident)
            new_count += 1
            scanned += 1
            if is_excluded_system(kind, r):
                continue
            r.pop("_distances", None)
            if match_candidate(kind, r, conditions, coord_cache, template["filters"], missing):
                for c in conditions:
                    if c.get("type") == "distance":
                        match_distance(kind, r, c, coord_cache)
                # Tool-specific checks run before a match consumes the result limit.
                if row_filter is not None and not row_filter(r):
                    continue
                out.append(r)
                if len(out) >= want:
                    reason = "已达到所需结果数，返回首批命中"
                    break
        eff = f"{len(out)*100//scanned}%" if scanned else "-"
        _report(progress, f"服务器直查第{page+1}页, 已扫 {scanned}, 命中 {len(out)} (有效率{eff})...",
                phase="page", scanned=scanned, hits=len(out), total=total,
                page=page + 1, pages=max_pages, per=per, want=want)
        if cancelled() or len(out) >= want:
            break
        if not new_count:
            reason = "服务器重复返回同一批候选，检索未完成"
            break
        if len(rs) < per:
            reason = "候选分页已取完"
            break
        page += 1
    if isinstance(total, (int, float)) and total >= 10000:
        notes.append("服务器候选计数已封顶 (10000)，不代表全库总数")
    if missing:
        notes.append("部分候选缺少本地复核字段，无法确认: " + ", ".join(sorted(missing)))
    notes.append(reason)
    return out, total, scanned


def module_spec_suffix(c):
    """模块规格后缀, 如 ' [5级/B级]' (诊断/展示用)。"""
    if c.get("field") != "modules":
        return ""
    parts = []
    if c.get("class"):
        parts.append("/".join(f"{v}级" for v in c["class"]))
    if c.get("rating"):
        parts.append("/".join(f"{v}级" for v in c["rating"]))
    return f" [{'/'.join(parts)}]" if parts else ""


def fresh_suffix(c):
    """集成新鲜度后缀, 如 ' [数据7天内]' (诊断/展示用)。"""
    if c.get("field") in FRESH_TS_KEY and c.get("fresh_days"):
        return f" [数据{c['fresh_days']}天内]"
    return ""


def cond_desc(c):
    if c.get('type') == 'system_details':
        return '天体／最近有人条件'
    if c.get("type") == "distance":
        mode = "内" if c.get("mode", "inside") == "inside" else "外"
        from result_format import format_ly
        return f"距{c.get('ref_system')}{format_ly(c.get('min_ly') if c.get('min_ly') is not None else 0)}~{format_ly(c.get('max_ly'), '∞')}ly范围{mode}"
    op = c.get("op")
    spec = module_spec_suffix(c) + fresh_suffix(c)
    if op in ("in", "not in"):
        return f"{c.get('field')} {op} {c.get('values')}{spec}"
    if op in ("between", "outside"):
        return f"{c.get('field')} {op} {c.get('min')}~{c.get('max')}"
    if op in ("true", "false"):
        return f"{c.get('field')} ={op}"
    return f"{c.get('field')} {op} {c.get('text', '')}{spec}"


def diagnose(kind, conditions, pages=3):
    """取前 pages 页候选, 统计每个条件各自的通过率, 定位是哪个条件杀光了结果。
    返回 ([(描述, 通过数, 样本数)], 样本数)。"""
    conditions = normalize_conditions(kind, conditions)
    coord_cache = {}
    for c in conditions:
        if c.get("type") == "distance" and c.get("ref_system"):
            canon, coords, fixed = resolve_ref(c["ref_system"].strip())
            if fixed:
                c["ref_system"] = canon
            coord_cache.setdefault(canon.lower(), coords)
        else:
            resolve_option_cond(kind, c, [])
    sample = []
    for page in range(pages):
        p = build_server_payload(kind, conditions, size=100, page=page)
        d = _http_json(f"{SPansh_BASE}/{kind}/search", p)
        rs = d.get("results", [])
        sample.extend(rs)
        if len(rs) < 100:
            break
    stats = []
    if kind == 'systems' and any(c.get('type') == 'system_details' or c.get('field') in COUNT_FIELDS for c in conditions):
        import system_filters
        system_filters.prepare(sample, conditions, max_pages=pages)
    for c in conditions:
        hit = 0
        for r in sample:
            r.pop("_distances", None)
            if c.get("type") == "distance":
                if match_distance(kind, r, c, dict(coord_cache)):
                    hit += 1
            elif c.get('type') == 'system_details':
                import system_filters
                if system_filters.outcome(r, c) is True:
                    hit += 1
            elif match_field(kind, r, c):
                hit += 1
        stats.append((cond_desc(c), hit, len(sample)))
    return stats, len(sample)


def carrier_parking_summary(row):
    """统计已收录航母；站点类型不完整时航母数未知，不估计车位。"""
    stations = row.get("stations")
    if not isinstance(stations, list) or any(not isinstance(s, dict) for s in stations):
        return None, None, "未知", "站点数据缺失，无法判断"
    count = len(stations)
    if any(not isinstance(s.get('type'), str) or not s['type'].strip() for s in stations):
        return count, None, "未知", "航母类型数据不完整"
    carriers = sum("carrier" in s['type'].casefold() for s in stations)
    return count, carriers, "已收录", "按已收录航母统计"


def carrier_parking_search(ref_system, radius_ly=30,
                           exclude_permit=True, max_pages=20, progress=None, stop=None,
                           min_carriers=None, max_carriers=None):
    """检索半径内星系的航母数量，按含边界的数量范围筛选。"""
    name = (ref_system or "").strip()
    if not name:
        raise ValueError("请填写参考星系")
    radius = _num(radius_ly)
    if isinstance(radius_ly, bool) or radius is None or not math.isfinite(radius) or not 0 < radius <= 50:
        raise ValueError("搜索半径必须大于 0 且不超过 50 ly")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("翻页上限必须是正整数")
    for bound in (min_carriers, max_carriers):
        if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int) or bound < 0):
            raise ValueError("航母数量须为非负整数，留空不限")
    if min_carriers is not None and max_carriers is not None and min_carriers > max_carriers:
        raise ValueError("最少航母数不能大于最多航母数")
    conditions = [dict(type="distance", ref_system=name, min_ly=None,
                       max_ly=radius, mode="inside")]
    corrections, notes = [], []
    systems, total, scanned = search(
        "systems", conditions, want=max_pages * 500 + 1, max_pages=max_pages,
        page_size=500, progress=progress, stop=stop, corrections=corrections, notes=notes)
    rows, unknown = [], 0
    for system in systems:
        count, carriers, category, label = carrier_parking_summary(system)
        if carriers is None:
            unknown += 1
        if exclude_permit and system.get("needs_permit") is not False:
            continue
        if (min_carriers is not None or max_carriers is not None) and (
                carriers is None or (min_carriers is not None and carriers < min_carriers)
                or (max_carriers is not None and carriers > max_carriers)):
            continue
        row = dict(system)
        row.update(_station_count=count, _carrier_count=carriers,
                   _parking_category=category, _parking_label=label,
                   _parking_distance=next(iter(system.get("_distances", {}).values()), None))
        rows.append(row)
    rows.sort(key=lambda r: (r["_parking_distance"] if r["_parking_distance"] is not None
                            else float("inf"), r.get("name", "")))
    canonical = dict(corrections).get(name, name)
    info = dict(reference=canonical, radius=radius, scanned=scanned, total=total,
                complete="候选分页已取完" in notes, unknown=unknown,
                notes=notes, corrections=corrections)
    return info, rows


def midpoint_search(name_a, name_b, want=20, populated_only=False,
                    exclude_permit=False, max_pages=10, progress=None,
                    corrections=None):
    """找离 A、B 两系中点最近的星系。
    星系名打错自动纠正(记入 corrections), 不存在抛 ValueError(带建议)。
    返回 (info, rows): info={a, b, mid, ab}。"""
    if corrections is None:
        corrections = []
    _report(progress, '解析参考星系', phase='resolve')
    canon_a, ca, fa = resolve_ref((name_a or "").strip())
    canon_b, cb, fb = resolve_ref((name_b or "").strip())
    if fa:
        corrections.append(((name_a or "").strip(), canon_a))
    if fb:
        corrections.append(((name_b or "").strip(), canon_b))
    mid = ((ca[0] + cb[0]) / 2.0, (ca[1] + cb[1]) / 2.0, (ca[2] + cb[2]) / 2.0)
    ab = dist3(ca, cb)
    rows, total, page = [], 0, 0
    exhausted = False
    while len(rows) < want and page < max_pages:
        p = {"filters": {}, "size": 100, "page": page,
             "sort": [{"distance": {"direction": "asc"}}],
             "reference_coords": {"x": mid[0], "y": mid[1], "z": mid[2]}}
        d = _http_json(f"{SPansh_BASE}/systems/search", p)
        if page == 0:
            total = d.get("count", 0)
        rs = d.get("results", [])
        if not rs:
            exhausted = True
            break
        for r in rs:
            if is_excluded_system("systems", r):
                continue
            try:
                rc = (float(r["x"]), float(r["y"]), float(r["z"]))
            except (KeyError, TypeError, ValueError):
                continue
            if populated_only and not (r.get("population") or 0) > 0:
                continue
            if exclude_permit and r.get("needs_permit"):
                continue
            r["_d_mid"] = round(dist3(rc, mid), 2)
            r["_d_a"] = round(dist3(rc, ca), 2)
            r["_d_b"] = round(dist3(rc, cb), 2)
            rows.append(r)
            if len(rows) >= want:
                break
        _report(progress, f"已找 {len(rows)}/{want}...",
                phase="page", done=len(rows), work_total=want, stage='目标结果',
                scanned=len(rows), hits=len(rows), total=total,
                page=page + 1, pages=max_pages, want=want)
        if len(rs) < 100:
            exhausted = True
            break
        page += 1
    info = {"a": canon_a, "b": canon_b, "mid": tuple(round(v, 2) for v in mid),
            "ab": round(ab, 2), "complete": exhausted or len(rows) >= want}
    return info, rows
