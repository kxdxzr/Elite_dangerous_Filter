# Agent CLI (headless JSON interface) / Agent CLI（headless JSON 接口）

## English

Development source only; existing release executables are unchanged.

The individual scripts in `src/agent_tools/` expose the GUI's search core as one-shot JSON tools. Choose the script by task, for example `search_pve.py`, `search_hge.py`, or `read_current_system.py`. Each accepts its argument object on stdin and prints one JSON response. Run a script with `--describe` to inspect its arguments. The shared implementation and the optional compatibility dispatcher `agent_cli.py` are also in that folder; no GUI or Tk import is required.

```powershell
'{"reference":"Sol","radius":300,"material":"federal"}' | python src/agent_tools/search_hge.py
python src/agent_tools/search_hge.py --describe
'{}' | python src/agent_tools/read_current_system.py
```

To specify limits or a request ID, send `{"arguments": {...}, "limits": {...}, "request_id": "..."}` instead. `--input FILE` and `--pretty` are also supported. The dispatcher below remains available for option discovery and compatibility.

### Calling convention

Send a UTF-8 JSON request on stdin, or pass `--input FILE` (`--pretty` indents the output). Exit codes: `0` when a response was produced (`ok`, `partial` or `cancelled`), `1` for `invalid_request`/`unknown_operation`, `2` for `operation_failed`.

```powershell
'{"interface_version":"1","operation":"capabilities"}' | & 'C:/software/anaconda/python.exe' src/agent_tools/agent_cli.py
```

A request is an object with `interface_version` (currently `"1"`), `operation`, optional `arguments` and optional `limits`:

- `limits.return_rows` — rows returned, default 200, maximum 10000 (extra rows are truncated and flagged via `coverage.truncated`).
- `limits.deadline_seconds` — optional cooperative stop deadline (0 < seconds <= 86400), not a hard process timeout. Some operations cannot interrupt an in-flight request; partial verified results may be returned.
- `limits.fields` — optional non-empty list of row keys for the projection.

A response carries `interface_version`, `application_version`, `operation`, `request_id`, `status`, `coverage`, `timings`, plus operation-specific fields such as `results`, `criteria`, `notes`, `corrections`, `errors`, `warnings`. `status` is `ok` (candidate pages exhausted or requested count reached), `partial` (coverage incomplete — this does **not** mean nothing exists), `cancelled` (deadline or stop signal), or `error` with `error.code` of `invalid_request`, `unknown_operation` or `operation_failed` (`retryable` and `exception_type` included; URLError/timeout/connection failures are retryable). Invalid requests never issue network calls. Non-finite floats are reported as `null`.

### Operations

Offline: `capabilities` (protocol/app version, operations, limits), `describe` (one operation's argument schema), `options` (field/operator/enum discovery: `system_fields`, `station_fields`, `colonisation_*`, `hge_*`, `powerplay_powers`, `rare_goods_sources`, `engineer_destinations`, `engineer_module_specs`, and more), `read_current_system` (last confirmed position from local Journal files — the same source as the GUI "use current system" button, no network needed).

Network (Spansh unless noted): `resolve_system`, `search_systems`, `search_stations`, `search_pve`, `search_hge`, `search_engineer_shopping`, `search_full_outfitting` (local snapshot by default; `refresh: true` rebuilds it over the network; a missing snapshot also triggers a rebuild), `search_waypoint_route`, `search_colonisation`, `search_rare_goods`, `search_midpoint`.

Use `describe` for each operation's exact argument schema. Notable semantics:

- `search_hge`: `population`/`freshness` accept either the option label or a number equal to one option's bound (e.g. `freshness: 168`); see `options` group `hge_freshness_options`. Faction states come from system records, not live signal spawns.
- `search_engineer_shopping`: `purchases` is the list of everything to buy (AND semantics, not OR); each entry is `{name, class?, rating?, weapon_mode?, discounted? (default true), fresh_days?}`. `destination` accepts an `engineer_destinations` entry or a system name.
- `search_waypoint_route`: optimizes over the queried candidate pools only, never a galaxy-wide optimum; per-group pool completeness is in `coverage.pools`, and "no route over complete pools" is still `ok`.
- `search_rare_goods`: `reference` must be one of the 138 rare-commodity source systems (case-insensitive; see `rare_goods_sources`), otherwise the request is rejected unless `allow_unknown_source` is set.
- `search_full_outfitting`: filters the saved local snapshot; a result proves only that the snapshot's station list was filtered, not live stock. `refresh: true` rebuilds the snapshot first (long-running, network).
- `search_pve`: `coverage` distinguishes `confirmed_res` from ring-inferred `inferred_res`; RES evidence is labelled per row.

Machine-readable keys and error codes are English; human-facing `notes` follow the search core and are currently Chinese.

## 中文

仅在开发源码中；已发布 EXE 未被替换。

`src/agent_tools/` 按功能提供独立的一次性 JSON 入口，如 `search_pve.py`、`search_hge.py`、`read_current_system.py`。stdin 直接传该功能的参数对象，stdout 返回统一 JSON；用 `--describe` 查看参数。公共代码与兼容用的 `agent_cli.py` 分发器也在该子目录，不导入 GUI/Tk。

例如：`'{"reference":"Sol","radius":300,"material":"federal"}' | python src/agent_tools/search_hge.py`；读取位置用 `'{}' | python src/agent_tools/read_current_system.py`。需要限制或请求 ID 时传 `{"arguments": {...}, "limits": {...}, "request_id": "..."}`。也支持 `--input 文件` 和 `--pretty`。

### 调用约定

stdin 传 UTF-8 JSON 请求，或用 `--input 文件`（`--pretty` 缩进输出）。退出码：`0` 表示有响应（`ok`/`partial`/`cancelled`），`1` 表示 `invalid_request`/`unknown_operation`，`2` 表示 `operation_failed`。

请求为对象，含 `interface_version`（当前 `"1"`）、`operation`、可选 `arguments` 与 `limits`：

- `limits.return_rows` — 返回行数，默认 200，上限 10000（超出被截断并在 `coverage.truncated` 标注）。
- `limits.deadline_seconds` — 可选协作式停止时限（0 < 秒 <= 86400），不是强制进程超时；部分操作无法中断正在进行的请求，也可能返回已核实的部分结果。
- `limits.fields` — 可选、非空的行字段投影列表。

响应包含 `interface_version`、`application_version`、`operation`、`request_id`、`status`、`coverage`、`timings`，以及各操作自有字段如 `results`、`criteria`、`notes`、`corrections`、`errors`、`warnings`。`status`：`ok`（候选分页取完或达到所需结果数）、`partial`（覆盖不完整，**不代表没有更多命中**）、`cancelled`（deadline/停止信号）、`error`（`error.code` 为 `invalid_request`、`unknown_operation` 或 `operation_failed`，附 `retryable` 与 `exception_type`；URLError/超时/连接类错误可重试）。无效请求不会发起网络调用。非有限浮点数统一输出为 `null`。

### 操作清单

离线：`capabilities`（协议/应用版本、操作、限额）、`describe`（单操作参数 schema）、`options`（字段/算子/枚举发现：`system_fields`、`station_fields`、`colonisation_*`、`hge_*`、`powerplay_powers`、`rare_goods_sources`、`engineer_destinations`、`engineer_module_specs` 等）、`read_current_system`（读本机 Journal 最近确认位置——与 GUI"使用当前星系"同源，无需联网）。

需网络（除注明外均为 Spansh）：`resolve_system`、`search_systems`、`search_stations`、`search_pve`、`search_hge`、`search_engineer_shopping`、`search_full_outfitting`（默认读本地快照；`refresh: true` 才联网重建）、`search_waypoint_route`、`search_colonisation`、`search_rare_goods`、`search_midpoint`。

各操作的精确参数用 `describe` 查看。要点：

- `search_hge`：`population`/`freshness` 可传选项标签，也可传等于某选项边界的数字（如 `freshness: 168`），见 `options` 组 `hge_freshness_options`。派系状态取自星系记录，不是实时信号刷点。
- `search_engineer_shopping`：`purchases` 是要买齐的全部商品（"与"关系，不是"或"）；每项为 `{name, class?, rating?, weapon_mode?, discounted?（默认 true）, fresh_days?}`；`destination` 可用 `engineer_destinations` 条目或星系名。
- `search_waypoint_route`：只在已查询的候选池内优化，不是全银河最优；各组候选池完整性见 `coverage.pools`，池完整但无路仍返回 `ok`。
- `search_rare_goods`：`reference` 必须是 138 个稀有商品来源星系之一（大小写不敏感，见 `rare_goods_sources`），否则拒绝请求，除非设置 `allow_unknown_source`。
- `search_full_outfitting`：筛选已保存的本地快照；结果只证明"快照名单已筛完"，不证明实时库存。`refresh: true` 会先重建快照（耗时长、需网络）。
- `search_pve`：`coverage` 区分 `confirmed_res`（明确 RES）与星环推定的 `inferred_res`；逐行标注地点证据。

机器字段与错误码为英文；人类可读 `notes` 沿用搜索核心文本，目前为中文。
