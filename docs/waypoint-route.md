# 多目标途经规划（开发版）

从 A 到 B，为几类独立要求各寻找至少一个符合条件的地点。先最少额外停靠，再在相同停靠数中选择几何总路程最短的方案。无需自建服务器或账号。

## 使用

1. 主界面选择星系或站点模式，编辑一组条件。
2. 打开“多目标途经规划”，点击“从主界面添加要求组”。条件会复制为独立快照；可以回主界面继续编辑，再添加下一组。
3. 添加 1～6 组要求，输入起终点、最大额外路程、每组候选数和最多页数，然后规划路线。
4. 结果列出访问顺序、每站完成的要求编号、分段距离及记录更新时间。“匹配依据”可以查看本次查询条件和所选地点的原始证据。

组内沿用主界面的条件语义：独立行是 AND，多选行可能是 OR。想买齐两种装备，请分别添加两行装备条件，不能用一行多选来表达“全部都有”。站点组中的条件必须在同一站成立，不会合并邻站库存。模块尺寸、评级、挂载和时效按原筛选器规则核对。

## 计数和距离

- 一站完成多组要求只停一次；同星系两个不同站算两次。星系级目标是途经点，不表示必须进站。
- 到一个站也视为经过该星系，可同时完成该星系已有证据支持的要求。
- 起点和终点仅输入星系名。其星系级要求若有候选证据，可免费完成；站点级要求仍需实际停靠，不能假设起终点已经进了某个站。
- 最大额外路程 = 所有途经段的直线距离总和 − A 到 B 的直线距离。零表示不能绕路，不是“不限”。
- 同星系不同站之间的星际几何距离为零，但仍计作两次停靠。不估算超巡、降落、办事时间。

## 候选范围与保证

默认每组最多取得 12 个候选、5 页。每组先加上安全的起终点距离界限，并在消耗候选额度前检查单点绕路下界。候选中已有明确字段支持另一组要求时，可交叉复核，发现一个地点完成多组要求的机会；缺失字段不能当作匹配，详细条件必须有对应核实结果。

路线范围另按 `|A-P| + |P-B| ≤ L` 收紧，其中 `L = |A-B| + 最大额外路程`。其可行域为椭球，向服务器下推中点半径 `L/2` 的安全包围球；星系模式还能下推椭球的坐标包围盒。坐标几何预筛在昂贵详细核验之前执行，最终仍核对原始条件和整条多站路线的总预算。普通“distance”字段依赖原参考点时不替换其参考点；已有更小的查询球也不扩大。边界有浮点容差。

这会改变受限分页时的候选顺序／内容，不保证与旧版首批候选完全一致；它不以缩减结果数或放松要求来换取速度。完整扫描固定数据时应保留相同可行结果。

求解器在已收集候选集内按“停靠数、几何距离”严格排序。它**不保证全银河绝对最优**：每组结果／页数限制及上游覆盖可能遗漏更好的组合，网页排序也不等同于路线最优排序。可以增大每组候选数（最多 30）或页数后重查。

没有完整路线时会显示未找到候选的要求编号，或说明现有组合不符合绕路上限；不能把它理解为游戏中绝对不存在。停止和查询异常不会将未完成的要求当作完成，也不会生成冒充完整的部分路线。

这是地点级规划，**不是逐跳航线**，不验证跃迁可达性、燃料、中子跳、许可或实时库存。使用前在游戏中核对。结果只属于该次查询快照；设置和要求组随会话保存，结果本身不保存。

## English summary

Capture 1–6 independent system/station requirement groups from the main editor. The planner minimizes extra stops first, then geometric distance, subject to a maximum detour over the direct A–B distance. Multiple requirements may share one verified station; different stations in one system count separately. System-level endpoint requirements may be satisfied without extra stops, but station visits at endpoints still count.

The optimum is relative to the bounded candidate pool only, not the entire galaxy. Default limits are 12 candidates and 5 pages per group. Explicit returned evidence can be cross-checked across groups; unknown fields never establish coverage. This is not fuel/jump/permit routing, live stock or travel-time prediction. Settings persist; results are query snapshots.
