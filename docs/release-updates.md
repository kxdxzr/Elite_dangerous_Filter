# GitHub Release 检测与自动替换（开发源码）

此功能尚未打包或发布，已发布的 v0.1.4-r1 不会因此获得新功能。

## 使用

- Windows EXE 交互启动约 3 秒后，后台检查一次项目 GitHub 的最新正式 Release；源码运行不自动检查。主窗口右侧“检查更新”可手动重试。
- 自动检查无新版或失败不弹窗；手动检查会提示最新状态或网络错误。检查与下载不阻塞查询，不需 token。
- **第一次确认**后下载并校验 EXE 的大小及 GitHub API 提供的 SHA256。未通过校验、下载失败、磁盘不足、目录不可写或助手无法启动，均不退出或改动当前 EXE。
- 下载完成后**第二次确认**：保存当前条件和工具设置，再退出、替换 EXE、自动重启。进行中的查询将中断，结果及内存断点不保证恢复。会话保存失败时不允许替换。
- 不写入／迁移用户数据目录，不申请管理员权限。建议升级前备份 `%LOCALAPPDATA%\EliteDangerousFilter`。
- 源码运行、缺少 Windows 附件或 API 的 SHA256 校验证据时，只提供本项目发布页手动下载，不降低校验要求。PowerShell 被策略禁止或程序目录不可写时，也可手动下载替换。

## 替换与恢复

- 临时更新目录 `.edf-update-*` 位于旧 EXE 旁，确保同卷替换；包含下载文件、助手脚本、配置及日志。准备成功并不等于授权，只有保存设置成功且确认退出才发送替换许可。
- 助手等待原进程真正退出（最多 60 秒），替换前再次校验 SHA256。文件仍被其他进程占用时重试最多 30 秒；超时不强制结束其他程序。
- 使用 Windows 文件替换 API，旧程序保存在该目录的 `previous.exe`，不覆盖此前备份。替换失败时保留原文件；启动调用失败时恢复旧文件并尝试启动旧程序。
- **回滚不是新版本健康检测**：启动调用成功后发生的崩溃／功能问题不能自动识别。必要时退出新版，手动将 `previous.exe` 恢复至原 EXE 路径。
- 后台助手失败会显示英文错误框，并写入更新目录的 `update.log`。未授权的助手最多等待 5 分钟后退出。取消及成功后的临时目录不会自动递归清理；确认不再需要回退后可手动删除对应更新目录。
- 哈希来自 GitHub 的 HTTPS Release 元数据，不是代码签名。更新程序仍可能触发 SmartScreen；不会绕过 Windows 安全提示或企业策略。

## 版本与网络边界

- 使用 GitHub REST `GET /repos/kxdxzr/Elite_dangerous_Filter/releases/latest`，排除草稿和预发布；版本按数字比较，项目 `-rN` 是正式修订：`0.1.4 < 0.1.4-r1 < 0.1.4-r2 < 0.1.5`。不自动降级。
- 只比较版本，不检测同版本替换附件；同名版本换包不触发升级。
- 检查超时 12 秒、元数据上限 2 MiB；下载读取超时 30 秒、整体循环上限约 10 分钟、文件上限 256 MiB。没有自动重试风暴或持久缓存；重复点击不并发检查／下载。
- 下载起始地址固定为本项目 Release 的 `EliteDangerousFilter.exe`，允许 GitHub 正常 CDN 重定向；最终大小及 SHA256 必须与 Release 元数据一致。
- Tk 操作通过主线程队列；EXE 冒烟与会话测试不启动联网检查。

## 验证

离线测试覆盖版本、损坏响应、校验缺失／失败、超时、权限、重复点击、确认取消、保存拒绝、线程分发及关闭保护。Windows 助手集成测试使用测试目录副本，验证等待进程退出、无许可不替换、真实文件替换与备份、替换前二次校验、新程序启动调用失败后的恢复；不替换正在使用的应用或已发布附件。真实最终打包 EXE 的端到端升级、可见弹窗与 SmartScreen 仍需打包后验收。

## English

Development source only; not included in the published v0.1.4-r1. Interactive Windows builds check for a stable GitHub release once at startup. The first confirmation downloads and verifies size and GitHub's SHA256 metadata while the app continues running. A second confirmation saves conditions, exits, replaces and restarts. Save failure prevents authorization. A separate PowerShell helper waits for the old process, rechecks SHA256 and uses Windows file replacement with a unique old-EXE backup. Replacement errors retain the old EXE; launch-call failures restore it. This is not post-launch health monitoring: later crashes require manual rollback. Local user data is preserved; query results/checkpoints are not guaranteed to survive. Source runs or missing verification metadata fall back to the release page. No privilege elevation, forced process termination or security-warning bypass. Staging directories, backups and logs remain beside the EXE for manual recovery/cleanup.
