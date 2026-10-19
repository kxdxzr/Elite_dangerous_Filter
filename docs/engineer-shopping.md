# Engineer trip shopping / 工程师途中采购

**Release status / 发布状态：** all source additions described below are included in
[v0.1.4-beta.2](releases/v0.1.4-beta.2.md). References to “not in beta.1” distinguish the older EXE.
下述源码新增功能已包含在beta.2；“未包含在beta.1”仅用于区分旧EXE。

## 功能描述

根据出发星系、目标工程师和自定单跳航程，寻找途中可在同一站购齐模组／舰载武器清单的售卖点。每项独立设置规格、折扣和数据新鲜度，可忽略航母／地面采购站，并限制到站距离和最多额外估算跳数。支持多跳行程，优先展示额外估算跳数少、绕行距离短的结果。跳数仅按距离估算，不代表已验证的实际航线；不核查商品购买数量。

界面短说明：**前往工程师途中，寻找少绕路的模组／舰载武器售卖点，可筛选已知折扣。**

## 输入与结果

- 出发星系可填写或联想；目的地只能从25位舰船工程师的“工程师名 — 星系”列表选择，包含Colonia与巫头地区，不含宇航服／手持武器工程师。名单来自[社区工程师列表](https://elite-dangerous.fandom.com/wiki/Engineers#Ship_Engineers)，核对日期2026-10-17。
- 单跳航程由用户自行填写，80 ly只是可编辑的默认值，不假设已读取当前配船。
- 最多额外跳数为非负整数，默认1；无需选择单跳或多跳模式。0表示估算总跳数不增加，并不代表完全不绕路。
- 点击“添加采购项”建立清单，各项支持独立的槽位分类、名称、单栏规格（如2C、5A或不限）、折扣和数据新鲜度，可单独删除。规格下拉只提供已确认组合，未收录规格可手填查询。**同一站必须满足全部采购项**；一行多选名称也会展开为全部必需商品，沿用该行规格／折扣／新鲜度。不同规格请分项添加，同一名称的不同规格可重复添加。普通主窗口的“属于其一”仍保持OR语义，不受此工具影响。
- 每项逐件复核名称、规格、折扣及新鲜度，缺少任何一项的站点不命中；这些不完整站点不占用“最多结果”名额。仅判断商品条目是否存在，不验证库存数量，不规划分多站凑单，也不会推断工程师是否能改造所选商品。旧条件的多值／部分规格筛选仍保留原义并以摘要显示。
- 折扣为“不限／是”，按[已知规则与例外](station-discounts.md)判断，默认要求折扣。当前源码另支持“效忠 Power（个人优惠）”，默认“无”；选择后默认勾选“按满级个人优惠计算”，不读取实际等级。Arissa／Archer／Yuri Grom 的适用武器按最高30%，Denton 按最高40%；仅在所选势力实际控制的 Exploited／Fortified／Stronghold 星系适用，不推定航母优惠、不与公共优惠相加，展示最强单项优惠。可取消勾选，仅计算公共优惠；选择及开关随会话保存。Archer 个人优惠不受其公共折扣 Bug 排除策略影响，但仍须游戏内核实。结果来源明确标注满级假设，并保留查询时设置，修改表单不会改写旧结果。本功能尚未包含在已发布的 v0.1.4-beta.1 EXE 中。
- “忽略航母”默认勾选。取消仅允许航母参与，仍须满足其他条件；不会为航母库存推定站点／势力优惠。
- “忽略地面站”默认不勾选，可独立启用并随会话保存。启用后采购点必须明确标记为非地面站；类型数据未知的不当作太空站。只约束采购站，不影响地面工程师目的地。
- 到站距离单位为`ls`，严格小于填写值，留空不限；默认1500 ls。
- **当前源码新增，尚未包含在已发布的 v0.1.4-beta.1 EXE 中：**采购站停机坪可选“不限／S／M／L”，按可停靠船型筛选，默认不限；S接受S／M／L，M接受M／L，L只接受L。由同一座满足完整采购清单的站点提供停机坪证据；未知数据在启用筛选时不命中，也不占用结果名额。只约束采购站，不判断工程师基地的停靠资格。选择随会话保存，旧会话默认不限；结果／CSV新增“已确认停机坪”列，显示已确认存在的最大尺寸，不代表未知的更大型坪必定不存在。
- 结果与CSV共用独立列：站名、星系、命中商品及规格、折扣幅度与来源（要求折扣时）、两端距离、到站距离（设限时）、直达估算跳数、到采购点估算跳数、到工程师估算跳数、经采购点估算总跳数、额外估算跳数、绕行距离`ly`。
- 完整采购清单、每项未完成草稿及行程参数随会话保存；旧版单项采购参数自动作为首项恢复。修改／增删表单不会改变上次搜索结果及其CSV的含义。结果和CSV按采购项编号分别展开命中名称、规格和折扣来源等列。

## 估算与检索边界

记出发地为A，工程师星系为B，采购星系为P，用户航程为R：

```text
直达估算跳数 N = ceil(|AB| / R)
经采购点估算总跳数 = ceil(|AP| / R) + ceil(|PB| / R)
额外估算跳数 = 经采购点估算总跳数 - N
绕行距离 = |AP| + |PB| - |AB|
```

同星系的零距离段算0跳。距离与跳数计算用完整精度，展示才保留两位小数。例如R=80 ly、直达320 ly、采购点在中途160 ly处，估算两段各2跳，合计4跳，额外0跳；不再因为两端都超过80 ly而淘汰。

仅保留额外估算跳数不超过用户限制的采购点；先按额外估算跳数升序，再按绕行距离升序，最后比较清单中最弱一项的已确认优惠幅度（未知按0处理），优惠不按商品总价加权。排序只覆盖已取回的命中，不承诺全库最优。绕路不合格的候选不会消耗结果数量名额，仍受页数上限约束。程序会显示取完候选、达到结果限制、达到翻页上限或停止等情况。

为避免搜索整个银河，检索先使用安全的两端包围球，再逐站复核两段估算跳数。包围球半径不是单跳航程。若允许额外K跳，则可接受行程的直线段距离之和不超过L=(N+K)R；任一段不超过(L+|AB|)/2，这就是两端包围球的半径（数值边界略微扩张）。

**这不是实际路线规划器。** 不枚举中转星、不验证燃油／载重／恒星分布／禁行区域，也不判断工程师解锁资格和许可。计算结果是距离下界意义上的跳数估算；即使显示“额外0跳”，实际路线也可能增加跳数或不可达。库存及折扣依据第三方记录和已知规则，最终以游戏内为准。

## English

**Current source only:** **Pledged Power (personal bonus)** defaults to None. Once a Power is selected, **Assume maximum-rank personal bonus** is enabled by default: eligible weapon discounts are 30% for Arissa / Archer / Yuri Grom, 40% for Denton. Actual rank is not read. Requires the selected Power's actual control and Exploited / Fortified / Stronghold state; carriers are excluded. No stacking with public discounts: show the strongest single rule. Uncheck to use public discounts only. Both settings persist across sessions. Archer's personal bonus is separate from the disabled public discount and still requires in-game verification. Result sources explicitly label the max-rank assumption; results retain their original settings when the form changes. Not in the published v0.1.4-beta.1 EXE.

**Current source only; not in the published v0.1.4-beta.1 EXE:** **Shopping pad (ship size)** offers **Any / S / M / L**, default Any. S accepts S/M/L pads, M accepts M/L, and L requires L. The same station must satisfy the full shopping list and the pad requirement. Unknown pad evidence is rejected when filtering and does not consume the result cap. This does not check engineer-base access. The choice survives sessions; older sessions default to Any. Results/CSV include **Confirmed landing pad**, the largest positively evidenced size, not proof that an unknown larger pad is absent.

**Ignore planetary stations** is an independent checkbox, disabled by default and saved in sessions. When enabled, shopping stations must explicitly be non-planetary; unknown flags are not treated as space stations. This does not exclude planetary engineer destinations.

**Description:** Find stations on the way to your selected ship engineer that stock every module / ship weapon on your shopping list, using your chosen jump range. Each item has independent specifications, discount and freshness requirements. Optionally ignore carriers or planetary shopping stations, limit arrival distance, and cap estimated extra jumps. Single- and multi-jump trips are handled automatically. Results favour fewer estimated extra jumps, shorter detours, then the strongest minimum item discount across the list (unknown = 0, not a price-weighted basket saving). Jump counts are distance-only estimates, not verified routes; purchase quantities are not checked.

The destination is a readonly **Engineer — system** list of 25 ship engineers. The editable defaults are 80 ly range, at most one estimated extra jump, arrival distance below 1500 ls, required discount per new item, and ignored carriers. Use **Add shopping item** for independently specified products; multiple names within one row also mean ALL products, sharing that row's specification/discount/freshness settings. One station must satisfy the entire list, including distinct variants of the same module. This does not verify quantities, split the basket across stations, or check an engineer's modification capabilities. List entries, unfinished drafts and all trip settings survive sessions; old single-item sessions migrate to the first entry. Results/CSV have independent evidence columns per item. Ordinary main-window OR conditions are unchanged.

For departure A, engineer B, shop P and range R, direct jumps are `ceil(|AB|/R)`, shopping jumps are `ceil(|AP|/R)+ceil(|PB|/R)`, extra jumps are their difference, and detour distance is `|AP|+|PB|-|AB|`. Zero-distance legs count as zero jumps. Calculations retain full precision; only display values are rounded. An extra-jump limit of zero does not imply a zero-distance detour.

Search bounds safely enclose all eligible points; the endpoint-sphere radii are not single-jump limits. The exact estimated-extra-jump check runs before the result cap is counted. Ranking applies only to fetched matches, not the whole database; result/page limits and stopping may leave a search incomplete. The table and CSV show separate item/specification, discount/source, endpoint/arrival-distance and estimated-route columns. Arrival distance uses `ls`, detour distance uses `ly`.

No intermediary stars, fuel/loaded range, restricted routes, permits or engineer access are validated. Estimated zero extra jumps may still mean additional actual jumps or an infeasible route. Stock and discounts depend on third-party records and known public rules; verify them in game. Suit/handheld-weapon engineers and personal/pledge discounts are outside this feature's scope.
