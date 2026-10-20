"""Conservative public station/Power discount rules; no price downloads.

Sources checked 2026-10-17:
https://elite-dangerous.fandom.com/wiki/Discounts
https://elite-dangerous.fandom.com/wiki/Li_Yong-Rui
Reported public-discount bugs (not evidence against personal rank bonuses):
https://forums.frontier.co.uk/threads/powerplay-related-discount-v2-0-even-if-not-pledge.630099/
Public rules exclude personal bonuses and expired CG discounts. Engineer shopping
may explicitly supply a pledged Power to assume its maximum-rank weapon bonus.
"""
import re


def key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


IMPERIAL_SHIPS = {key(n) for n in ('Imperial Eagle', 'Imperial Courier', 'Imperial Clipper', 'Imperial Cutter')}
LAKON_SHIPS = {key(n) for n in ('Asp Explorer', 'Asp Scout', 'Diamondback Explorer', 'Diamondback Scout',
    'Type-6 Transporter', 'Type-7 Transporter', 'Type-8 Transporter', 'Type-9 Heavy', 'Type-10 Defender',
    'Type-11 Prospector', 'Keelback', 'Alliance Chieftain', 'Alliance Challenger', 'Alliance Crusader')}
ATTILIUS_SHIPS = {key(n) for n in ('Sidewinder', 'Sidewinder MkI', 'Eagle', 'Eagle MkII', 'Viper MkIII',
    'Cobra MkIII', 'Diamondback Scout', 'Diamondback Explorer', 'Vulture', 'Fer-de-Lance')}
ATTILIUS_MODULES = {key(n) for n in ('Pulse Laser', 'Burst Laser', 'Beam Laser', 'Cannon', 'Multi-Cannon',
    'Rail Gun', 'Railgun', 'Chaff Launcher', 'Heat Sink Launcher', 'Heatsink Launcher')}
CONTROLLED_STATES = {'exploited', 'fortified', 'stronghold'}
# Shared by the public-rule evaluator and full-outfitting candidate queries.
ALL_MODULE_PUBLIC_STATIONS = (('Shinrarta Dezhra', 'Jameson Memorial', 10),)
MAX_RANK_WEAPON_DISCOUNTS = {key(name): percent for name, percent in (
    ('A. Lavigny-Duval', 30), ('Arissa Lavigny-Duval', 30),
    ('Denton Patreus', 40), ('Jerome Archer', 30), ('Yuri Grom', 30))}


def combat_weapon(item):
    return (item.get('category') == 'hardpoint' and bool(item.get('weapon_mode'))
            and key(item.get('name', '')) not in {key(name) for name in (
                'Mining Laser', 'Abrasion Blaster', 'Seismic Charge Launcher',
                'Sub-Surface Displacement Missile', 'Sub-Surface Displacement Missile Launcher',
                'Sub-Surface Extraction Missile')})


def discount_info(row, item, field, personal_power=''):
    """Return the strongest known applicable rule, never sum overlapping rules.

    No rule match means unknown, not proof of full price. Missing item details
    cannot qualify for product-specific rules. Fleet carriers are not retailers.
    """
    unknown = dict(discounted=None, percent=None, source='')
    if 'carrier' in str(row.get('type', '')).casefold() or not isinstance(item, dict):
        return unknown
    name = key(item.get('name', ''))
    if not name:
        return unknown
    system, station = key(row.get('system_name', '')), key(row.get('name', ''))
    if public_surcharge(row) and field in ('ships', 'modules'):
        return dict(discounted=False, percent=None, surcharge=20, source='i Sola Prospect')
    power = key(row.get('system_controlling_power', ''))
    state = key(row.get('system_power_state', ''))
    rules = []

    def add(percent, source):
        rules.append(dict(discounted=True, percent=percent, source=source))

    for system_name, station_name, percent in ALL_MODULE_PUBLIC_STATIONS:
        if (system, station) == (key(system_name), key(station_name)):
            add(percent, station_name)
    if power == key('Li Yong-Rui') and state in ('fortified', 'stronghold'):
        add(15, 'Li Yong-Rui')
    if field == 'ships':
        if power == key('Denton Patreus') and state in CONTROLLED_STATES and name in IMPERIAL_SHIPS:
            add(10, 'Denton Patreus')
        if system == key('Alioth') and name in LAKON_SHIPS:
            add(5, 'Alioth / Lakon Spaceways')
        if (system, station) == (key('Alioth'), key('Irkutsk')) and name in {key('Asp Explorer'), key('Orca')}:
            add(20, 'Irkutsk')
        if (system, station) == (key('Wolf 406'), key('Hamilton Gateway')) and name == key('Diamondback Explorer'):
            add(20, 'Hamilton Gateway')
        if (system, station) == (key('Summerland'), key("Henry O'Hare's Hangar")) and name in IMPERIAL_SHIPS:
            add(10, "Henry O'Hare's Hangar")
        if (system, station) == (key('Sol'), key('Daedalus')):
            if name in {key('Federal Dropship'), key('Vulture')}:
                add(10, 'Daedalus')
            if name in {key('Eagle'), key('Eagle MkII')}:
                add(20, 'Daedalus')
        if (system, station) == (key('Beta Hydri'), key('Edmondson High')) and name in {key('Eagle'), key('Eagle MkII')}:
            add(10, 'Edmondson High')
        if (system, station) == (key('CD-43 11917'), key('Attilius Orbital')) and name in ATTILIUS_SHIPS:
            add(20, 'Attilius Orbital')
    elif field == 'modules':
        pledged = key(personal_power)
        if power == key('Arissa Lavigny-Duval'):
            power = key('A. Lavigny-Duval')
        if pledged == key('Arissa Lavigny-Duval'):
            pledged = key('A. Lavigny-Duval')
        # Explicit shopping assumption only, not a public benefit or verified rank.
        if (pledged in MAX_RANK_WEAPON_DISCOUNTS and power == pledged
                and state in CONTROLLED_STATES and combat_weapon(item)):
            add(MAX_RANK_WEAPON_DISCOUNTS[pledged], f'{personal_power} (assumed max-rank personal bonus)')
        # Guardian HRP/SRP broker discounts are reported bugged and excluded.
        if power == key('Edmund Mahon') and state in ('fortified', 'stronghold') and name in {key('Cargo Rack'), key('Hull Reinforcement Package')}:
            add(20, 'Edmund Mahon')
        # Archer's public discount is treated as inactive due to a reported game
        # bug (Frontier issue #70307: displayed discount not applied).
        # Independent station discounts still apply in his territory.
        if (system, station) == (key('CD-43 11917'), key('Attilius Orbital')) and name in ATTILIUS_MODULES:
            try:
                size = int(item.get('class'))
            except (ValueError, TypeError):
                size = None
            mode = str(item.get('weapon_mode') or '').casefold()
            if size is not None and size < 3 and (name in {key('Chaff Launcher'), key('Heat Sink Launcher'),
                    key('Heatsink Launcher')} or mode in ('fixed', 'gimbal', 'gimballed')):
                add(30, 'Attilius Orbital')
    return max(rules, key=lambda rule: rule['percent']) if rules else unknown


def public_surcharge(row):
    """Known station-wide markup, not a negative discount or a Power bonus."""
    return 20 if (key(row.get('system_name')), key(row.get('name'))) == (
        key('Brestla'), key('i Sola Prospect')) else None
