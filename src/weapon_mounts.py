"""Offline, presentation-only mounts for exact weapon name and specification.

Source: EDCD/FDevIDs outfitting.csv at
c35612952dd6a547d1a7ac4cffab9c7051e86579, checked 2026-10-31.
Only explicit Fixed/Gimballed/Turreted facts matching bundled pairs are kept.
F/G/T are mounts, not inferred from ratings. Multiple mounts can share a code.
These facts are not station stock; selected mounts require stock-level evidence.
"""

MOUNT_CODES = {
    'AX Missile Rack': '2B:FT 3A:FT',
    'AX Multi-Cannon': '2E:F 2F:T 3C:F 3E:T',
    'Abrasion Blaster': '1D:FT',
    'Advanced Missile Rack': '1B:F 2B:F',
    'Advanced Multi-Cannon': '1F:F 2E:F',
    'Advanced Plasma Accelerator': '3B:F',
    'Beam Laser': '1E:FG 1F:T 2D:FG 2E:T 3C:FG 3D:T 4A:FG',
    'Burst Laser': '1F:F 1G:GT 2E:F 2F:GT 3D:F 3E:GT 4E:FG',
    'Cannon': '1D:F 1E:G 1F:T 2D:FG 2E:T 3C:FG 3D:T 4B:FG',
    'Concord Cannon': '2D:G',
    'Cytoscrambler Burst Laser': '1F:F',
    'Double Screaming Fragment Cannon': '1E:G 3C:G',
    'Enforcer Cannon': '1F:F',
    'Enhanced AX Missile Rack': '2D:F 2E:T 3B:F 3D:T',
    'Enhanced AX Multi-Cannon': '2D:F 2E:GT 3B:F 3C:G 3D:T',
    'Enzyme Missile Rack': '2B:F',
    'Exposing Missiles': '3A:F',
    'Far-Reaching Abrasion Blaster': '1D:F',
    'Force Impact Cannon': '4B:F',
    'Fragment Cannon': '1E:FGT 2A:F 2D:GT 3C:FGT',
    'Guardian Gauss Cannon': '1D:F 2B:F',
    'Guardian Nanite Torpedo Pylon': '2I:F 3I:F',
    'Guardian Plasma Charger': '1D:F 1F:T 2B:F 2E:T 3C:F 3D:T',
    'Guardian Shard Cannon': '1D:F 1F:T 2A:F 2D:T 3C:F 3D:T',
    'High-Yield Enzyme Missile Rack': '2B:F',
    'Imperial Hammer Rail Gun': '2B:F',
    'Lockdown Seeker Missile Rack': '2B:F',
    'Long Range Mining Laser': '1D:F',
    'Mine Launcher': '1I:F 2I:F',
    'Mining Lance': '1D:F',
    'Mining Laser': '1D:FT 2D:FT',
    'Mining Volley Repeater': '3C:F',
    'Missile Rack': '1B:F 2B:F 3A:F',
    'Mk II Plasma Shock Accelerator': '3B:F',
    'Multi-Cannon': '1F:F 1G:GT 2E:F 2F:GT 3C:FG 3E:T 4A:FG',
    'Overloaded Beam Laser': '4A:F',
    'Pacifier Frag-Cannon': '3C:F',
    'Pack-Hound Missile Rack': '2B:F',
    'Plasma Accelerator': '2C:F 3B:F 4A:F',
    'Pulse Disruptor Laser': '2E:F',
    'Pulse Laser': '1F:F 1G:GT 2E:F 2F:GT 3D:F 3E:G 3F:T 4A:FG',
    'Rail Gun': '1D:F 2B:F',
    'Rapid Phase Multi-Cannon': '2E:F',
    'Regenerative Burst Laser': '2F:G',
    'Remote Release Flak Launcher': '2B:FT',
    'Remote Release Flechette Launcher': '2B:FT',
    'Retributor Beam Laser': '1E:F',
    'Rocket Propelled FSD Disruptor': '2B:F',
    'Seeker Missile Rack': '1B:F 2B:F 3A:F',
    'Seismic Charge Launcher': '2B:FT',
    'Shock Cannon': '1D:F 1E:G 1F:T 2D:FG 2E:T 3C:FG 3D:T',
    'Shock Mine Launcher': '1I:F',
    'Sub-Surface Displacement Missile': '1B:FT 2B:FT',
    'Sub-Surface Extraction Missile': '2B:F',
    'Torpedo Pylon': '1I:F 2I:F 3I:F',
}

_MOUNTS = {name.casefold(): dict(part.split(':') for part in codes.split())
           for name, codes in MOUNT_CODES.items()}

MODES = {'F': ('Fixed', '固定'), 'G': ('Gimballed', '万向'), 'T': ('Turreted', '炮塔')}


def specification_choices(names, variants):
    labels = specification_labels(names, variants)
    choices, displays = [], {}
    facts = _MOUNTS.get(names[0].casefold(), {}) if len(names) == 1 else {}
    for code in variants:
        modes = facts.get(code, '')
        if modes:
            for token in modes:
                mode, title = MODES[token]
                value = f'{code}|{mode}'
                choices.append(value)
                displays[value] = f'{code}（{title}）'
        else:
            choices.append(code)
            if code in labels:
                displays[code] = labels[code]
    return choices, displays


def item_mount(item):
    """Only explicit stock mount or stable symbol tokens prove a mount."""
    aliases = {'fixed': 'Fixed', 'gimbal': 'Gimballed', 'gimballed': 'Gimballed',
               'turret': 'Turreted', 'turreted': 'Turreted'}
    explicit = str(item.get('weapon_mode') or item.get('mount') or '').casefold()
    mode = aliases.get(explicit)
    symbol = str(item.get('ed_symbol') or item.get('symbol') or '').casefold()
    symbolic = {aliases[token] for token in symbol.split('_') if token in aliases}
    if len(symbolic) > 1 or mode and symbolic and mode not in symbolic:
        return None
    return mode or next(iter(symbolic), None)


def specification_labels(names, variants):
    """Decorate a single weapon only; never merge mounts across selected names."""
    from module_slots import groups_for
    if len(names) != 1:
        return {}
    if names[0].casefold() not in _MOUNTS and '武器挂点' not in groups_for(names[0]):
        return {}
    facts = _MOUNTS.get(names[0].casefold(), {})
    labels = {}
    for code in variants:
        modes = facts.get(code, '')
        text = '／'.join(label for token, label in (('F', '固定'), ('G', '万向'), ('T', '炮塔'))
                         if token in modes) or '支架未知'
        labels[code] = f'{code}（{text}）'
    return labels
