# Public station / Power discounts · 地点／势力公共优惠

**Release status / 发布状态：** the policies and personal-bonus extension below are included in
[v0.1.4-beta.2](releases/v0.1.4-beta.2.md). Older “source-only / not in beta.1” notes refer to beta.1.
下述策略和个人优惠扩展已包含在beta.2；旧“仅源码／未包含在beta.1”说明指beta.1版本。

**Source-only personal-bonus extension (2026-10-18):** engineer shopping now allows an explicit pledged Power, default None, and assumes maximum-rank rewards by default when selected. Eligible weapon bonuses: Arissa Lavigny-Duval / Jerome Archer / Yuri Grom 30%, Denton Patreus 40%, only in that Power's actually controlled Exploited / Fortified / Stronghold systems, excluding carriers. Public-rule exclusions below do not disable Archer's separate personal bonus. This is an unverified rank/price assumption, labelled in result sources, not an automatic entitlement. No stacking: use the strongest single rule. Unchecking the assumption restores public-only calculation. The exclusions of personal bonuses mentioned below describe the public catalogue, not this opt-in engineer-shopping extension.

**仅当前源码的个人优惠扩展（2026-10-18）：**工程师采购可明确选择效忠 Power，默认“无”，选择后默认按满级奖励计算。适用武器优惠为 Arissa／Archer／Yuri Grom 30%、Denton 40%；仅限该势力实际控制的 Exploited／Fortified／Stronghold 星系，航母除外。下述公共规则对 Archer 的排除不禁用其独立个人优惠。未读取等级、未验证实际结算，结果来源标注满级假设，不代表已获得购买资格；不叠加，取最强单项优惠。取消满级假设后仅计算公共优惠。下文“排除个人奖励”指公共优惠目录，不包括此工程师工具显式启用的扩展。

Rules checked against the community-maintained [Discounts list](https://elite-dangerous.fandom.com/wiki/Discounts) and [Li Yong-Rui](https://elite-dangerous.fandom.com/wiki/Li_Yong-Rui) page on 2026-10-17. These are rule-based candidates, not live checkout-price validation. No standard-price catalogue is fetched. Associated Power alone is insufficient: Power rules require `system_controlling_power` and a supported `system_power_state`. Carrier listings do not inherit retail discounts.

规则核对日期为2026-10-17；来源为上述社区维护资料，不代表实时结算验证。不下载价格表，势力规则要求实际控制势力与对应状态，不将关联 Power 当作控制关系，航母列表不继承零售站优惠。

| Source / 来源 | Scope / 适用范围 | Reduction / 优惠幅度 |
| --- | --- | --- |
| Li Yong-Rui, Fortified / Stronghold | Ships and modules / 舰船及模组 | 15% |
| Jameson Memorial, Shinrarta Dezhra | Ships and modules / 舰船及模组 | 10% |
| Denton Patreus, Exploited / Fortified / Stronghold | Imperial Eagle, Courier, Clipper, Cutter | 10% |
| Edmund Mahon, Fortified / Stronghold | Standard Cargo Rack, Hull Reinforcement Package / 普通货架、船体增强套件 | 20% |
| Jerome Archer | Public Power discount disabled due to a reported game bug / 因已报告的游戏 Bug，势力公共折扣按不生效处理 | Excluded / 不计入 |
| Alioth | Known Lakon ships / 已知 Lakon 舰船 | 5% |
| Irkutsk, Alioth | Asp Explorer, Orca | 20% |
| Hamilton Gateway, Wolf 406 | Diamondback Explorer, if stocked / 有货时 | 20% |
| Henry O'Hare's Hangar, Summerland | Imperial Eagle, Courier, Clipper, Cutter | 10% |
| Daedalus, Sol | Federal Dropship, Vulture; Eagle | 10%; 20% |
| Edmondson High, Beta Hydri | Eagle | 10% |
| Attilius Orbital, CD-43 11917 | Selected ships; selected small/medium non-turret weapons and chaff/heat sinks / 指定舰船；指定小中型非炮塔武器及箔条／散热器 | 20%; 30% |

Each requested item must still exist in the returned stock and match its name and module class/rating. Location rules require both system and station identity. Missing details or unmatched rules do not qualify for **True**. This is not an exhaustive discount catalogue: personal Elite/pledge bonuses, expired CG sales and unconfirmed new products are excluded. Overlapping rules show the strongest single known reduction, not an invented stacked percentage. Legacy unfinished **False** selections become **Any**.

Edmund Mahon is only partially affected: retain the 20% discount for standard Cargo Rack / Hull Reinforcement Package in Fortified / Stronghold systems, not Exploited. Guardian Hull Reinforcement Package (HRP) / Guardian Shield Reinforcement Package (SRP) discounts at Guardian Technology Brokers are reported as described but not applied, and are excluded from Mahon's rule. Independent station discounts remain eligible. This source change is not yet in the published v0.1.4-beta.1 EXE.

Edmund Mahon 仅部分优惠受 Bug 影响：Fortified／Stronghold 星系的普通货架／船体增强套件保留20%优惠，Exploited 不计入。Guardian 科技经纪人处的 Guardian 船体增强（HRP）／护盾增强（SRP）存在“描述有折扣但实际未应用”的游戏 Bug 报告，不计入 Mahon 势力优惠；独立站点优惠仍可适用。此源码调整尚未包含在已发布的 v0.1.4-beta.1 EXE 中。

Current source policy (2026-10-18; not yet in the published v0.1.4-beta.1 EXE): treat Jerome Archer's public Power discount as inactive in all states due to a reported game bug where the displayed discount is not applied ([Frontier issue #70307](https://issues.frontierstore.net/issue-detail/70307)). This is a filtering policy, not live verification of the bug's current status. Independent station discounts in his territory remain eligible. Li Yong-Rui's 15% discount in Fortified / Stronghold systems remains enabled.

当前源码策略（2026-10-18，尚未包含在已发布的 v0.1.4-beta.1 EXE 中）：**因已报告的游戏 Bug（界面显示折扣，但实际价格未应用，[Frontier 问题单 #70307](https://issues.frontierstore.net/issue-detail/70307)）**，将 Jerome Archer 所有状态下的势力公共折扣按不生效处理，不计入折扣筛选或展示，并非该势力在规则上没有优惠。这是筛选策略，不代表已实时验证该 Bug 当前是否修复；其领地内独立站点优惠仍可命中。Li Yong-Rui 在 Fortified／Stronghold 星系的15%优惠保持启用。

仍须在实际返回库存中找到同件商品，并满足名称及模组等级／级别；地点优惠同时匹配星系与站名。证据缺失或没有已知规则不命中“是”。规则并非穷尽所有优惠：不计算个人 Elite／效忠奖励、过期社区目标优惠或未经确认的新商品。同件商品有多条规则时显示最大单项优惠，不猜叠加比例。旧版未完成的“否”选择转换为“不限”。

UI/CSV show **matched item**, **class**, **rating**, **discount %**, and **source** in separate columns as applicable. Percentages mean price reductions: **15 = 15% off = 85% of original price**, not a 15%-of-original purchase price. Verify access permits, stock and final prices in game.

界面及CSV按需分列显示命中商品、等级、级别、优惠幅度及来源；**15表示减价15%，即85折**，不是原价的15%。请在游戏内复核许可、库存及最终结算价。

## Discounts Wiki supplement / Wiki 补充核对（2026-10-18）

### Bug-report reference / 折扣未生效参考资料

[Frontier Forums: Powerplay-related discount v2.0 — even if not pledge](https://forums.frontier.co.uk/threads/powerplay-related-discount-v2-0-even-if-not-pledge.630099/)

This community report is the reference for excluding **Archer's public weapon discount** and **Mahon's Guardian HRP / SRP broker discount**. It does not establish that Archer's separate maximum-rank 30% personal weapon bonus is broken. Reported behaviour is not confirmation of the current game's fix status; personal bonuses remain explicitly labelled assumptions.

该社区核查帖作为 **Archer 公共武器折扣**与 **Mahon 的 Guardian HRP／SRP 科技经纪人折扣**未生效的参考资料。不能据此认定 Archer 独立的满级30%个人武器优惠也失效。历史报告不代表已确认当前版本的修复状态；个人优惠仍明确标为假设。

Cross-checked against the [Active Discounts](https://elite-dangerous.fandom.com/wiki/Discounts#Active_Discounts) and [Expired Discounts](https://elite-dangerous.fandom.com/wiki/Discounts#Expired_Discounts) sections. The listed public location discounts are already represented above; the Wiki's Archer entries do not override the reported-bug exclusion policy.

- **Personal Elite bonus:** the Wiki lists a galaxy-wide 2.5% ship/module discount after an Elite rank in Combat, Trade, Exploration or CQC, stackable with other discounts. The tool does not read commander ranks, so it neither enables this bonus nor calculates stacked percentages.
- **Access is separate:** Alioth, Shinrarta Dezhra, Summerland, Sol, Beta Hydri and CD-43 11917 require permits. Ship rank requirements still apply where relevant. A discount match does not verify either requirement.
- **Stock is required:** the Wiki notes Diamondback Explorer as out of stock at Hamilton Gateway. Its rule is conditional on the actual returned listing containing that ship; the tool does not assume availability from the discount catalogue.
- **Attilius Orbital:** the 30% module discount covers only the named products in the table, excludes Class 3+ and turret weapons, and is not a blanket outfitting discount. Its 20% ship discount is also limited to the named ships.
- **Expired sales stay excluded:** examples include the Lembava 23.5% FSD sale, Onnes Gateway's 30% module sale and Torval's 40% mining-equipment sale. Do not infer current eligibility from historical CG rewards.

已对照 Wiki 的“有效优惠”和“已过期优惠”两节；其公共地点优惠已由上表覆盖。Wiki 仍列出的 Archer 优惠不覆盖本工具按已报告 Bug 排除的策略。

- **Elite 个人奖励：**Wiki 记载，战斗／贸易／探索／CQC 任一领域达到 Elite 后，舰船与模组享受全银河2.5%优惠，可与其他优惠叠加。工具不读取玩家等级，因此不自动计入，也不计算叠加幅度。
- **准入另算：**Alioth、Shinrarta Dezhra、Summerland、Sol、Beta Hydri、CD-43 11917 均涉及星系许可；相关舰船仍须满足购买军衔。折扣命中不代表已核验这些资格。
- **库存另算：**Wiki 提醒 Hamilton Gateway 的 Diamondback Explorer 缺货。工具只有在返回库存确实包含该船时才应用规则，不根据优惠名单推定有货。
- **Attilius Orbital：**30%模组优惠仅限表中指定商品，不适用于3级及以上模组或炮塔武器，不是全站模组通用优惠；20%舰船优惠也仅限指定船型。
- **过期促销不计入：**例如 Lembava 的23.5% FSD优惠、Onnes Gateway 的30%模组优惠、Torval 的40%采矿设备优惠，均位于已过期列表，不据历史社区目标奖励判定当前有效。
