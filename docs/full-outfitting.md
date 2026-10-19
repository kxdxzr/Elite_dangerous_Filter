# 全配件折扣站查找器 / Full-outfitting discount station finder

**当前源码新增，未包含在已发布的 v0.1.4-beta.2 EXE 中。**

## 筛选语义

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
源码运行使用仓库的 `cache/` 目录；`ELITE_FILTER_DATA_DIR` 可覆盖路径。表格及CSV保留目录事实版本和核验时间。
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
各来源共享“最多页数”预算；结果数量达到上限不代表搜完整个范围。为避免深分页，每个来源最多扫描10000条候选。
HTTP 500/502/503/504及临时网络错误最多重试一次；失败时标明来源、页码和错误，不丢掉之前已验证的命中。
一个独立来源失败后，在预算及停止条件允许时仍可查询其他来源。部分结果导出须确认，CSV保留检索完整性标记。
分页／停止／请求失败均不宣称遍历了全银河。CSV导出使用查询结果快照，改变表单不会重算旧结果。

上述游戏事实属于各自权利人，尤其是 Frontier；项目 GPL-3.0-only 不授予对第三方数据的额外权利。
不捆绑下载的目录、原始库存、价格、图片或字体。详见 [折扣策略](station-discounts.md)。

分类依据：[Frontier Operations 更新说明](https://cms.zaonce.net/en-GB/node/7931)、
[Frontier Merc 装备说明](https://forums.frontier.co.uk/threads/new-modules-available-for-mercs.647907/)。

## English

**Unreleased source feature; not included in the published v0.1.4-beta.2 EXE.**

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
