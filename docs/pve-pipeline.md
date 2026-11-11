# PvE detail pipeline / 海盗任务详情流水线

## English

Development source only; not part of the already published v0.1.5-beta EXE.

### Behavior

- Radius `0` remains unlimited. All locally eligible catalogue pairs are processed; batch size never limits search coverage.
- Existing radius, site, bulk-controller and bulk-Power prefilters remain. Mission candidates then use source-first detail verification: only survivors proceed to target-detail loading. Faction minima are checked before target requests.
- At most four detail-loader workers operate on the current small batch (up to eight pairs). A shared per-query, case-insensitive cache reuses successful records and errors across batches and source/target roles. Duplicate in-flight names are submitted only once. Spansh's existing process-wide HTTP governor is unchanged.
- No BGS detail load is added when no dynamic BGS/station filter needs it. Independent ring verification may still need HTTP. `detail_requests` counts detail-loader invocations, not raw HTTP requests; persistent cache hits can avoid HTTP entirely.
- In mission mode, fully checked RES/ring-inferred rows can stream before later batches finish when no target-ring-distance restriction remains. The GUI appends at most 200 rows per display callback and labels them as partial. Final results are reconciled and sorted using the existing ranking.
- Unknown sites and target-ring-distance restrictions retain their existing ring verification before those rows are emitted. CNB fallback waits for a complete query with no RES/unknown matches; cancellation or incomplete data cannot establish absence.
- Expanded mode retains final merging and source annotation before its callback. RES-only mode also retains its existing final-result path. Neither is presented as fully streamed by this change.
- Cancellation stops submitting further detail work, retains already verified results, and waits for already running calls under their existing timeouts. Failures remain explicit rather than becoming empty, complete searches.

### Reproducible evidence

```text
python scripts/benchmark_pve_pipeline.py --baseline v0.1.5-beta --count 100 --delay-ms 2
```

This developer-only benchmark requires Git history. It runs the actual old and new search implementations on the same offline records, including systems over 100,000 ly away with radius `0`. The optional delay is artificial, not measured Internet latency. It checks exact final-row equality, complete coverage and detail-loader call counts.

| Fixed case | Old detail loads | New detail loads | Loads started before first visible result |
| --- | ---: | ---: | --- |
| 90% of sources fail the faction minimum | 200 | 110 | 200 → 9 |
| Every source and target passes | 200 | 200 | 200 → 16 |
| No dynamic detail conditions | 0 | 0 | 0 → 0 |

These are fixture-specific results, not galaxy-wide speed claims. When all candidates pass, no calls are saved and batching can add scheduling overhead. The benefit is fewer unnecessary target loads when sources fail, and earlier usable results. Actual overall speed depends on filtering, caches, upstream throttling and response times.

Tests cover unlimited coverage, shared/case-insensitive identities, no unnecessary loads, cancellation, delayed CNB fallback, ring restrictions, snapshot isolation, final sorting, and GUI rows appearing before the worker returns without duplication.

## 中文

此优化仅在开发源码，未替换已发布的 v0.1.5-beta EXE。

- 不限距离仍处理全部符合本地条件的配对，不用批次大小偷偷限制覆盖。
- 先核验来源，再查询通过者所需的目标详情；来源派系数量不符时不查目标。
- 复用同次查询的星系资料，忽略名称大小写去重，跨批次、跨来源／目标身份共用。最多四个详情工作线程，当前批次最多八条配对；现有 Spansh 总限速不变。
- 不需要动态条件时不增加 BGS 详情查询。星环核验仍可按原规则联网；详情加载次数不等同于实际 HTTP 次数，持久缓存也可能直接命中。
- 任务模式在没有待验证的目标星环距离限制时，核实 RES／星环推定行后立即发送；GUI 每次最多追加 200 行，结束后按原规则统一排序。未知地点和星环距离条件须先完成相应核验。
- CNB 仍需完整查询确认没有 RES／未知命中后才能兜底；停止或错误不能解释成没有 RES。扩展模式须先完成合并和来源补全，RES-only 模式也保留原有最终结果流程，不冒充全面增量显示。
- 固定的不限距离 100 条候选对比中，90% 来源被淘汰时，详情加载由 200 次降为 110 次，首条结果在第 9 次而非第 200 次加载后可用；全部合格时仍为 200 次，但第 16 次后即可显示首批。两种情况下最终行均与旧版完全相同；无动态条件均为零次详情加载。
- 人为延迟只用于离线实验，不当作真实联网提速。全部合格时仍有少量调度开销；实际收益取决于条件、缓存和上游响应。
