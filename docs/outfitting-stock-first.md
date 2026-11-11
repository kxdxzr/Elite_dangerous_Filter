# Stock-first discount verification

## English

Development-source optimization; the published v0.1.5-beta assets are unchanged.

### Scope and behavior

The GUI normally discovers a broad **non-discount** inventory snapshot, then filters that snapshot locally. This change does not add network requests to local filtering or promise a large speedup when switching options on an existing snapshot. It primarily optimizes the lower-level `full_outfitting.search` path when a public discount is required and system Power evidence must be fetched. Shared system-context lookup also serves result metadata completion during snapshot discovery.

- Before fetching missing Power evidence, perform a stock-only preflight. Definite missing stock, invalid catalogue requirements or failed non-discount conditions cannot be repaired by Power data, so those stations skip the lookup.
- The preflight performs no item pricing and **never returns a final match**. Plausible stations still undergo full public-discount checks; missing Power information is never assumed to be Li Yong-Rui control or an eligible Power state.
- Ambiguous identities remain distinct from definite missing stock. Nearly complete inventories retain the existing exact-market/system/station EDSM identity check, under the original discount and evidence gates. No cross-station inventory merge or weaker specification matching is introduced.
- Existing complete Power evidence and named public-discount stations retain their original direct-check path, avoiding an unnecessary extra stock walk.
- Discount enrichment and display metadata share a query-local context cache. Keys preserve name punctuation, ignore surrounding whitespace/case and include a supplied system id64. Conflicting IDs cannot borrow one another's evidence.
- Empty and failed contexts are retained only for the current query, avoiding repeated lookups for sibling stations. They remain unknown, not affirmative discount evidence; a subsequent query can retry.
- Inventory timestamps, original inventory records, result limits and full checks for successful rows remain unchanged. Rejected-row diagnostics can now expose stock failures before any discount background has been fetched.

### Validation

```text
python scripts/benchmark_outfitting_stock_first.py --baseline v0.1.5-beta --count 100
```

The offline comparison runs the actual old and new verification code against fixed candidates and checks exact verified-row and result-CSV equality. The candidate transport is a fixture, not a measurement of live Spansh performance or server prefilter selectivity.

| Fixed case | Old system lookups | New system lookups |
| --- | ---: | ---: |
| 100 distinct systems, 90 candidates missing stock | 100 | 10 |
| 100 distinct systems, all stock complete | 100 | 100 |
| 100 stations in one system, all stock complete | 1 | 1 |

The original implementation already reused exact-name system contexts; normalized identity keys and cached negative results strengthen that reuse. If all stations are plausible, calls need not decrease, and stock preflight can add local CPU work. No general speed multiplier is claimed.

Regression tests cover stock rejection before HTTP, false/unknown discounts, same-system cache reuse, failed-context retry boundaries, name/ID isolation, no speculative preflight hits, and real ambiguous stock resolved through exact-station EDSM evidence.

## 中文

此项仅在开发源码，未替换已发布的 v0.1.5-beta。

- 当前界面主要建立无折扣库存快照，再本地筛选；这项不会新增本地筛选的联网，也不承诺切换已有快照条件时显著提速。主要优化需要补查 Power 的底层折扣搜索，并统一快照建立时结果资料的星系背景缓存。
- 补查 Power 前先做不计价的库存预检；明确缺货或其他必需条件失败时跳过补查。预检绝不直接产生合格结果，可能通过的站仍完整核验折扣，不猜测缺失 Power／状态。
- 模糊身份不等于明确缺货，原同市场、同星系、同站点的 EDSM 补证和折扣限制保留，不跨站拼库存。已有完整 Power 信息或具名公共折扣站保留直接判定，避免无谓增加库存遍历。
- 星系背景在同次查询内复用：名称忽略首尾空白和大小写但保留标点；有 id64 时也必须一致。空响应和失败只在本次查询暂存，避免同星系多站重复查询，下次查询可重试。
- 固定 100 个不同星系候选、90 个明确缺货的实验中，背景查询由 100 次降到 10 次，最终合格行与结果 CSV 完全相同；全部齐货时仍是 100 次，同星系 100 站仍只需一次。后者原本就有基本缓存，此次加强身份及失败缓存，不冒充新获得的百倍提速。
- 离线候选响应不代表真实上游分页或过滤效果；全部候选都可能合格时，预检会增加少量本地计算，不能保证总体耗时更短。库存时间及同站身份规则保持不变；拒绝诊断可能更早展示缺货原因。
