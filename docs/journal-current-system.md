# Use current system / 使用当前星系

## English

Development source only; existing release executables are unchanged.

Click **Use current system** beside an origin/reference-system input to fill it from local Elite Dangerous Journal files. This does not run a search, change a destination or enable continuous tracking. No EDMC, account login or network is needed to read the position.

Available in main-window distance conditions (including shared condition editors), engineer shopping, waypoint planning, PvE, HGE, full outfitting, colony candidates, carrier parking and midpoint system A. The rare-goods source selector also has the button, but accepts the position only when it belongs to the tool's supported source catalogue; otherwise the previous selection is retained.

The default folder is `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous`. If missing, clicking opens a folder picker. **Right-click the button** to select a different Journal folder at any time. The chosen directory is shared by the application's windows for this run, not saved across restarts. Cancelling selection leaves inputs unchanged. A present but empty/inaccessible folder produces an error; right-click to choose another.

Hover over the button for instructions. After a successful fill, the tooltip includes the system, Journal timestamp and source filename. This is the **last confirmed Journal position**, not live telemetry; an old/offline Journal can describe an old location. There is no startup scan or automatic log upload. Files are read only, in a background worker; edits made while reading and closed windows are not overwritten by late results.

Only `Location`, `FSDJump` and `CarrierJump` confirm position. `StartJump` and route targets do not. Select the most recently active Journal file by modification time, then read numbered parts of that session backwards. A new session with no position never borrows one from an older session. This is a local file-selection policy, not commander authentication: copied logs with changed modification times can affect selection; choose a suitable directory when several commanders' logs are mixed.

Reading is bounded to 5,000 matching files, 16 MiB total scanned bytes and 1 MiB per line. Incomplete final lines wait for a future click after completion. Malformed JSON is skipped; invalid fields in the latest recognized position event are an error rather than permission to use an older position. Errors preserve the original input. No position is invented when no complete record is available.

Regression coverage uses synthetic Journals and GUI mocks, not private player logs or live-game timing measurements.

## 中文

本功能仅在开发源码中，已发布 EXE 未被替换。

点击起点／参考星系旁的 **使用当前星系**，从本机 Journal 填入日志最近确认的所在地。不自动搜索、不改终点、不持续跟随；读取位置无需 EDMC、登录或联网。

覆盖主界面距离条件（含共用条件编辑器）、工程师采购、多目标途经、PvE、HGE、满配件、殖民、航母车位和中点工具 A 星系。稀有商品来源选择器也提供按钮，但当前位置必须属于支持的来源清单，否则保留原选择。

默认目录为 `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous`。目录不存在时点击会打开选择器；**右键按钮可随时换 Journal 目录**。选择在本次程序运行的各窗口间共用，重启不保存。取消不改输入；已有目录为空或无权限时提示错误，可右键换目录。

悬停查看用法；填入成功后悬停可查看星系、原始日志时间和文件名。这不是实时遥测，离线或旧日志可能只反映过去位置。不启动即扫描、不上传日志，只读文件；后台读取期间手动修改输入或关闭窗口，晚到结果不会覆盖。

仅采用 Location、FSDJump、CarrierJump，不拿 StartJump 或路线目的地当作当前位置。按修改时间选择最新活动文件，仅回查同会话分卷，新会话无位置不借用旧会话。修改过时间的拷贝或多指挥官混合目录可能影响选择，这不是账号身份认证。

限制匹配文件数 5000、总扫描 16 MiB、单行 1 MiB。未完成尾行须等待写完后再点击；坏 JSON 可跳过，但最新位置事件字段无效时不退回更旧好值。所有失败保留原输入，无记录不猜位置。

回归使用合成日志和 GUI 模拟，不读取私人游戏日志，也不宣称验证了游戏内实时更新频率。
