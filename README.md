# Elite_dangerous_Filter

English · [简体中文](README_zh-CN.md) · [Releases](https://github.com/kxdxzr/Elite_dangerous_Filter/releases)

An Elite Dangerous desktop system/station filter using [Spansh](https://spansh.co.uk/) and other public data. Includes instant Chinese/English switching and System/Light/Dark appearance.

**Built for combining complex conditions**: multiple reference distances, actual module specifications, complete single-station shopping lists, discounts, planets and rings. A complement to simple Inara lookups, not a replacement.

## Download and quick start

[**Download Windows x64 EXE v0.1.4**](https://github.com/kxdxzr/Elite_dangerous_Filter/releases/download/v0.1.4/EliteDangerousFilter.exe) · [Release notes](docs/releases/v0.1.4.md) · [All releases and source packages](https://github.com/kxdxzr/Elite_dangerous_Filter/releases)

1. Download `EliteDangerousFilter.exe`. No Python installation or API key required.
2. Launch it: search systems/stations in the main window, or open a tool under **Extra tools**.
3. Add conditions and search. Click result headers to sort; copy names, export CSV, save conditions and restore sessions.

Online searches and updates require internet. Saved full-outfitting stock can be filtered locally; missing reference-system coordinates still require a lookup.

**Back up `%LOCALAPPDATA%\EliteDangerousFilter` before upgrading.** Beta and stable share this directory; keep the old EXE and backup for rollback.

The EXE is **not code-signed**; Windows may show Unknown publisher or SmartScreen warnings. Confirm the download came from this project's release page, then compare its hash with that release's `SHA256SUMS.txt`. Hash checking is not publisher-signature verification or a safety guarantee.

```powershell
certutil -hashfile EliteDangerousFilter.exe SHA256
```

> Source and published assets can differ: current source and the local rebuild now embed Windows file/product version resources. The original GitHub v0.1.4 assets have not been replaced.

## Tools

| Tool | Purpose and key rules |
| --- | --- |
| Main filter | Combine system/station conditions: AND between rows, OR within a multi-select row; multiple reference points, distance intersections/outside ranges, same-item specifications, freshness, station/faction counts and planet/ring groups |
| Find fully outfitted stations | Check actual same-station ordinary/Power variants against the known catalogue; optional discounts, AX, Universal controllers, Merc, ships/armour and Guardian broker; excludes carriers and Stronghold Carriers |
| Engineer trip shopping | Find one station stocking every specified item on the way to one of 25 ship engineers; independent specifications, discounts and freshness, plus pad, arrival distance and estimated extra jumps |
| Rare goods target finder | 142 source entries across 138 systems; associated-Power filters and system-level grouping, with optional experimental neutron-alignment filtering |
| Pirate massacre finder (testing) | EDTools mission pairs/sites with Spansh factions, controlling Power, source stations and target rings; minimum mission factions 0 expands RES-system discovery |
| Carrier parking finder | Up to 50 ly, filtering recorded carrier counts by an optional maximum; counts are not live vacancies |
| System midpoint | Find systems near the geometric midpoint of two systems, with distances to the midpoint and both endpoints |
| Colonisation candidate finder | Zero-population, explicitly permit-free, station-free candidates; regional, nearest-populated, value, planet and independent ring conditions; not a claimability guarantee |

Module suggestions retain confirmed class/rating pairs instead of inventing combinations. Main-window OR conditions differ from shopping lists, where **every item must match**. Unknown data never counts as confirmed evidence.

### Find fully outfitted stations

- **The first scan is slow: minutes to more than ten minutes are possible.** Initial/manual discovery uses the widest shortlist within **20,000 ly of Sol**, primarily useful around the Bubble.
- Subsequent conditions reuse local stock. Changing reference only retrieves missing coordinates and recalculates distances. Increasing radius does not discover stations outside the shortlist; results far from the Bubble may be unsuitable or empty.
- Discounts, AX, 7A/7C Universal multi-limpet controllers and Merc are off by default. Merc identity remains ambiguous; strict searches may return no hits rather than accept guesses.
- Successful refreshes atomically replace the same snapshot; failures retain old data. Stock is not live; the UI displays cache age.
- Catalogue and stock are separate: manual GitHub catalogue updates/rollback are supported, but **no catalogue release has been published yet**. Refresh stock manually to apply a changed catalogue.
- Completeness is relative to the current catalogue and selected options. Explicit hangar/vehicle-bay exclusions are recorded in the [tool guide](docs/full-outfitting.md) and [catalogue roadmap](docs/catalog-next-version.md).

See [full usage and validation](docs/full-outfitting.md) and [catalogue updates/rollback](docs/catalog-updates.md) (Chinese).

### Important distinctions

- **Discounts:** general filters use documented public rules, not associated-Power guesses. Engineer shopping separately labels a maximum-rank personal weapon-discount assumption when a Power is selected; actual rank is not read. Select None for public-only discounts. No stacking. See [discount rules](docs/station-discounts.md) and [engineer shopping](docs/engineer-shopping.md).
- **Distances:** pirate mission-pair radius applies to the source; additional RES-system rows use the target. Radius `0` means unlimited. Station/ring maximum Ls is unlimited only when blank; `0` is an actual 0 Ls bound. See [search logic](docs/README_search_logic.md).
- **Estimates are not routes:** engineer extra jumps are estimates; rare-goods neutron alignment checks geometry, not fuel, landing systems or actual jump savings.
- **Colonisation limitation:** the current station-free check still includes ordinary carriers, excluding carrier-only systems. Construction-slot counts are unsupported. Nearest-populated defaults to population >1; both distance bounds apply to the same nearest qualifying system.
- **Neutron planner moved:** use [Elite_dangerous_Neutron_Planner](https://github.com/kxdxzr/Elite_dangerous_Neutron_Planner) for full routing. It is no longer bundled here. Old `route_ship_favorites.json` files can be imported manually there; rare-goods geometric filtering remains here.

## Data, sessions and exports

- **Data is neither guaranteed live nor galaxy-complete.** Verify stock, permits, discounts, missions, vacancies and colonisation eligibility in game. Faction counts only estimate potential issuers; rings do not establish a specific RES type.
- Page/server limits, missing data, request failures or cancellation can leave searches incomplete. No results does not prove absence in game. Percentages refer only to the labelled stage.
- Rare goods uses associated Power. Mapping Spansh `Unoccupied` to Inara Unoccupied/Expansion/Contested is unverified; the latter two cannot be filtered separately.
- Changes save every 1.5 seconds and on close, including language, appearance, condition drafts and seven tools' settings. Writes are atomic; failed close-time saves display an error and keep the window open.
- EXE data: `%LOCALAPPDATA%\EliteDangerousFilter\`. Source runs use project `data/` and `cache/`. `ELITE_FILTER_DATA_DIR` overrides both for isolation. `scripts/migrate_data.py` migrates legacy files without overwriting existing destinations.
- CSV begins with five `# ` provenance rows: author, project name, running version, timezone-aware export time and project URL. Some exports, including full outfitting, add search conditions, followed by a blank row, result header and data. **Do not hard-code skipping six lines: locate the separator/result header after metadata.**
- CSV reflects the completed search, not edited-but-unsubmitted drafts. Main-window exports use condition-driven columns instead of full raw JSON. Provenance identifies the software, not ownership of third-party game data.

## Screenshots

Captured on 2026-10-20 from v0.1.4 in Light appearance, covering the main window and seven tools. All show **offline illustrative fixtures**, labelled by yellow banners—not actual stock, missions, claimable systems or verified routes. Click images for full resolution.

### Main window

![Main GUI in English](docs/images/main-gui-en.png)

<details>
<summary>Planet/ring groups and nearest-populated conditions</summary>

![Detailed system conditions in English](docs/images/main-system-details-en.png)

</details>

### Find fully outfitted stations

![Find fully outfitted stations in English](docs/images/full-outfitting-finder-en.png)

### Engineer trip shopping

![Engineer trip shopping in English](docs/images/engineer-shopping-en.png)

<details>
<summary>Distances, estimated jumps and detours</summary>

![Engineer shopping distance details in English](docs/images/engineer-shopping-route-details-en.png)

</details>

### Rare goods target finder

![Rare goods target finder in English](docs/images/rare-goods-target-finder-en.png)

### Pirate massacre finder (testing)

![Pirate massacre result overview in English](docs/images/pirate-massacre-finder-summary-en.png)

<details>
<summary>Source station and target ring distances</summary>

![Pirate massacre distance details in English](docs/images/pirate-massacre-finder-en.png)

</details>

### Carrier parking finder

Maximum-carrier filtering and recorded counts, not live vacancies.

![Carrier parking finder in English](docs/images/carrier-parking-finder-en.png)

### System midpoint finder

![System midpoint finder in English](docs/images/system-midpoint-finder-en.png)

### Colonisation candidate finder

![Colonisation candidate finder in English](docs/images/colonisation-finder-en.png)

<details>
<summary>Value and matching-body details</summary>

![Colonisation details in English](docs/images/colonisation-finder-details-en.png)

</details>

## Run from source and build

Requires **Python 3.10+ and tkinter**, with no third-party runtime dependencies. Check Tk with `python -m tkinter`; Debian/Ubuntu may require `python3-tk`.

```sh
git clone https://github.com/kxdxzr/Elite_dangerous_Filter.git
cd Elite_dangerous_Filter
python filter_gui.py
```

Run tests and build the Windows EXE from the project directory:

```sh
python scripts/run_tests.py
python -m compileall -q src tests scripts filter_gui.py spansh_filter.py
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean EliteDangerousFilter.spec
```

Default output: **`dist/EliteDangerousFilter.exe`** inside the project. Application identity and version live in `src/app_metadata.py`; the build derives Windows version resources from the same data used by CSV exports. Version resources are not code signatures.

The actual EXE supports `--smoke-test <report.json>`, `--session-test write <report.json>` and `--session-test read <another-report.json>`. Run session write/read in separate processes with an isolated `ELITE_FILTER_DATA_DIR`; create report directories first to avoid touching personal sessions. Tk tests require a graphical display. CI covers Windows/Ubuntu and Python 3.10/3.13.

Implementation is in `src/`, tests in `tests/`, helpers in `scripts/` and sample conditions in `examples/`. CLI usage: `python spansh_filter.py --help` and the [filter guide](docs/README_筛选器说明.txt) (Chinese). Refresh screenshots with `scripts/capture_screenshots.py` and optional developer dependency Pillow 12; it isolates sessions, blocks network access and records dimensions/hashes in the [manifest](docs/images/screenshots.json).

## Documentation and sources

- [Detailed search logic](docs/README_search_logic.md) · [Full outfitting](docs/full-outfitting.md) · [Engineer shopping](docs/engineer-shopping.md) · [Discount rules](docs/station-discounts.md)
- [Language-pack structure and extension guide](docs/localization.md) (Chinese; currently Chinese/English only)
- [v0.1.4 release notes](docs/releases/v0.1.4.md) · [Release history](https://github.com/kxdxzr/Elite_dangerous_Filter/releases)
- Developing other ED tools: [shareable public data/API reference](docs/ed-public-data-api-reference.md) · [complete API development reference](docs/ed-api-reference.md) (Chinese)
- [Spansh](https://spansh.co.uk/): systems, stations, factions and bodies. [EDSM](https://www.edsm.net/): coordinates and same-market outfitting identity evidence.
- [EDTools / CMDR VicTic](https://edtools.cc/pve.php): mission pairs and explicit RES/CNB records, not a live mission API. [Inara](https://inara.cz/elite/): rare-goods target-template reference.

## License and credits

Copyright (c) 2026 kxdxzr. Project-owned code and documentation are [GPL-3.0-only](LICENSE) from the licence-change notice commit onward. Commercial use is permitted; redistribution must meet corresponding-source, notice and other GPL obligations. No warranty. Previously granted MIT permissions remain valid (including commits `afe84c4` and `2393198`); historical versions are not retroactively relicensed. Third-party code, data and services retain their respective terms.

Developed by **GPT-6.1 Sol** through **vibe coding**, with user-driven iteration. Community project; not affiliated with Frontier Developments.
