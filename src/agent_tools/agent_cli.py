"""Headless JSON CLI over the existing EDF search core; no GUI or Tk import.

One request per process: UTF-8 JSON on stdin (or --input FILE), one JSON
envelope on stdout, diagnostics on stderr. Machine keys/codes are English;
human-facing note text follows the search core (currently Chinese).
"""
import argparse
from copy import deepcopy
import dataclasses
import json
import math
import sys
import threading
import time
from pathlib import Path

# The search core lives in src; the agent interface stays in this subfolder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from system_filter_fields import COUNT_FIELDS
import app_metadata
import colonisation_tool
import engineer_destinations
import engineer_shopping
import filter_engine as eng
import full_outfitting
import hge_tool
import journal_location
import module_spec_pairs
import outfitting_snapshot
import powerplay_tool
import pve_tool
import rare_goods
import spansh_filter
import waypoint_route

INTERFACE_VERSION = '1'
DEFAULT_RETURN_ROWS = 200
MAX_RETURN_ROWS = 10000
SYSTEM_FIELDS = dict(spansh_filter.SYSTEM_FIELDS, **COUNT_FIELDS)

CONDITION_OPS = ('in', 'not in', '=', '!=', 'contains',
                 '<', '<=', '>', '>=', 'between', 'outside', 'true', 'false')

OUTFITTING_OPTIONS = ('other_discounts', 'neutral_ships', 'federal_ships',
                      'imperial_ships', 'guardian', 'special_equipment',
                      'require_discount', 'ax_weapons', 'universal_limpets')


class _Deadline:
    """Set a threading.Event once, from a timer thread; callers poll it."""

    def __init__(self, seconds):
        self.event = threading.Event()
        self._timer = None
        if seconds is not None:
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) \
                    or not 0 < seconds <= 86400:
                raise ValueError('limits.deadline_seconds must be a number from 0 (exclusive) to 86400')
            self._timer = threading.Timer(seconds, self.event.set)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        if self._timer is not None:
            self._timer.cancel()


def _limit(table, key, default, minimum, maximum):
    value = (table or {}).get(key, default)
    if value is None and key in ('want', 'max_pages'):
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{key} must be an integer from {minimum} to {maximum}')
    return value


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return value


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _rows(rows, want, fields):
    truncated = len(rows) > want
    rows = rows[:want]
    if fields is not None:
        rows = [{key: row.get(key) for key in fields} for row in rows]
    return _clean(rows), truncated


def _search_complete(notes):
    return any(note == '候选分页已取完' or '已达到所需结果数' in note for note in notes)


def _search_status(notes, stopped):
    if _search_complete(notes):
        return 'ok', 'Candidate pages exhausted or requested result count reached.'
    if stopped:
        return 'cancelled', 'Stopped before candidates were exhausted; verified hits are retained.'
    return 'partial', ('Page limit reached before exhausting candidates; '
                       'hits are not the full result set and absence of further hits is unconfirmed.')


def _stopped(args):
    return bool(args.get('stop') is not None and args['stop'].is_set())


def _options(args):
    group = args.get('group')
    groups = {
        'condition_operators': list(CONDITION_OPS),
        'system_fields': dict(sorted(SYSTEM_FIELDS.items())),
        'station_fields': dict(sorted(spansh_filter.STATION_FIELDS.items())),
        'colonisation_body_fields': dict(sorted(colonisation_tool.BODY_FIELDS.items())),
        'colonisation_ring_fields': dict(sorted(colonisation_tool.RING_FIELDS.items())),
        'colonisation_operators': list(colonisation_tool.OPERATORS),
        'colonisation_values': colonisation_tool.VALUES,
        'hge_materials': hge_tool.MATERIAL_LABELS,
        'hge_population_options': hge_tool.POPULATION_OPTIONS,
        'hge_freshness_options': hge_tool.FRESHNESS_OPTIONS,
        'powerplay_powers': list(powerplay_tool.POWERS),
        'rare_goods_sources': list(rare_goods.SOURCE_SYSTEMS),
        'engineer_destinations': list(engineer_destinations.CHOICES),
        'engineer_module_specs': {name: codes.split() for name, codes in module_spec_pairs.PAIR_CODES.items()},
        'modules_condition_keys': {
            'class': 'List of class digits as strings, e.g. ["5"]; combines AND-wise with the module name',
            'rating': 'List of rating letters as strings, e.g. ["A"]',
            'weapon_mode': 'Fixed | Gimballed | Turreted',
            'module_slot': 'Slot-group label as used by the GUI condition editor',
            'fresh_days': 'Positive int: the offer is in stock and its data is no older than N days',
            'discounted': 'true: match discounted offers only (discount rules, not personal discounts)',
        },
        'engineer_purchase_keys': {
            'name': 'Module or ship-weapon product name (required)',
            'class': 'Single class digit, e.g. 5 (optional)',
            'rating': 'Single rating letter, e.g. A (optional)',
            'weapon_mode': 'Fixed | Gimballed | Turreted (optional)',
            'discounted': 'true (default): only stations known to sell it discounted',
            'fresh_days': 'Positive int: offer data no older than N days (optional)',
        },
    }
    if group is None:
        return dict(groups=sorted(groups)), 'ok', dict(complete=True), {}
    if group not in groups:
        raise ValueError(f'Unknown options group {group!r}; available groups: ' + ', '.join(sorted(groups)))
    return dict(group=group, values=_clean(groups[group])), 'ok', dict(complete=True), {}


def _generic_search(kind, args):
    conditions = args.get('conditions')
    if not isinstance(conditions, list) or not conditions:
        raise ValueError('conditions must be a non-empty list of condition objects')
    normalized = eng.normalize_conditions(kind, deepcopy(conditions))
    want = _limit(args, 'want', DEFAULT_RETURN_ROWS, 1, 10000)
    max_pages = _limit(args, 'max_pages', 25, 1, 1000)
    corrections, notes = [], []
    rows, total, scanned = eng.search(kind, normalized, want=want, max_pages=max_pages,
                                      stop=args['stop'], corrections=corrections, notes=notes)
    results, truncated = _rows(rows, args['return_rows'], args['fields'])
    status, reason = _search_status(notes, _stopped(args))
    coverage = dict(complete=status == 'ok', reason=reason, scanned=scanned,
                    server_count=total, returned=len(results), truncated=truncated)
    payload = dict(kind=kind, conditions=_clean(normalized), results=results)
    extras = dict(notes=notes, corrections=corrections)
    return payload, status, coverage, extras


def _search_systems(args):
    return _generic_search('systems', args)


def _search_stations(args):
    return _generic_search('stations', args)


def _criteria_kwargs(criteria_class, args, skip=()):
    names = {field.name for field in dataclasses.fields(criteria_class)}
    return {key: args[key] for key in names if key in args and key not in skip}


def _pve(args):
    criteria = pve_tool.Criteria(**_criteria_kwargs(pve_tool.Criteria, args)).validate()
    info, rows = pve_tool.search(criteria, stop=args['stop'])
    results, truncated = _rows(rows, args['return_rows'], args['fields'])
    stopped = _stopped(args)
    complete = bool(info.get('complete')) and not stopped
    status = 'ok' if complete else 'cancelled' if stopped else 'partial'
    coverage = dict(
        complete=complete,
        reason=('Complete dataset scan finished; site evidence distinguishes confirmed RES, ring-inferred sites and unknown records.'
                if complete else 'Stopped.' if status == 'cancelled' else
                'Dataset scan incomplete (errors, stop or page limits); an empty result does not prove absence.'),
        scanned=info.get('scanned', 0), mode=info.get('mode'),
        confirmed_res=info.get('confirmed_res', 0), inferred_res=info.get('inferred_res', 0),
        hits=info.get('hits'), detail_requests=info.get('detail_requests'),
        returned=len(results), truncated=truncated)
    payload = dict(criteria=_clean(vars(criteria)), results=results)
    extras = dict(notes=info.get('notes', []), errors=info.get('errors', []))
    return payload, status, coverage, extras


def _hge(args):
    raw = dict(args)
    for key, table in (('population', hge_tool.POPULATION_OPTIONS), ('freshness', hge_tool.FRESHNESS_OPTIONS)):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            match = next((label for label, bound in table.items() if bound == value), None)
            if match is None:
                raise ValueError(f'{key}: no option equals {value}; see options group hge_{key}_options')
            raw[key] = match
    kwargs = _criteria_kwargs(hge_tool.Criteria, raw)
    criteria = hge_tool.Criteria(**kwargs).validate()
    result = hge_tool.search(criteria, stop=args['stop'])
    results, truncated = _rows(result['rows'], args['return_rows'], args['fields'])
    stopped = bool(result.get('stopped')) or _stopped(args)
    failed = bool(result.get('paused') or result.get('error'))
    complete = not stopped and not failed and _search_complete(result['notes'])
    status = 'cancelled' if stopped and not complete else 'ok' if complete else 'partial'
    coverage = dict(
        complete=complete,
        reason=('Complete candidate scan; faction states come from system records, not live signal spawns.'
                if complete else 'Stopped.' if status == 'cancelled' else
                'Network interruption or page limit; verified rows retained; rerun for a fresh scan.'),
        scanned=result['scanned'], server_count=result['total'],
        fetched_at=result.get('fetched_at'), returned=len(results), truncated=truncated)
    payload = dict(criteria=_clean(vars(criteria)), results=results)
    extras = dict(notes=result['notes'], errors=[result['error']] if result.get('error') else [])
    return payload, status, coverage, extras


def _purchase_condition(entry):
    if not isinstance(entry, dict) or not str(entry.get('name', '')).strip():
        raise ValueError('Each purchase needs a non-empty module/weapon name')
    condition = dict(type='field', field='modules', op='=', text=str(entry['name']).strip(),
                     discounted=bool(entry.get('discounted', True)))
    if entry.get('class') is not None:
        condition['class'] = [str(entry['class'])]
    if entry.get('rating') is not None:
        condition['rating'] = [str(entry['rating']).strip()]
    if entry.get('weapon_mode'):
        condition['weapon_mode'] = str(entry['weapon_mode'])
    if entry.get('fresh_days') is not None:
        condition['fresh_days'] = _limit(entry, 'fresh_days', 1, 1, 3650)
    return condition


def _engineer_shopping(args):
    purchases = args.get('purchases')
    if not isinstance(purchases, list) or not purchases:
        raise ValueError('purchases must be a non-empty list of {name, class?, rating?, weapon_mode?, discounted?, fresh_days?}')
    module_conditions = [_purchase_condition(entry) for entry in purchases]
    max_extra_jumps = args.get('max_extra_jumps', 1)
    if isinstance(max_extra_jumps, bool) or not isinstance(max_extra_jumps, int) or max_extra_jumps < 0:
        raise ValueError('max_extra_jumps must be a non-negative integer')
    for key in ('ignore_carriers', 'ignore_planetary'):
        if key in args and not isinstance(args[key], bool):
            raise ValueError(f'{key} must be a boolean')
    if 'arrival_ls' in args and args['arrival_ls'] is not None:
        _number(args['arrival_ls'], 'arrival_ls')
    criteria = engineer_shopping.build_criteria(
        args.get('origin', ''), args.get('destination', ''), args.get('jump_range'),
        args.get('arrival_ls'), module_conditions,
        ignore_carriers=bool(args.get('ignore_carriers', True)),
        max_extra_jumps=max_extra_jumps,
        ignore_planetary=bool(args.get('ignore_planetary', False)),
        landing_pad=args.get('landing_pad', '') or '',
        pledged_power=args.get('pledged_power', '') or '')
    want = _limit(args, 'want', 100, 1, 10000)
    max_pages = _limit(args, 'max_pages', 25, 1, 1000)
    result = engineer_shopping.search(criteria, want=want, max_pages=max_pages, stop=args['stop'])
    results, truncated = _rows(result['rows'], args['return_rows'], args['fields'])
    stopped = bool(result.get('stopped')) or _stopped(args)
    complete = not stopped and _search_complete(result['notes'])
    status = 'cancelled' if stopped and not complete else 'ok' if complete else 'partial'
    coverage = dict(
        complete=complete,
        reason=('Complete candidate scan; jump estimates are route-metric estimates, not verified routes.'
                if complete else 'Stopped.' if status == 'cancelled' else
                'Page limit reached before exhausting candidates.'),
        scanned=result['scanned'], server_count=result['total'],
        returned=len(results), truncated=truncated)
    payload = dict(criteria=_clean(vars(criteria)), results=results)
    extras = dict(notes=result['notes'])
    return payload, status, coverage, extras


def _full_outfitting(args):
    options = {}
    for key in OUTFITTING_OPTIONS:
        if key in args and args[key] is not None:
            if not isinstance(args[key], bool):
                raise ValueError(f'{key} must be a boolean')
            options[key] = args[key]
    criteria = full_outfitting.build_criteria(
        args.get('reference', ''), args.get('radius'), **options)
    want = _limit(args, 'want', 50, 1, 10000)
    max_pages = _limit(args, 'max_pages', 25, 1, 1000)
    result = outfitting_snapshot.search(criteria, want=want, max_pages=max_pages,
                                        stop=args['stop'], refresh=bool(args.get('refresh', False)))
    results, truncated = _rows(result['rows'], args['return_rows'], args['fields'])
    stopped = bool(result.get('stopped')) or _stopped(args)
    complete = bool(result.get('complete')) and not stopped
    status = 'ok' if complete else 'cancelled' if stopped else 'partial'
    coverage = dict(
        complete=complete,
        reason=('Local snapshot filter finished; this proves only the saved station list was filtered, not live stock.'
                if complete else 'Stopped.' if status == 'cancelled' else
                'Snapshot filter incomplete; absence of stations is unconfirmed.'),
        scanned=result.get('scanned', 0), total_snapshot_stations=result.get('total', 0),
        snapshot_created_at=result.get('snapshot_created_at'),
        catalog_revision=result.get('catalog_revision'),
        rejected=result.get('rejected', 0), uncertain=result.get('uncertain', 0),
        incomplete=result.get('incomplete', 0), condition_failures=result.get('condition_failures', 0),
        returned=len(results), truncated=truncated)
    payload = dict(criteria=_clean(result.get('criteria', vars(criteria))), results=results)
    extras = dict(notes=result.get('notes', []), errors=result.get('errors', []),
                  diagnostics=result.get('diagnostics'),
                  warnings=['Snapshot may be stale; rebuild explicitly with refresh=true (network).']
                  if not args.get('refresh') else [])
    return payload, status, coverage, extras


def _waypoint_route(args):
    groups = args.get('groups')
    if not isinstance(groups, list) or not groups:
        raise ValueError('groups must be a non-empty list of {kind, conditions, name?}')
    criteria = waypoint_route.Criteria(
        origin=args.get('origin', ''), destination=args.get('destination', ''),
        max_extra_ly=args.get('max_extra_ly', 100),
        candidates_per_group=args.get('candidates_per_group', 12),
        max_pages=args.get('max_pages', 5)).validate()
    result = waypoint_route.search(criteria, deepcopy(groups), stop=args['stop'])
    count = len(result.get('groups', groups))
    pools = []
    pools_complete = True
    for index in range(count):
        prefix = f'{index + 1}: '
        notes = [note[len(prefix):] for note in result.get('notes', []) if note.startswith(prefix)]
        complete = _search_complete(notes)
        pools_complete = pools_complete and complete
        pools.append(dict(group=index + 1, complete=complete, notes=notes))
    stopped = _stopped(args)
    route_found = result.get('route') is not None
    if pools_complete:
        status = 'ok'
        reason = ('No feasible route within the detour bound over complete candidate pools.'
                  if not route_found else
                  'Route optimized over fully fetched candidate pools; best within the pools, not a galaxy-wide optimum.')
    else:
        status = 'cancelled' if stopped else 'partial'
        reason = ('Stopped before all candidate pools were fetched; the route may be suboptimal.'
                  if stopped else
                  'Some candidate pools hit the page limit; the route may be suboptimal.')
    payload_keys = ('route', 'stops', 'total_ly', 'direct_ly', 'extra_ly', 'final_leg_ly',
                    'missing', 'endpoint_requirements', 'origin', 'destination')
    payload = {key: _clean(result[key]) for key in payload_keys if key in result}
    coverage = dict(complete=pools_complete, reason=reason, route_found=route_found, pools=pools)
    extras = dict(notes=result.get('notes', []))
    return payload, status, coverage, extras


def _colonisation(args):
    kwargs = _criteria_kwargs(colonisation_tool.Criteria, args)
    criteria = colonisation_tool.Criteria(**kwargs).validate()
    info, rows = colonisation_tool.search(criteria, stop=args['stop'])
    results, truncated = _rows(rows, args['return_rows'], args['fields'])
    stopped = _stopped(args)
    complete = bool(info.get('complete')) and not stopped
    status = 'ok' if complete else 'cancelled' if stopped else 'partial'
    coverage = dict(
        complete=complete,
        reason=info.get('reason') or ('Complete candidate scan; unknown body records are counted, not assumed eligible.'
                                      if complete else 'Stopped or incomplete scan; absence of candidates is unconfirmed.'),
        scanned=info.get('scanned', 0), server_count=info.get('total', 0),
        unknown=info.get('unknown', 0), value_field=info.get('value_field', criteria.value_field),
        returned=len(results), truncated=truncated)
    payload = dict(criteria=_clean(vars(criteria)), results=results)
    extras = {}
    return payload, status, coverage, extras


def _rare_goods(args):
    reference = str(args.get('reference', '')).strip()
    if not reference:
        raise ValueError('reference must be a rare-commodity source system')
    canonical = next((name for name in rare_goods.SOURCE_SYSTEMS
                      if name.casefold() == reference.casefold()), None)
    if canonical is None and not args.get('allow_unknown_source'):
        raise ValueError(f'{reference!r} is not a known rare-commodity source system; '
                         'see options group rare_goods_sources, or pass allow_unknown_source=true')
    power = args.get('power') or powerplay_tool.POWERS[0]
    power = powerplay_tool.normalize_power(power)
    info, groups = powerplay_tool.search_powerplay(
        reference=canonical or reference, power=power,
        all_powers=bool(args.get('all_powers', False)),
        min_ly=_number(args.get('min_ly', 200), 'min_ly'),
        max_ly=_number(args.get('max_ly', 220), 'max_ly'),
        max_pages=_limit(args, 'max_pages', 20, 1, 1000), stop=args['stop'])
    rows = []
    for group_power, group in (groups or {}).items():
        for row in group.get('rows', []):
            rows.append(dict(row, powerplay_power=group_power, group_status=group.get('status')))
    results, truncated = _rows(rows, args['return_rows'], args['fields'])
    stopped = _stopped(args)
    complete = bool(info.get('complete')) and not stopped
    status = 'ok' if complete else 'cancelled' if stopped else 'partial'
    coverage = dict(
        complete=complete,
        reason=('Per-power candidate pages exhausted; fallback groups may still be incomplete if not all_powers.'
                if complete else 'Stopped or page limit; per-power statuses flag incompleteness.'),
        scanned=info.get('scanned', 0), unverifiable=info.get('unverifiable'),
        power=power, requested_reference=canonical or reference,
        returned=len(results), truncated=truncated)
    payload = dict(results=results)
    extras = dict(notes=info.get('notes', []), corrections=info.get('corrections', []))
    return payload, status, coverage, extras


def _midpoint(args):
    info, rows = eng.midpoint_search(
        args.get('system_a', ''), args.get('system_b', ''),
        want=_limit(args, 'want', 20, 1, 200),
        populated_only=bool(args.get('populated_only', False)),
        exclude_permit=bool(args.get('exclude_permit', False)),
        max_pages=_limit(args, 'max_pages', 10, 1, 100))
    results, truncated = _rows(rows, args['return_rows'], args['fields'])
    stopped = _stopped(args)
    complete = bool(info.get('complete')) and not stopped
    status = 'ok' if complete else 'cancelled' if stopped else 'partial'
    coverage = dict(
        complete=complete,
        reason=('Candidate pages exhausted near the midpoint.' if complete else
                'Stopped.' if status == 'cancelled' else
                'Page limit reached; systems slightly nearer the midpoint may be missing.'),
        a=info.get('a'), b=info.get('b'), ab_ly=info.get('ab'),
        midpoint=list(info['mid']) if info.get('mid') is not None else None,
        returned=len(results), truncated=truncated)
    payload = dict(results=results)
    extras = {}
    return payload, status, coverage, extras


def _resolve_system(args):
    name = str(args.get('name', '')).strip()
    if not name:
        raise ValueError('name must be a non-empty system name')
    canonical, coords, fixed = eng.resolve_ref(name)
    payload = dict(system=canonical, coords=dict(zip(('x', 'y', 'z'), coords)),
                   corrected=bool(fixed), source='Spansh')
    return payload, 'ok', dict(complete=True), dict(
        warnings=[f'Corrected {name!r} to {canonical!r}.'] if fixed else [])


def _read_current_system(args):
    directory = args.get('directory') or journal_location.default_directory()
    location = journal_location.read_current_system(directory)
    payload = dict(system=location.system, timestamp=location.timestamp,
                   filename=location.filename, source='Elite Dangerous Journal',
                   note='Last confirmed Journal position event, not live telemetry.')
    return payload, 'ok', dict(complete=True), {}


def _capabilities(_args):
    payload = dict(
        interface_version=INTERFACE_VERSION,
        application_version=app_metadata.PROJECT_VERSION,
        operations=[dict(name=name, description=OPERATIONS[name]['description'],
                         network=bool(OPERATIONS[name].get('network', True)))
                    for name in sorted(OPERATIONS)],
        limits=dict(default_return_rows=DEFAULT_RETURN_ROWS, max_return_rows=MAX_RETURN_ROWS,
                    deadline_seconds='optional, 0 < seconds <= 86400',
                    fields='optional, non-empty list of row keys for the projection'),
        notes=['Results are data snapshots with provenance, not live mission-board or stock guarantees.',
               'status=partial means coverage is incomplete, not that nothing exists.',
               'Human-facing note text follows the core and is currently Chinese.'])
    return payload, 'ok', dict(complete=True), {}


def _describe(args):
    name = args.get('operation')
    if name not in OPERATIONS:
        raise ValueError(f'Unknown operation {name!r}; see capabilities')
    spec = OPERATIONS[name]
    payload = dict(operation=name, description=spec['description'],
                   arguments=spec['schema'],
                   network='usually required' if spec.get('network', True) else 'not required')
    return payload, 'ok', dict(complete=True), {}


OPERATIONS = {
    'capabilities': dict(description='Protocol version, application version, operations and limits.',
                         schema={}, run=_capabilities, network=False),
    'describe': dict(description='Input schema and semantics of one operation.',
                     schema=dict(operation=dict(type='string', required=True)),
                     run=_describe, network=False),
    'options': dict(description='Discover condition fields, operators and enum values per tool group.',
                     schema=dict(group=dict(type='string', required=False,
                                            description='Omit to list group names')),
                     run=_options, network=False),
    'resolve_system': dict(description='Resolve one system name to its canonical name and coordinates (Spansh).',
                           schema=dict(name=dict(type='string', required=True)), run=_resolve_system),
    'search_systems': dict(description='Filter star systems by field/distance/system-details conditions.',
                           schema=dict(conditions=dict(type='array of condition objects, non-empty', required=True),
                                       want=dict(type='int 1-10000', required=False),
                                       max_pages=dict(type='int 1-1000', required=False)),
                           run=_search_systems),
    'search_stations': dict(description='Filter stations by field/distance/ring conditions; '
                                       'same-station equipment via modules conditions.',
                            schema=dict(conditions=dict(type='array of condition objects, non-empty', required=True),
                                        want=dict(type='int 1-10000', required=False),
                                        max_pages=dict(type='int 1-1000', required=False)),
                            run=_search_stations),
    'search_pve': dict(description='Pirate-mission RES/CNB candidates from EDTools-derived data '
                                  'with optional BGS/Power filters.',
                       schema=dict(reference=dict(type='string', required=True),
                                   radius=dict(type='number >= 0; 0 means unlimited', required=False),
                                   search_mode=dict(type='missions|res_systems|expanded', required=False),
                                   min_factions=dict(type='int 0-8', required=False),
                                   min_federation=dict(type='int 0-8', required=False),
                                   min_empire=dict(type='int 0-8', required=False),
                                   source_faction=dict(type='string', required=False),
                                   source_controller=dict(type='string', required=False),
                                   target_controller=dict(type='string', required=False),
                                   power=dict(type='string', required=False),
                                   power_scope=dict(type='source|target|both', required=False),
                                   prefer_low=dict(type='bool', required=False),
                                   cnb_fallback=dict(type='bool', required=False),
                                   source_pad=dict(type='S|M|L or omitted', required=False),
                                   source_station_max_ls=dict(type='number >= 0 or omitted', required=False),
                                   target_ring_max_ls=dict(type='number >= 0 or omitted', required=False),
                                   site_type=dict(type='any|confirmed|low|reg|high|haz', required=False)),
                       run=_pve),
    'search_hge': dict(description='HGE candidate systems by controller allegiance/state rules; '
                                  'not a live signal or spawn claim.',
                       schema=dict(reference=dict(type='string', required=True),
                                   radius=dict(type='number > 0', required=True),
                                   material=dict(type='hge_materials key', required=False),
                                   population=dict(type='option label, or a number equal to one option bound',
                                                   required=False),
                                   freshness=dict(type='option label, or a number equal to one option bound (hours)',
                                                  required=False),
                                   want=dict(type='int 1-10000', required=False),
                                   max_pages=dict(type='int 1-10000', required=False),
                                   require_manufactured_trader=dict(type='bool', required=False)),
                       run=_hge),
    'search_engineer_shopping': dict(description='Shopping stations near the origin-engineer route '
                                                'offering all requested purchases.',
                                     schema=dict(origin=dict(type='string', required=True),
                                                 destination=dict(type='engineer_destinations entry or system name',
                                                                  required=True),
                                                 jump_range=dict(type='number > 0 ly', required=True),
                                                 purchases=dict(type='array of {name, class?, rating?, '
                                                                            'weapon_mode?, discounted?, fresh_days?}',
                                                                required=True),
                                                 arrival_ls=dict(type='number >= 0 or omitted', required=False),
                                                 max_extra_jumps=dict(type='non-negative int', required=False),
                                                 ignore_carriers=dict(type='bool, default true', required=False),
                                                 ignore_planetary=dict(type='bool, default false', required=False),
                                                 landing_pad=dict(type='S|M|L or omitted', required=False),
                                                 pledged_power=dict(type='string or omitted for none', required=False),
                                                 want=dict(type='int 1-10000', required=False),
                                                 max_pages=dict(type='int 1-1000', required=False)),
                                     run=_engineer_shopping),
    'search_full_outfitting': dict(description='Filter the local full-outfitting snapshot; '
                                              'refresh=true rebuilds it over the network.',
                                   schema=dict(reference=dict(type='string', required=True),
                                               radius=dict(type='number > 0 ly', required=True),
                                               other_discounts=dict(type='bool', required=False),
                                               neutral_ships=dict(type='bool', required=False),
                                               federal_ships=dict(type='bool', required=False),
                                               imperial_ships=dict(type='bool', required=False),
                                               guardian=dict(type='bool', required=False),
                                               special_equipment=dict(type='bool', required=False),
                                               require_discount=dict(type='bool', required=False),
                                               ax_weapons=dict(type='bool', required=False),
                                               universal_limpets=dict(type='bool', required=False),
                                               refresh=dict(type='bool, default false', required=False),
                                               want=dict(type='int 1-10000', required=False),
                                               max_pages=dict(type='int 1-1000', required=False)),
                                   run=_full_outfitting),
    'search_waypoint_route': dict(description='Optimize fewest-stop waypoints between two systems '
                                            'over queried candidate pools.',
                                  schema=dict(origin=dict(type='string', required=True),
                                              destination=dict(type='string', required=True),
                                              groups=dict(type='array of 1-6 {kind: systems|stations, '
                                                                      'conditions: [...], name?}',
                                                          required=True),
                                              max_extra_ly=dict(type='number >= 0 ly, default 100', required=False),
                                              candidates_per_group=dict(type='int 1-30, default 12', required=False),
                                              max_pages=dict(type='int 1-100, default 5', required=False)),
                                  run=_waypoint_route),
    'search_colonisation': dict(description='Zero-population, no-station colonization candidates '
                                          'with body/ring eligibility groups.',
                                schema=dict(reference=dict(type='string, required unless radius is omitted',
                                                           required=False),
                                            radius=dict(type='number > 0 ly or omitted', required=False),
                                            populated_radius=dict(type='number or omitted', required=False),
                                            populated_min_distance=dict(type='number or omitted', required=False),
                                            minimum_value=dict(type='number or omitted', required=False),
                                            value_field=dict(type='colonisation_body_fields value key '
                                                             '(e.g. estimated_mapping_value)', required=False),
                                            body_mode=dict(type='AND|OR', required=False),
                                            ring_mode=dict(type='AND|OR', required=False),
                                            body_groups=dict(type='array of condition lists', required=False),
                                            ring_groups=dict(type='array of condition lists', required=False),
                                            want=dict(type='int >= 1', required=False)),
                                run=_colonisation),
    'search_rare_goods': dict(description='Powerplay-aligned stations within a distance band '
                                        'of a rare-commodity source system.',
                              schema=dict(reference=dict(type='rare_goods_sources entry', required=True),
                                          power=dict(type='powerplay_powers entry', required=False),
                                          all_powers=dict(type='bool, default false', required=False),
                                          min_ly=dict(type='number >= 0, default 200', required=False),
                                          max_ly=dict(type='number > min_ly, default 220', required=False),
                                          max_pages=dict(type='int 1-1000', required=False),
                                          allow_unknown_source=dict(type='bool, default false', required=False)),
                              run=_rare_goods),
    'search_midpoint': dict(description='Systems nearest the midpoint of two systems.',
                            schema=dict(system_a=dict(type='string', required=True),
                                        system_b=dict(type='string', required=True),
                                        want=dict(type='int 1-200', required=False),
                                        populated_only=dict(type='bool', required=False),
                                        exclude_permit=dict(type='bool', required=False),
                                        max_pages=dict(type='int 1-100', required=False)),
                            run=_midpoint),
    'read_current_system': dict(description='Read the last confirmed position from local '
                                          'Elite Dangerous Journal files.',
                                schema=dict(directory=dict(type='string, optional; default the user '
                                                           'Saved Games folder', required=False)),
                                run=_read_current_system, network=False),
}


def _error_response(request_id, operation, code, message, started, retryable=None, error_type=None):
    error = dict(code=code, message=message)
    if retryable is not None:
        error['retryable'] = retryable
    if error_type:
        error['exception_type'] = error_type
    return dict(interface_version=INTERFACE_VERSION,
                application_version=app_metadata.PROJECT_VERSION,
                operation=operation, request_id=request_id, status='error',
                error=error, timings=dict(seconds=round(time.monotonic() - started, 3)))


def _cancelled_response(request_id, operation, started):
    return dict(interface_version=INTERFACE_VERSION,
                application_version=app_metadata.PROJECT_VERSION,
                operation=operation, request_id=request_id, status='cancelled',
                coverage=dict(complete=False,
                              reason='Stopped by the deadline or a stop signal before completing; '
                                     'no verified results are reported.'),
                timings=dict(seconds=round(time.monotonic() - started, 3)))


def run_request(request):
    started = time.monotonic()
    if not isinstance(request, dict):
        return _error_response(None, None, 'invalid_request', 'Request must be a JSON object.', started)
    operation = request.get('operation')
    request_id = request.get('request_id')
    if request.get('interface_version', INTERFACE_VERSION) != INTERFACE_VERSION:
        return _error_response(request_id, operation, 'invalid_request',
                               f"interface_version must be {INTERFACE_VERSION!r}.", started)
    spec = OPERATIONS.get(operation) if isinstance(operation, str) else None
    if spec is None:
        return _error_response(request_id, operation, 'unknown_operation',
                               f'Unknown operation {operation!r}; see capabilities.', started)
    if not isinstance(request.get('arguments', {}), dict):
        return _error_response(request_id, operation, 'invalid_request',
                               'arguments must be a JSON object.', started)
    arguments = dict(request.get('arguments', {}))
    limits = request.get('limits') or {}
    if not isinstance(limits, dict):
        return _error_response(request_id, operation, 'invalid_request',
                               'limits must be a JSON object.', started)
    deadline = None
    try:
        return_rows = _limit(limits, 'return_rows', DEFAULT_RETURN_ROWS, 1, MAX_RETURN_ROWS)
        deadline = _Deadline(limits.get('deadline_seconds'))
        fields = limits.get('fields')
        if fields is not None and (not isinstance(fields, list) or not fields
                                   or any(not isinstance(key, str) or not key for key in fields)):
            raise ValueError('limits.fields must be a non-empty list of non-empty row-key strings')
        arguments.update(stop=deadline.event, return_rows=return_rows, fields=fields)
        payload, status, coverage, extras = spec['run'](arguments)
    except (KeyboardInterrupt, InterruptedError):
        return _cancelled_response(request_id, operation, started)
    except ValueError as exc:
        return _error_response(request_id, operation, 'invalid_request', str(exc), started)
    except Exception as exc:
        retryable = isinstance(exc, (TimeoutError, ConnectionError, OSError, json.JSONDecodeError))
        return _error_response(request_id, operation, 'operation_failed', str(exc), started,
                               retryable=retryable, error_type=type(exc).__name__)
    finally:
        if deadline is not None:
            deadline.cancel()
    response = dict(interface_version=INTERFACE_VERSION,
                    application_version=app_metadata.PROJECT_VERSION,
                    operation=operation, request_id=request_id, status=status,
                    coverage=coverage,
                    timings=dict(seconds=round(time.monotonic() - started, 3)))
    response.update(payload)
    response.update({key: value for key, value in extras.items() if value})
    return _clean(response)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input', help='UTF-8 JSON request file; default stdin')
    parser.add_argument('--pretty', action='store_true', help='Indent the stdout envelope')
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    if args.input:
        with open(args.input, encoding='utf-8-sig') as file:
            text = file.read()
    else:
        text = sys.stdin.read()
    try:
        request = json.loads(text)
    except ValueError as exc:
        response = _error_response(None, None, 'invalid_request',
                                   f'Request is not valid JSON: {exc}', time.monotonic())
    else:
        response = run_request(request)
    try:
        text = json.dumps(response, ensure_ascii=False, allow_nan=False)
    except ValueError:
        text = json.dumps(_clean(response), ensure_ascii=False, allow_nan=False)
    if args.pretty:
        text = json.dumps(json.loads(text), ensure_ascii=False, allow_nan=False, indent=2)
    sys.stdout.write(text + '\n')
    if response.get('status') == 'error':
        return 1 if response['error']['code'] in ('invalid_request', 'unknown_operation') else 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
