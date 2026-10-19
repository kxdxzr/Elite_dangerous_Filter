# Neutron jump planner / 中子星跳跃规划器

**Moved / 已拆分：** the ship-specific planner now lives in
[Elite_dangerous_Neutron_Planner](https://github.com/kxdxzr/Elite_dangerous_Neutron_Planner).
The planning sections below are historical notes for older published filter EXEs;
the rare-goods destination-filter sections still apply to the filter's current source.
按配船的中子规划器已迁出；下文航线部分为旧版历史说明，稀有商品几何筛选部分仍适用当前源码。

## English

Included in the downloadable v0.1.3 Windows EXE.

Neutron supercharging is enabled by default. The backend remains Spansh's exact-plotter `/api/generic/route` for ship-specific fuel and refuelling planning, not the fixed-range neutron router. An ordinary jump may still be part of a neutron-assisted route.

### Builds and local storage

- Import exactly one Coriolis JSON build or EDSY SLEF (an object or a single-element SLEF array), not a website URL. Only named ship builds are persisted; there is no route-favourites library. Corrupt favourites are reported, never silently replaced with an empty library. No personal Journal directory or commander profile is read automatically.
- The selected JSON and route points are submitted to Spansh when planning. Do not include private data you do not wish to send. First parsing downloads FSD facts from a pinned [EDCD/coriolis-data revision](https://github.com/EDCD/coriolis-data/tree/0db9234b5b9ce8c939ea84133d7ce336eea88e27); see its [licence](https://github.com/EDCD/coriolis-data/blob/0db9234b5b9ce8c939ea84133d7ce336eea88e27/LICENSE.md). Its JSON data is copyrighted by Frontier and subject to Frontier's terms; the repository's MIT licence applies to Coriolis code, not the JSON data. This application does not bundle that catalogue; successful downloads cache locally as `route_module_cache.json`.
- SLEF uses final engineered optimal mass and max fuel per jump without rounding. Coriolis applies optimal-mass modifications and supported experimental effects. Unknown FSDs, reservoirs, experimental effects or unsupported max-fuel modifications require SLEF instead of guessed physical parameters. The protocol follows the observed Spansh form request, not a guarantee of future API compatibility.

### Selected ship attributes

Selecting a favourite displays ship type/name and normal/neutron-supercharged full-tank ranges only; ship IDs, multipliers and technical drive parameters are not shown. Drive facts load/parse in the background without submitting the build to Spansh. The catalogue is reused within the window. Selection changes discard stale results, and missing data clears old ranges rather than leaving the previous ship's numbers visible. Cargo changes recalculate locally; ship names remain unchanged when switching UI languages.

The full-tank theoretical range is `optimal_mass / (base_mass + tank_size + cargo) * (min(tank_size, max_fuel_per_jump) / fuel_multiplier) ** (1 / fuel_power) + range_boost`. Here `base_mass` already includes the full auxiliary reservoir. The neutron range multiplies the entire normal range, including Guardian boost, by the drive's supported multiplier (normally 4, or 6 for the supported supercharge-optimised Mk II). This follows the [Guardian booster / supercharging range model](https://forums.frontier.co.uk/threads/the-science-of-the-guardian-fsd-booster-2-0.436365/). The class-3 Guardian boost is 7.75 ly. Display uses two decimals without rounding calculation inputs. This preview excludes injections and reserve-fuel restrictions and does not assert that a neutron charge is currently available or active.

### Multi-leg semantics

- Route points are resolved by exact case-insensitive name. Validate all points before submitting jobs. Adjacent duplicates are rejected; non-adjacent revisits are allowed. Each leg submits `/api/generic/route` and polls `/api/results/{job}` sequentially with backoff. HTTP reads and timeouts are bounded, server calculation budget is 60 seconds per leg and local polling deadline is ten minutes per leg. Unknown states, invalid jobs, malformed jumps or wrong endpoints fail rather than silently skipping a leg. There is no automatic resubmission.
- Each leg uses the original full main-tank capacity, never a smaller tank to simulate remaining fuel. Shared endpoints are merged, retaining previous-leg arrival fuel separately from next-leg assumed departure fuel. Already-supercharged is only an initial flag for leg one; subsequent legs start without that assumption. This is **not a continuous-fuel route**. The tool does not verify refuelling facilities or scoopable stars at waypoints.
- CSV includes leg/departure/waypoint/full-tank markers and incomplete-route status; textual formula cells are escaped. Cancellation or failure preserves only validated complete legs, and partial export requires confirmation. Distances use two decimals and comma grouping without changing raw values. The displayed remaining distance is to the **current leg's destination**, not the final trip destination.
- At shared endpoints, leg/fuel-used/arrival fields describe arrival on the preceding leg, while the explicit departure-leg/full-tank columns and refuel/neutron/injection flags describe departure on the next leg. Next-leg departure actions are not discarded during endpoint merging.
- Stop cancels local polling and future submissions; it does not guarantee cancellation of an already-submitted server job. The current HTTP call may finish or time out before cancellation is observed. Progress measures completed legs, not server calculation time.

### Validation

Tests cover parsing/engineering, favourite persistence/corruption, full-tank boundaries, endpoint checks, partial results, cancellation, CSV and bilingual GUI actions. An online two-leg smoke query `Sol → Alpha Centauri → Barnard's Star` succeeded with a synthetic validation build. At Alpha Centauri, arrival fuel was about 31.98718 t and the next leg correctly restarted from the assumed 32 t; this is not a refuelling-availability check or an endorsement of that build.

### Rare-goods destination filter

**Experimental feature:** estimates may differ from actual in-game routes.

**Progressive geometric alignment:** within one search, reuse the same scanned candidates and choose the first nonempty tier **independently per Power**: strict alignment (30 degrees / 10% detour), moderate detour (45 degrees / 25%), then relaxed candidate (60 degrees / 50%). A Power with any stricter-tier geometric results never adds weaker-tier rows just to fill five slots. All tiers require projection onto the source-to-target line within [0, 1] (no reverse/overshooting anchors); detour is `d(source, neutron) + d(neutron, target) - d(source, target)`, relative to direct distance. These are adjustable defaults, not physical limits. No model-savings gate is applied. Prefer earlier tiers, then smallest detour and angle; the model hint is only a tie-breaker before name. Table/CSV show tier, outbound/return reference neutron stars, angle and detour. No guaranteed savings, full Power coverage or reduction in actual distance.

Tier relaxation does not fetch candidates or submit new route jobs. Within each existing station-search pass, evaluate the entire scanned batch before selecting per-Power tiers. The existing station-distance fallback remains separate: after exhausting all alignment tiers at <=100 Ls, only confirmed empty Powers may trigger the <=1000 Ls pass. Catalogue failures, partial pagination or cancellation remain incomplete; a tier selected from partial data is provisional and a stricter hit might exist in unseen candidates.

Available as an optional checkbox, off by default; independent of exact ship-specific planning. The catalogue is centered on the **selected goods source**, default **Ngurii**, not Sol. Only neutron systems within **200 ly of that source**, with a neutron body's arrival distance **<=100 Ls**, can be boost anchors in either direction. This 200 ly anchor radius is separate from the user's destination-distance interval. Near secondary stars are included; distant ones are excluded.

Spansh `/api/bodies/search` supplies the catalogue, with exact system-coordinate lookups for qualifying stars. Complete catalogues cache locally for seven days, keyed by source and coordinates. Pagination, identity, arrival distance, coordinates and actual 200 ly radius are validated; unavailable or incomplete data is not treated as an empty catalogue. No per-destination route jobs are submitted and there is no 50-destination budget. Station result coordinates are reused.

The optional internal hint uses a local directed graph for source, destination and each individual neutron anchor. Ordinary transfer cost is `ceil(distance / R)`; charged departure cost is `1 + ceil(max(0, distance - 4R) / R)`, taking the cheaper option. Use **R=40 ly outbound, R=50 ly return**, recomputing directions independently. Departure charging is allowed only at the neutron system. Ordinary intermediate stars, fuel and flight time are unverified; these are optimistic geometric estimates, not actual itineraries.

**The 40/50 ly hint never excludes a candidate or causes tier relaxation.** Geometrically aligned candidates remain eligible when estimated savings are zero or hint calculation fails. Missing catalogue/coordinates still mean unknown geometry, not a match; cancellation is still respected. Table/CSV omit jump counts, baseline, savings and internal completion/range columns. Outbound/return reference stars indicate candidates to consider, not verified charged departures; the selected aligned star is shown even if the hint does not recommend charging. Partial exports require confirmation; assumptions/completion status remain in the UI/search notes.

Apply filtering and system deduplication before the five-system limit per Power. Each system retains its nearest eligible station as a reference; summaries count systems only. Reuse comparisons across stations, Powers and the existing 100/1000 Ls station fallback. Catalogue errors or cancellation make results incomplete and must not trigger fallback as if no savings existed. Destination pagination limits still apply; no claim of exhaustive global ranking is made.

## 中文

本功能已包含在可下载的v0.1.3 Windows EXE中。

默认启用中子增压，后端仍使用 Spansh exact-plotter 的 `/api/generic/route` 按配船规划燃油与补油，不是固定跳距的中子路线接口；中子辅助路线仍可能包含普通跳跃。

### 配船与本地保存

- 导入单个 Coriolis JSON 或 EDSY SLEF（对象或单元素 SLEF 数组），不接受网页链接。仅保存命名舰船配置，不做航线收藏库。收藏文件损坏时提示，不静默重置为空；不自动读取个人 Journal 目录或指挥官档案。
- 规划时向 Spansh 发送所选 JSON 和航点，请勿包含不愿发送的私人信息。首次解析下载 [EDCD/coriolis-data 固定版本](https://github.com/EDCD/coriolis-data/tree/0db9234b5b9ce8c939ea84133d7ce336eea88e27)，[许可原文](https://github.com/EDCD/coriolis-data/blob/0db9234b5b9ce8c939ea84133d7ce336eea88e27/LICENSE.md)区分：JSON 数据版权属于 Frontier，受其条款约束；MIT 仅适用于 Coriolis 代码，不适用于 JSON 数据。程序不捆绑分发该目录，下载成功后本地缓存为 `route_module_cache.json`。
- SLEF 使用工程后的最优质量／单跳最大燃油，不舍入。Coriolis 应用最优质量修正及支持的实验效果。未知 FSD、备用油箱、实验效果或不支持的单跳燃油修改明确要求改用 SLEF，不猜测物理参数。按目前观察到的 Spansh 表单协议提交，网站未来变化可能需要更新客户端。

### 所选舰船属性

收藏预览仅显示船型、舰名及普通／中子增压后的满油跳距，不显示编号、倍率或 FSD 技术参数。后台获取／解析参数，不会为预览向 Spansh 提交配船。窗口内复用目录；切换收藏后忽略旧请求的迟到结果，缺失参数时清除旧跳距，不误显示上一艘船。货物变化在本地重新计算，切换语言不修改舰名。

理论满油跳距为 `最优质量 / (基础质量 + 主油箱容量 + 货物) × (min(主油箱容量, 单跳最大燃油) / 燃油倍率)^(1 / 燃油指数) + 守护者增程`，基础质量已含满副油箱。中子增压对包含守护者增程的完整普通跳距乘以支持的 FSD 倍率（通常4倍，支持的增压优化 Mk II 为6倍），参考[增程器／中子跳距模型](https://forums.frontier.co.uk/threads/the-science-of-the-guardian-fsd-booster-2-0.436365/)。3级守护者增程为7.75 ly。显示两位小数，不舍入计算输入；此预览不含注入及储备燃油限制，不代表当前位置能够中子增压或当前已增压。

### 多段规则

- 星系全名大小写不敏感匹配，全部航点解析成功后才提交。拒绝相邻重复点，允许非相邻重访。各段依次提交 `/api/generic/route` 并退避轮询 `/api/results/{job}`；HTTP 读取／超时受限，服务器每段计算预算60秒、本地轮询上限10分钟。未知状态、无效任务、无效跳跃或端点不匹配即失败，不跳过、不自动重提。
- 每段以原主油箱容量满油出发，不缩小油箱模拟剩余油量。合并共享端点时，分别保留前段到达燃油和后段假定出发燃油。“第一段已增压”仅用于首段，后续分段不沿用已增压假设。此为独立满油分段，**不保证燃油连续**，也不验证途经点有无补油设施／可吸油恒星。
- CSV 保留分段、出发段、途经点、满油提醒及未完成状态，转义可能触发公式的文本。取消或失败仅保留已验证的完整前段；部分导出需确认。距离两位小数、千位逗号，不修改原始值。剩余距离指**当前分段终点**，不是全程终点。
- 共享端点的分段／到达油量／本跳耗油描述前段到达；出发段／满油提醒及补油／中子／注入标记描述后段出发，合并时不会丢弃后段起点的出发操作。
- 停止取消本地轮询和后续提交，不保证撤销服务器已有任务；当前 HTTP 调用返回／超时后才可能响应取消。进度按完成分段计数，不是服务器计算耗时百分比。

### 验证

测试覆盖配船／工程、收藏保存及损坏、满油交界、端点核查、部分结果、停止、CSV 和双语 GUI。使用合成验证配船的在线两段查询 `Sol → Alpha Centauri → Barnard's Star` 已成功；Alpha Centauri 到达油量约31.98718 t，下一段确实重新按32 t出发。此测试不验证能否补油，也不构成推荐配船。

### 稀有商品目的地筛选

**实验性功能：**估算结果可能与游戏内实际航线不同。

**渐进几何顺路筛选：**一次查询复用同批候选，**逐势力独立**选择首个有几何命中的档位：优先顺路（30°／10%额外绕行）→适度绕行（45°／25%）→宽松候选（60°／50%）。已有严格档几何命中的势力不再加入较宽松结果，也不为凑满5条继续放宽。所有档位均要求来源到目标直线上的投影比例位于[0,1]（不反向、不越过目标）；额外绕行为 `来源到中子星 + 中子星到目标 − 来源到目标`，按直线距离计算比例。以上为可调整默认值，不是物理限制。不再要求通过模型省跳门槛。优先档位严格，再比较绕行、夹角；模型仅在这些几何条件相同时作为名称之前的次要排序。表格／CSV标注档位、去返程参考中子星、夹角及绕行，不承诺实际省跳、全势力有结果或距离缩短。

档位放宽仅做本地计算，不重新扫描候选或提交路由任务。每个已有站点查询轮次先处理整批已扫描数据，再选各势力档位。到站距离回退独立保留：≤100 Ls候选在全部顺路档位仍确认无结果的势力，才进入≤1000 Ls查询。目录失败、候选分页不完整或取消仍标为未完成；部分数据选出的档位仅为暂定，未扫描候选可能有更严格的命中。

已恢复可选复选框，默认关闭，与按配船精确规划独立。以**所选商品来源星系**（默认 **Ngurii**，不是 Sol）为中心，仅使用**来源200 ly内、到达距离≤100 Ls** 的中子星作为去返程增压锚点。200 ly 是锚点范围，与用户设置的目的地距离区间独立；近次星保留，远次星排除。

通过 Spansh `/api/bodies/search` 查询目录，对合格中子星精确获取所在星系坐标。完整目录按来源与坐标缓存7天，验证分页、身份、到达距离、坐标及实际200 ly范围；错误或不完整数据不解释为空目录。目的地使用站点结果已有坐标，不逐目的地提交路由任务，取消原有50个目的地评估上限。

内部参考模型逐颗以来源、目标和单颗锚点构建有向图。普通中转代价为 `ceil(距离/R)`，中子星出发可用 `1 + ceil(max(0, 距离-4R)/R)`，取较小值。去程 **R=40 ly**、返程 **R=50 ly**，分别计算方向，仅在中子星处允许增压出发。普通中转段假设存在合适落点，**未验证中转星、燃油、补油或时间**，是偏乐观几何估算，不是实际逐跳路线。

**40／50 ly模型不再排除候选，也不决定档位放宽。** 几何条件满足时，即使模型预计省跳为0或模型计算不可用，仍保留候选。目录／坐标缺失仍代表几何未知，不能当作命中；取消仍中止处理。表格／CSV不显示跳数、普通下限、预计节省或内部完成状态／跳距假设列。去返程参考中子星仅表示可考虑的星系，不代表已验证的增压出发；模型未建议增压时也显示所选顺路星。部分导出仍需确认，假设与完成状态保留在界面／检索说明中。

先筛目的地并按星系去重，再取每势力最近5个星系；同星系仅保留最近的合格站点作参考，汇总仅计星系数。跨站点、势力及100／1000 Ls站点回退复用比较。目录错误或取消标记未完成，不按确认无命中触发回退。目的地候选分页上限仍适用，不宣称全局穷举排行。
