# 查找满配件空间站 / Find fully outfitted stations

**自v0.1.4正式版起提供；旧v0.1.4-beta.2 EXE不含此工具。**

支持[GitHub装备清单独立更新与回退](catalog-updates.md)：手动检查、确认版本／摘要、校验后安装；已有库存快照时，需要“更新数据并查询”后应用新清单。首份清单Release尚未发布。

## 一次更新，多次本地筛选

**适用范围提醒：主要适用于Bubble（人类核心居住区）。远离Bubble后，现有站点名单可能不再适用或没有结果；更换参考星系只重算距离，不会自动发现当地站点。无结果不代表当地一定没有配件供应。**

- 首次查询和手动更新均固定以**Sol为中心、半径20,000 ly**建立最宽松库存快照，与用户表单中的参考星系／半径无关。采集不要求折扣、AX、Merc、通用无人机控制器、舰船或Guardian经纪人。保留所有通过最宽松库存核验的站及其原始库存、已有身份补证和最终展示资料，再按用户条件重算距离及筛选。
- 建立快照时不受“最多结果”限制，必须完整取完候选；“最多页数”仅限制联网更新预算。页数不足、停止或网络失败都不会用不完整数据替换原快照。
- 之后所有条件筛选都基于已有的小型站点名单，**不重扫库存、不重建目录**。最多结果仅限制显示数量，不截断保存的数据。缓存中仍无法确认的Merc身份等不会因本地筛选而猜成有货。
- **可以任意更换参考星系或扩大／缩小半径**：用名单中站点的星系坐标重算距离，按新距离排序、筛选；不会因此刷新库存。缺少新参考星系或站点坐标时，仅向Spansh查询相应星系坐标并缓存，之后可离线复用。坐标无法确认则报错，绝不套用旧参考星系的距离。
- 扩大半径不会自动发现名单外的新站点；CSV中的“已有站点名单筛选完成”只代表本地名单已筛完，不表示新范围的全量检索完成。需要重新发现站点或刷新库存时，手动点击“更新数据并查询”。
- 快照继续保存在同一个`full_outfitting_snapshot_v1.json`文件，手动更新成功后原子覆盖，不另存多套扫描缓存；失败保留原文件。已有Sol中心20,000 ly完整缓存会原位迁移格式并直接复用，不重扫库存，也不改变原库存时间。旧小范围缓存需手动更新，不能误认为已覆盖固定范围。关闭窗口或重启程序仍可使用，不存在自动过期刷新。
- 快照包含固定装备目录；GitHub清单更新或回退后，旧快照仍按原目录核验，手动更新库存数据后才采用新清单。下载清单不代表刷新库存。
- 更新失败保留原快照和已显示结果；可改回旧快照范围继续查询。首份完整快照尚未成功建立时，下次查询仍需建立，或点击更新重试。
- 首次采集的范围和时间保留为来源信息；换参考星系不改变它们或库存时间，不是全银河或实时库存保证。
- 界面显示“缓存于（N）天之前”，按快照原创建时间计算已过的完整24小时数，不使用文件修改时间；不足一天显示0天。打开窗口即可读取本地缓存时间，筛选／格式迁移不会重置天数；成功更新数据后重新计算。

## 筛选语义

- **Merc要求明确排除High-Yield Enzyme Missile Rack 2B**，保留身份事实及其他Merc规格要求。[排除记录与恢复评估](catalog-next-version.md)包含原因和限制；移除此项不代表其他Merc身份歧义已解决。

- **通用多功能无人机控制器7A／7C独立可选，默认关闭**；启用后要求两项同站齐全。其他无人机控制器的要求不变，CSV与会话记录此开关。
- **普通及Mk II大型行星车库当前暂不要求**，已加入[未来版本计划](catalog-next-version.md)。普通Planetary Vehicle Hangar仍保留。

- **AX装备独立可选，默认关闭。** 包含AX导弹／多管炮及增强型、高级导弹／多管炮、遥控高射炮、异种扫描器（含增强型及脉冲波）、实验武器稳定器、关闭力场／异种脉冲中和器、去污无人机及异种多功能无人机控制器，以及泰坦救援专用的2B Sub-Surface Extraction Missile。普通采矿用Sub-Surface Displacement Missile仍是默认要求。Power配件要求不变。覆盖分母随开关变化，CSV记录条件。下文853/853等验收数字为拆分AX之前的历史结果。内部会话字段仍保留`ax_weapons`以兼容已有设置，含义现为AX装备。
- **`_free`领取版机库不列入库存需求**，无论AX开关是否开启；普通付费版机库仍须逐规格核验。不会把此规则扩展为排除所有`_free`配件。
- **当前版本暂不要求Mk II舰载机库（Mk II Vessel Hangar）**，付费版也不要求；记录于[装备清单：下版本可能添加](catalog-next-version.md)，未来版本是否恢复另行决定。普通Vessel Hangar仍保留。
- Brestla / i Sola Prospect具有20%公共加价（原价120%），结果和CSV明确显示，不再写成未知折扣；该站不能通过“必须全配件公共折扣”。规则仅匹配这个星系与站点组合，不推广到整个Brestla星系。

- **折扣要求可选，默认关闭。** 默认只要求同站全部已知普通／Power配件实际规格齐全，折扣仅作为结果信息。
- 启用“必须全部普通／Power配件都有公共折扣”后，默认仅 Li Yong-Rui 实际控制的 Fortified / Stronghold 星系，使用15%公共配件折扣。
- 排除所有航母，包括要塞航母。没有站点类型证据也不入选，不推定航母有 LYR 优惠。
- 可勾选包含其他全配件公共折扣站，例如 Jameson Memorial 的10%。不是枚举几个著名站点就直接判定齐全；仍核验库存。
- “其他”只在启用折扣要求时有效；关闭折扣要求时禁用控件但保留草稿。折扣模式按已知公共规则分来源查询，当前额外来源为Jameson Memorial，再合并LYR，不扫描无关商店。
- 不要求折扣时查询范围内配件商店，先用目录内全部必需的8A/A级普通配件（排除舰船专属及特殊装备）作服务器预筛，再逐项核验全目录。这不是放宽齐全标准，不能只靠预筛项目就通过。
- 同一站点必须具备全部已知普通、Power 配件实际规格。不拼接多个站点，不计个人武器优惠，不叠加折扣。只有启用折扣要求时，未确认全配件公共优惠才会排除候选。
- 结果及CSV区分“全配件有已知优惠／部分配件有已知优惠／未确认公共折扣”。Attilius Orbital等部分商品优惠不会误标成全配件折扣；勾选折扣要求时仍不能靠局部优惠通过。
- 默认具有所有 Power 配件购买资格，不读取个人等级、效忠、解锁记录。
- **Merc Coins 特殊装备为独立可选条件，默认关闭。** Rapid Phase Multi-Cannon、Enduring Feedback Rail Gun、Extended Cargo Rack等是 Operations 预改装装备，不是Power专属配件。勾选后额外检查其全部已知规格库存；不推定代币价格享有公共信用点折扣，也不拿特殊版代替普通版。
- 三个独立可多选项：全部非势力船（含联盟）、全部联邦船、全部帝国船。默认都不选；勾选后同时要求对应舰船及船体装甲齐全，舰船本身不要求折扣。
- 默认不要求任何船型专属装甲。船体装甲不能由其他船型的同名装甲代替。
- 可选同站 Guardian 科技经纪人。普通 Technology Broker 服务不等于 Guardian，Human 经纪人也不满足；有经纪人不代表已解锁或全部科技产品齐全。
- 科技经纪人兑换、工程师专供、其他预改装／活动限定产品不属于普通零售库存；真正的Power专属产品保留在必需目录中，Merc Coins装备单独按开关检查。
- 工程师专售的1级普通护盾、8级普通FSD不列入通用零售要求；**8级SCO FSD仍保留**。Caustic Sink Launcher属于限定科技／救援供应，不混入通用零售目录。2026-10-20的供应点审计中，8C普通FSD的14个供应点、1A护盾的3个供应点均带Workshop服务。

## 创世正向回归基准

Jameson Memorial / Shinrarta Dezhra 是正向验收基准，不是固定参照面板，也不能强塞进结果。
在不要求折扣，或启用折扣要求并“包含其他公共折扣站”，且范围覆盖创世、没有额外不适用条件的测试下，应通过正常检索、正常出现在结果表中。
如果没有出现，应继续排查目录或识别逻辑，不能因单元测试通过就宣布全配件功能验收完成。
该项线上验收必须独立于单元测试执行；结果以实际查询记录为准，不能靠固定展示或豁免站点库存检查代替。
内部参照查询只供诊断，不绕过正式结果的筛选条件。

2026-10-20 实机验收（当前版本，已启用全部必需8A/A级普通配件预筛）：

- **折扣可选（默认）**：Sol，500 ly，最多50个结果、25页，其他附加条件关闭。扫描1580条候选，分页完成，无请求错误，耗时约196秒；命中3站，均为853/853：**Jameson Memorial / Shinrarta Dezhra（10%，853项全部有已知优惠）**、**Attilius Orbital / CD-43 11917（部分配件30%优惠，只标为部分优惠）**、**i Sola Prospect / Brestla（未确认公共折扣）**。
- **要求全配件公共折扣**：同样的范围与页数，并勾选“包含其他公共折扣站”。扫描184条候选，分页完成，无请求错误，耗时约25秒；只命中**Jameson Memorial，853/853，10%公共折扣**。Attilius的部分优惠不会通过。
- 两次命中都通过Spansh与同市场EDSM库存复核产生，不是固定行、站点白名单或跳过库存校验。预筛只发送目录中必需的普通8A/A级配件（排除舰船专属及特殊装备），任何被排除的站也无法满足完整库存要求。
- 本地420项自动测试通过。单次验收不保证未来第三方服务可用或游戏内即时库存。

## 目录与数据限制

首次查询构建独立的公开事实目录，之后缓存到
`%LOCALAPPDATA%/EliteDangerousFilter/full_outfitting_catalog_v4.json`，不会改变原会话或配船收藏。
v1/v2/v3缓存不再使用，但不删除，v4首次查询会重新构建目录。
身份事实同时记录普通、Power与Merc装备，后者仅在勾选时参与库存要求，不再为特殊装备逐个扫供应站来猜规格。
源码运行使用仓库的 `cache/` 目录；`ELITE_FILTER_DATA_DIR` 可覆盖路径。检索说明与CSV开头的信息区保留目录事实版本和核验时间，不在各站点结果行中重复。
目录来源为 Spansh 实际库存观测、项目现有真实 class/rating 对表及固定版本
EDCD/coriolis-data `0db9234b5b9ce8c939ea84133d7ce336eea88e27` 的符号／规格事实。
真实物品身份与当前规格使用固定EDCD/FDevIDs版本 `c35612952dd6a547d1a7ac4cffab9c7051e86579`。
同一数字物品ID的历史名称／评级变化不会重复要求；普通版与Merc版即使符号相同，数字ID不同就保留为不同产品。
界面可“刷新目录并查询”；刷新不会扫描 Journal 或上传私人配置。

只使用真实观测／事实条目，不将尺寸、评级和挂载方式做笛卡尔积。
优先用数字ID识别产品；没有身份事实的测试／旧条目保留严格名称、符号及规格匹配。
Merc与普通版的同符号记录若缺失数字ID，则不能证明两种库存都有，仍标为**无法确认**。
对于其余规格齐全、仅存在这种身份冲突的候选，按相同市场ID、星系和站名读取EDSM公开配件记录作第二来源复核。
明确列出普通版的独立记录可以补证普通库存，不能顺便证明Merc版本也有货；本规则适用于所有候选，不仅是创世。
EDSM未提供库存更新时间，界面／CSV明确列出其来源，不冒充现场实时库存，也不合并附近或不同市场的商店。
目录保留冲突证据；它们不再混在普通“未收录规格”中。
固定／万向／炮塔版本由实际符号区分。历史 class/rating 对仍未补齐时，目录不完整，工具会停止严格判定并列出缺项；失败目录不缓存成有效目录。

**“齐全”始终相对于此版本的已知目录，不代表实时、穷尽未来新增产品的官方保证。**
目录可能陈旧，库存上报可能缺失，不足以证明零售站不存在某物品。
工具不会因某个项目难找到而自动降低标准，也不会为了有结果而偷偷排除 Power 配件。
严格模式仍可能无命中；可查看检索说明中的未收录规格、身份冲突、未知优惠和未通过候选（按覆盖率优先，最多100条）。
身份冲突不是已通过库存要求，不会为了有结果而默认为齐全。状态栏现在只统计**仅待身份复核（其余要求均满足）**的站点，不再把同时缺少大量库存的站点也算进去。
另外显示“库存未齐或未收录”，检索说明按这两类和其他条件失败分别标注。只有真实完整、仅剩身份问题的候选才触发第二来源复核；复核成功转为正式命中，否则保留待复核，不强行判有货。

结果显示覆盖数量、公共折扣范围及来源、Guardian 经纪人、许可证据和配件更新时间。
特殊装备／AX／通用控制器／舰船条件、折扣要求、目录与身份版本、快照范围／时间和检索完整性统一放在CSV开头的信息区（界面中可查看“检索说明”），不再逐站重复。库存核验来源也移到信息区；来源不同时按来源分组并列出对应星系／站点，避免丢失证据归属。站点各自的配件库存更新时间仍保留在结果行。
CSV开头的项目信息区最下方记录本次检索条件（参考星系、半径、结果／页数上限及全部可选条件），
随后空行分隔结果表头；使用查询快照，不使用导出时修改过的表单。
最终命中统一补查Spansh星系资料（包括已知折扣站），填入许可等空字段；距离、
经纪人及服务字段缺失时，再按同星系、同站名、同市场ID补查站点。
不覆盖已有的false、零值或实际库存，不把新响应时间冒充原库存时间。
Spansh仍无记录时显示“Spansh未提供”，网络失败记录到检索说明，保留已核验命中。
各来源共享“最多页数”预算；结果数量达到上限不代表搜完整个范围。为避免深分页，每个来源最多扫描10000条候选。
HTTP 500/502/503/504及临时网络错误最多重试一次；失败时标明来源、页码和错误，不丢掉之前已验证的命中。
一个独立来源失败后，在预算及停止条件允许时仍可查询其他来源。部分结果导出须确认，CSV保留检索完整性标记。
分页／停止／请求失败均不宣称遍历了全银河。CSV导出使用查询结果快照，改变表单不会重算旧结果。

上述游戏事实属于各自权利人，尤其是 Frontier；项目 GPL-3.0-only 不授予对第三方数据的额外权利。
不捆绑下载的目录、原始库存、价格、图片或字体。详见 [折扣策略](station-discounts.md)。

分类依据：[Frontier Operations 更新说明](https://cms.zaonce.net/en-GB/node/7931)、
[Frontier Merc 装备说明](https://forums.frontier.co.uk/threads/new-modules-available-for-mercs.647907/)。

## English

This tool is primarily intended for the Bubble. Far outside it, a saved Bubble
station shortlist may no longer be useful or return results. Changing reference
only recalculates distances; it does not discover local stations. No results do
not prove that local outfitting is unavailable.

Initial and manual discovery always use Sol as the centre with a 20,000 ly radius,
independently of the form's reference/radius, selected options and display limit.
The resulting persistent widest-scope snapshot is then filtered for the user's query.
Subsequent searches reuse that station shortlist and stock. Any reference/radius is
supported by recalculating and sorting distances from system coordinates. Only missing
system coordinates are fetched from Spansh and cached; inventory is not re-fetched.
Increasing radius does not discover stations outside the saved shortlist. Only an
explicit **Update data and search** refreshes the stock/shortlist. Failed/incomplete updates preserve the previous
snapshot. The catalogue is pinned within each snapshot; installed catalogue updates
apply when stock data is manually refreshed. Snapshot time and scope are exported.

AX equipment is a separate, default-off requirement, including AX/Advanced weapons,
flak launchers, Xeno scanners, experimental weapon stabilisers, neutralisers,
decontamination and Xeno limpet controllers, and the Titan-rescue 2B Sub-Surface
Extraction Missile. The mining Sub-Surface Displacement Missile remains required.
Universal Multi Limpet Controllers 7A/7C are separately optional (off by default).
Claimable `_free` hangars, Mk II Vessel Hangars, and both Large Planetary Vehicle
Hangar families are excluded from current requirements; standard Vessel Hangars
and Planetary Vehicle Hangars remain required. Large hangars are on the future-version review list.
Power requirements are unchanged. Coverage and CSV
record the selected AX scope; the 853-item live regressions below predate this split.

**Available in stable v0.1.4; not included in the older v0.1.4-beta.2 EXE.**

Discount requirements are optional and off by default. Complete ordinary/Power
stock is still mandatory; discounts are informational unless explicitly required.
With the discount requirement enabled, default scope is LYR-controlled Fortified /
Stronghold systems with the 15% public discount.
All carriers, including Stronghold Carriers, are excluded. An opt-in includes other
public all-module discounts such as Jameson Memorial, but never bypasses stock checks.
Known public-discount sources are queried separately and deduplicated; enabling
other discounts no longer scans every outfitter in the radius. Without a discount
requirement, every mandatory class-8/A ordinary catalogue variant (excluding
ship-specific and special equipment) prefilters outfitters before the complete
same-station check. Sources share the
page budget; each source has a 10,000-candidate safety limit.
Every known actual ordinary/Power module variant must be sold at the same station;
public discounts on every required module are optional. Partial/unknown discounts
are explicitly distinguished in the table/CSV. Personal weapon bonuses are not counted; all Power purchase eligibility
is assumed without reading commander data.

Independent ship-group options require all selected non-rank-faction (including
Alliance), Federal or Imperial ships and their hull armour. No ship selections means
no ship-specific armour checks. Ship discounts are not required. The optional Guardian
broker condition needs explicit Guardian evidence, not a generic broker service, and
does not assert complete broker unlock stock. Engineer/broker-only, pre-engineered and
limited-event products are outside ordinary retail requirements.

Merc Coins/Operations special equipment is a separate, default-off stock requirement,
not part of Powerplay eligibility or ordinary retail completeness. Selected equipment
does not substitute for base modules; no token-price discount is inferred. Its
identity facts are loaded with the ordinary/Power catalogue, but its stock requirement
is activated only by the separate checkbox.

Jameson Memorial is a positive acceptance benchmark, not a fixed panel or injected hit.
With discounts unrestricted (or other public discounts enabled), an encompassing
radius and no incompatible extra conditions, it must appear through the normal
result pipeline. On 2026-10-20 the current build scanned 1,580 candidates with
discounts optional and 184 with all-module discounts required, completing both
without request errors. Jameson Memorial was a real 853/853 hit in both runs
(10%); Attilius Orbital and i Sola Prospect were real optional-discount hits.
The internal reference helper is diagnostic only.

The versioned catalogue uses real Spansh stock observations, existing audited
class/rating pairs, pinned Coriolis facts, and EDCD/FDevIDs revision
`c35612952dd6a547d1a7ac4cffab9c7051e86579` for numeric product IDs/current descriptions.
Changes in an ID's descriptive rating/name do not create additional required products.
Ordinary and Merc variants with different numeric IDs are not merged despite shared symbols.
No Cartesian products or inferred mount variants. Unresolved catalogue gaps fail
closed, are shown in diagnostics and are not cached as a complete catalogue.
Only audited spelling/renaming aliases are deduplicated. A shared symbol with a
different name/rating is reported as uncertain identity, not confirmed absence or
permission to count one item as both ordinary and special/Power stock. v4 rebuilds
without deleting v1/v2/v3 caches. Workshop-only class-1 ordinary shields, class-8
ordinary FSDs and restricted Caustic Sink Launcher stock are not general-retail
requirements; class-8 SCO drives remain required. Candidate diagnostics prioritise coverage.

Nearly complete candidates with only ambiguous identities are cross-checked against
explicitly named EDSM stock at the exact same market/system/station. This is not a
Jameson-specific exemption, and never proves both ordinary and Merc stock from one
symbol. EDSM does not supply an inventory timestamp; exports retain that limitation.

Coverage is relative to this known catalogue, not guaranteed live stock or exhaustive
future game content. An empty search is possible and does not prove universal absence.
Catalogue refresh is explicit after the initial download; it does not read Journals or
send private builds. Failed candidates (up to 100) and missing specifications can be
inspected. CSV exports retain the completed search snapshot. Third-party game facts
retain their own ownership/terms; downloaded facts and prices are not bundled.

The pending-identity counter includes only candidates meeting every other active
requirement. Candidates also missing inventory are counted separately, not presented
as almost-qualified identity-only candidates. No ambiguous stock is treated as present.

Transient HTTP 500/502/503/504 or network errors are retried once. Remaining errors
identify the source/page and retain already verified hits; independent sources may
continue within the remaining budget. Partial exports require confirmation and
include a search-completeness column. No claim of exhaustive live availability.
