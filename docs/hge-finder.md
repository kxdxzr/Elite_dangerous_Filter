# HGE 可能星系查找器 / HGE candidate system finder

**仅开发源码，不包含在 v0.1.4-r1 修订版中。 / Development source only; not included in v0.1.4-r1.**

## 用途与口径

从主界面的工具区打开 **HGE 可能星系查找器**。这是依据用户提供规则查找可能星系的工具，不是实时 HGE 信号扫描器，不保证材料掉落。规则尚不是独立验证过的官方掉落表。

按照本工具约定，使用**同一个控制派系的阵营和当前状态**：在 Spansh 星系记录的 `minor_faction_presences` 中按 `controlling_minor_faction` 精确核对派系名称，再读取该项 `allegiance`、`state` 和 `active_states`。不拼接不同小派系的条件，不使用其他小派系、待处理或恢复中的状态，也不直接用顶层星系阵营替代控制派系阵营。重复控制派系记录互相矛盾、控制派系不明或状态缺失时不命中。

真实 HGE 信号点可能属于别的派系，因此这个约定可能漏掉游戏内有效地点，也可能返回没有 HGE 的星系；到达后必须在游戏中检查。

| 材料选择 | 控制派系阵营 | 当前状态（任选其一） |
| --- | --- | --- |
| Core Dynamics Composites / Proprietary Composites | Federation | Election / None |
| Military Grade Alloys / Military Supercapacitors | Independent / Alliance | War / Civil War |
| Improvised Components | Independent / Alliance | Civil Unrest |
| Imperial Shielding | Empire | Election / None |
| Pharmaceutical Isolators | Independent / Alliance | Outbreak |
| Proto Heat Radiators / Proto Light Alloys | Independent / Alliance | Boom |
| Proto Radiolic Alloys（按用户勘误） | Independent / Alliance | Boom |

`None` 必须有明确的无状态记录；缺失字段、空列表不算 None。若当前存在其他活动状态，不将同时返回的 None 当作满足“无状态”。选择“全部材料”时任一规则匹配即可，并列出全部匹配材料；并非要求所有材料都可能掉落。

## 操作

- 默认参考星系 Sol，半径 50 ly；半径必须大于零，避免误发全银河扫描。
- 人口下限下拉：不限、人口大于 0、至少 100 万、1000 万、1 亿、10 亿、100 亿。默认人口大于 0；这是用户筛选条件，不是新增的掉落规则。
- 星系记录时效下拉：近 1、3、6、12、24、48、72 小时，近 7 天，不限；默认近 24 小时。
- **可选“目标星系存在人造材料商人”**，默认不勾选。勾选后，在 HGE 规则等条件通过后，重新查询目标星系的站点，要求同一座站点明确属于该星系且 `material_trader = Manufactured`；Raw、Encoded、未知类型或邻近星系的商人不算。若星系数字身份同时可用，也需一致。只需至少一座符合的站点，不要求站点与 HGE 控制派系相同。
- 启用商人条件时，结果增加“人造材料商人站点”证据列；此选项随会话保存，旧会话默认关闭。未勾选时不增加商人网络请求，也不声称该星系一定没有商人。商人资料不明、核验页数耗尽或异常时，不计入匹配结果，且不占用结果名额；网络暂时失败仍保留此前已核实的部分结果。时效下拉仍针对星系记录，不对商人资料另作同一时效的保证。
- 默认最多 100 个结果、25 页。只在完成阵营、状态、人口及时效核实后计入结果数；页数上限仍可能造成不完整。
- 结果显示星系、距离、可能材料、控制派系、阵营、匹配当前状态、人口、记录更新时间、查询时记录年龄和许可提示。表头可排序；选中后点击“复制星系名”或双击复制。
- **不提供 CSV 导出，也不保存搜索结果。** 仅保存筛选设置，重新打开可恢复。
- 每次查询重新发起 Spansh 检索，不使用 HGE 结果缓存；沿用共享请求节流和有限重试。暂时网络异常或手动停止时保留本次已核实的部分结果，再点查询将重新获取候选，不跨查询续用旧结果。参数无效时保留旧显示。

## 时效边界

时效按**星系记录 `updated_at`** 判断，不代表控制派系状态有独立时间证据，更不代表信号生成或到期时间。限定时效时，缺失、非法、未来的时间不命中；“不限”明确放开这个限制。年龄是本次查询时的快照，不是不断刷新的在线状态。

同样，缺少记录不证明游戏内不存在 HGE。查询时效不表示服务器已实时采集当前状态；没有额外重新采集游戏日志或现场信号。

## English

**Optional: Target system has a Manufactured material trader**, disabled by default and saved in sessions. When enabled, HGE-rule survivors receive fresh station queries. A station must explicitly match the target system and `material_trader = Manufactured`; Raw, Encoded, unknown types and neighbouring-system traders do not qualify. If both numeric system identities are present, they must agree. One verified station is sufficient; its controlling faction need not match the HGE controller. The result adds a trader-station evidence column. Unknown/incomplete station evidence is not a hit and does not consume the result cap; transient network errors retain prior verified results. Disabling the checkbox makes no station requests and does not claim trader absence. The record-age dropdown still describes system records, not an additional freshness guarantee for trader data.

Open **HGE candidate system finder** from the main-window tools. Rules are user-supplied candidate heuristics, not an independently validated official drop table. Allegiance and current states must come from the **same named controlling faction** in a system's `minor_faction_presences`. Unrelated, pending and recovering states do not count. Missing or contradictory evidence is not a match. Explicit None is required; an empty list is not proof of no state.

The real HGE signal owner may differ from the controlling faction. This tool neither detects live signals nor guarantees materials, and may miss valid in-game sites. Verify in game.

The table above defines the seven rule groups. All materials means any matching group, not a requirement to match every material. Population and age are readonly dropdowns. Defaults: Sol, 50 ly, population above zero, record within 24 hours, at most 100 results and 25 pages. Available population minima: unrestricted, above zero, 1/10/100 million, 1/10 billion. Record-age choices: 1/3/6/12/24/48/72 hours, 7 days, unrestricted.

Record age is based on **system updated_at**, not an independently dated faction state or signal lifetime. Missing, invalid and future timestamps fail an enabled age restriction. Results are snapshots, not continuously refreshed state. Each search fetches new candidates; no HGE result cache, saved results or CSV export. Settings persist. Sorting and system-name copying are supported. Stops/transient errors retain verified partial results; the next search starts fresh. The common Spansh request governor still applies. No matches is not proof of in-game absence; page/result caps can leave the search incomplete.
