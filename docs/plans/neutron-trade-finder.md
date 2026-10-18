# Neutron-assisted long-haul trade finder / 中子星顺路长途贸易查找器

Status / 状态: **future plan, not implemented** (drafted 2026-10-18, data findings verified against live Spansh endpoints on 2026-10-17).
**未来计划，尚未实现**（2026-10-18 起草，数据结论于 2026-10-17 对 Spansh 线上接口验证）。

This document records an agreed direction and the endpoint research behind it. It is not a shipped feature and is not linked from the README.
本文记录已讨论确定的方向及其接口调研结论，不是已发布功能，也不从 README 链接进入。

## English

### Goal

A **single-segment buy → sell candidate finder** for long-haul commodity trading, with an optional experimental neutron-alignment ranking. Same user flow as the rare-goods target finder: choose a source, get a ranked candidate list, and optionally re-rank by "on the way" neutron geometry.

Positioning is deliberate: Spansh and Inara already optimise short local loops by profit/hour. This tool targets the gap that neither covers — **carry cargo on a long trip you were making anyway** — so the neutron/jump angle is the differentiator, not loop optimisation. Honest framing: the output is "data says this station pays more", never "guaranteed profit route".

### Verified data availability (live probes, 2026-10-17)

- `/api/stations/search` (POST; the project already uses it) returns each station row **including the full `market` array** — per-commodity `buy_price`, `sell_price`, `supply`, `demand` — plus `x/y/z`, `system_name`, `name`, `market_id`, `market_updated_at`, `distance_to_arrival`, pads, `is_planetary`, `is_dssa_carrier`.
- Server-side freshness filtering works, but only in this shape:
  `"market_updated_at": {"comparison": "<=>", "value": ["<ISO from>", "<ISO to>"]}`.
  A leading `{min: ...}`, a unix-timestamp pair, or `{min/max: ...}` did **not** filter (rows months old came back). The existing engine deliberately keeps timestamp filtering local (`filter_engine.plan_server_filters`: `timestamp` → `local_only`), so for this tool the verified server format is pushed for the scan window and results are still re-checked locally.
- Measured volume: within 100–300 ly of Sol, **248** stations had markets updated in the last ~50 minutes; a 24–48 h window yields a few thousand rows. Each row is roughly 7 KB with its market, so a full scan needs paging (gzip), a progress display and a stop action — the same pattern as the existing paged searches.
- `/api/station/{market_id}` returns a full station record (includes `market`). Fallback for any row where the market array is absent.
- `/api/trade/route` exists (public, job-based: `GET` → `202 {job}` → poll `/api/results/{job}`) but returns **one best route per job** — the site's own front end only reads `result[0]`. It cannot supply a candidate list, and a job queues for about a minute. Accepted parameters: `max_hop_distance`, `max_price_age`, `max_cargo`, `max_hops`, `starting_capital`, `max_system_distance`, plus pad / prohibited / planetary / player-owned / restricted / unique / permit toggles. Keep this endpoint for a possible later "loop route" feature; a `/trade-to-system/:system/:station/:commodity` variant also exists.
- Neutron geometry is fully reusable from `src/rare_neutron.py`: `load_anchors` (neutron stars within 200 ly of the source, arrival <=100 Ls) and `alignment(origin, target, anchor)`, with the existing tiers 30°/10% → 45°/25% → 60°/50% and selection rules documented in `docs/route-planner.md`.

### Agreed v1 scope

- **Inputs:** source system + station (resolved to a market snapshot), distance band (default 100–300 ly), market-age limit (default 48 h), cargo capacity, optional large-pad / ignore-planetary.
- **Scan:** station search with reference coordinates, the distance band, `has_market`, and the freshness window; paged with progress, stop, and an explicit completeness note.
- **Compute locally:** source `supply > 0` × candidate `demand > 0`; profit per ton = candidate sell price − source buy price; buyable amount = min(source supply, candidate demand, cargo).
- **Results:** sortable table — commodity | sell station (system + station) | profit/ton | buyable amount | total profit | segment `ly` | sell-station market age — plus **optional neutron columns, off by default**: outbound/return reference neutron stars, angle, detour `ly`, tier label. Copy station name, CSV with provenance, and session save.
- **Project integration:** bilingual UI, `i18n` catalogue entries, smoke/session tests, README and feature docs — the built-in tool count goes 7 → 8.
- **Boundaries to state in the UI:** EDDN snapshots; supply/demand change; purchase quantities are not verified; neutron columns are experimental with no guaranteed savings; the source snapshot's own age is shown.

### Out of scope for v1

Planner hand-off ("generate neutron route" from a result row), multi-hop chains, favourites, and the job-based `/api/trade/route` loop planner. These stay as possible follow-ups.

### Open items before/while coding

- Names for the new module/window (Chinese + English) and its position in the Extra-tools menu.
- Pagination size, scan row caps, and the wording that discloses an incomplete scan.
- Whether to reuse the existing station lookup for the source row or read `/api/station/{market_id}` directly.
- Confirm `market` is present on every `has_market` row (fallback path above), measure a full 48 h scan, and settle carrier/planetary defaults.
- Tests: search/parse/filter, profit computation, neutron evaluation, GUI behaviour, i18n coverage, smoke (tool count 7 → 8) and session round-trip.

## 中文

### 目标

面向长途商品贸易的**单段"买点 → 卖点"候选查找器**，附带可选的实验性中子星顺路排序。交互与稀有商品目标查找器一致：选来源，得到排序后的候选列表，再可选地按"顺路"中子几何重排。

定位是有意为之：Spansh 与 Inara 已按每小时利润优化本地短线循环；本工具瞄准两者都不覆盖的缝隙 —— **反正要飞远，顺路带什么货** —— 因此中子／跳跃视角才是差异点，而不是循环优化。措辞必须诚实：输出是"数据显示这里卖得贵"，绝不是"稳赚路线"。

### 已验证的数据可用性（2026-10-17 线上探测）

- `/api/stations/search`（POST，项目已在用）返回的每个站点行**自带完整 `market` 数组**——逐商品 `buy_price`、`sell_price`、`supply`、`demand`——另含 `x/y/z`、`system_name`、`name`、`market_id`、`market_updated_at`、`distance_to_arrival`、停机坪、`is_planetary`、`is_dssa_carrier`。
- 服务端时效过滤可用，但只认这种形状：
  `"market_updated_at": {"comparison": "<=>", "value": ["<ISO 起>", "<ISO 止>"]}`。
  用 `{min: ...}`、unix 时间戳对、或 `{min/max: ...}` 都**不会**过滤（会返回几个月前的行）。现有引擎故意把时间戳过滤留在本地（`filter_engine.plan_server_filters` 中 `timestamp` → `local_only`），因此本工具在扫描窗口推送已验证的服务端格式，并仍然在本地复核。
- 实测数据量：Sol 周边 100–300 ly 内，市场在最近约 50 分钟内更新过的站有 **248** 个；放宽到 24–48 小时约有数千行。每行含市场约 7 KB，因此整轮扫描需要分页（gzip）、进度显示和停止操作——与现有分页检索同一套模式。
- `/api/station/{market_id}` 返回完整站点记录（含 `market`），可作为缺少市场数组行的兜底。
- `/api/trade/route` 存在（公开、job 型：`GET` → `202 {job}` → 轮询 `/api/results/{job}`），但每次只返回**一条最优路线**——站点自身前端也只取 `result[0]`，无法提供候选列表，且任务要排队约一分钟。可用参数：`max_hop_distance`、`max_price_age`、`max_cargo`、`max_hops`、`starting_capital`、`max_system_distance`，以及停机坪／违禁品／地面／玩家所有／受限／唯一／许可等开关。保留该接口给将来可能的"循环路线"功能；另有 `/trade-to-system/:system/:station/:commodity` 变体。
- 中子几何可从 `src/rare_neutron.py` 直接复用：`load_anchors`（来源 200 ly 内、到达≤100 Ls 的中子星）与 `alignment(origin, target, anchor)`，沿用既有档位 30°／10% → 45°／25% → 60°／50% 及 `docs/route-planner.md` 记录的选取规则。

### v1 已确认范围

- **输入：** 起点星系＋站名（解析市场快照）、距离带（默认 100–300 ly）、市场时效上限（默认 48 小时）、货舱容量、可选大型停机坪／排除地面站。
- **扫描：** 以起点坐标为参照的站点检索，叠加距离带、`has_market` 与时效窗口；分页并显示进度、可停止，明确标注完成度。
- **本地计算：** 源站 `supply > 0` × 候选站 `demand > 0`；每吨利润 = 候选卖价 − 源站买价；可购量 = min(源供给, 候选需求, 货舱)。
- **结果：** 可排序表格——商品｜卖站（星系＋站）｜每吨利润｜可购量｜总利润｜段距离 `ly`｜卖站市场年龄——另加**默认关闭的可选中子列**：去程／返程参考中子星、夹角、绕行 `ly`、档位标签。支持复制站名、带来源信息的 CSV、会话保存。
- **项目集成：** 中英双语界面、`i18n` 词条、冒烟／会话测试、README 与功能文档——内置工具数 7 → 8。
- **界面需写明的边界：** 数据为 EDDN 快照；供需会变；不核查购买数量；中子列为实验性、不保证省跳；起点快照自身年龄也要显示。

### v1 不做

结果行到规划器的一键衔接（"生成中子路线"）、多跳链、收藏，以及 job 型 `/api/trade/route` 循环规划。均留作后续可能。

### 实现前／实现中的待定项

- 新模块／窗口的中英文命名，以及在"额外工具"菜单中的位置。
- 分页大小、扫描行数上限，以及披露"扫描未完成"的措辞。
- 起点行是复用现有站点查询，还是直接读 `/api/station/{market_id}`。
- 确认每个 `has_market` 行都带 `market`（用上面的兜底路径）、实测一轮 48 小时扫描耗时、确定航母／地面站默认值。
- 测试：检索／解析／过滤、利润计算、中子评估、界面行为、i18n 覆盖、冒烟（工具数 7 → 8）与会话往返。
