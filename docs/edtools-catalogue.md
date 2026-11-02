# EDTools 本地清单与更新

开发版随程序附带完整的 EDTools 配对清单 `pve.json` 和地点清单 `res.json`，合并存为 `assets/edtools/default.json`。当前默认文件约 5.45 MiB。首次使用无须为取得这两份清单联网；星系坐标、动态派系、势力、站点和星环核验仍可能联网。

## 正常查询

- 优先使用用户更新过的完整清单，没有有效用户清单时使用内置默认清单。
- 所有半径统一使用全量 JSON 在本地生成候选，不再按半径重新抓取 EDTools 网页。半径、派系筛选及同站核验语义保持不变。
- 清单不会因一小时 TTL 到期而自动重新下载。“刷新动态资料并查询”只强制刷新动态查询，不偷偷更新 EDTools。
- 仍支持手动导入旧 PvE HTML 网页；“使用 EDTools 清单”可切回本地完整清单。
- 同一次查询固定使用同一代配对／地点清单，更新不会改变正在运行的查询，包括扩展模式的任务结果与补充 RES 结果。

## 自动检查与手动更新

进入海盗任务工具时，后台检查清单是否变化，不阻塞现有查询。自动检查最多每 24 小时一次（最近成功获取清单也计入）；失败也记录检查时间，避免频繁重新打开窗口反复请求。手动“检查 EDTools 更新”可立即重查。

优先发送 `If-None-Match`；没有 ETag 时使用 `If-Modified-Since`。未变化的资源可以只返回 HTTP 304；服务器未提供条件请求验证信息或返回 200 时，则下载并逐条验证，再比较规范化内容 SHA256。JSON 空白／字典键顺序变化不算数据更新。

2026-11-02 实测两份资源都返回 Last-Modified，条件 GET 返回 304；这只证明本次接口行为，不保证服务器未来一直支持。RES 清单的 Last-Modified 与配对清单不同，不能据此宣称 EDTools 所有数据更新频率都很低。

有变化会暂存一套完整清单，提示用户确认，**不会自动替换正在使用的版本**。确认后直接安装暂存版本，不重复下载；点“更新 EDTools 清单”也可主动下载安装。拒绝后旧清单保持不变，暂存版本可在以后确认使用。

两份资源都完整下载、逐条校验成功后，才通过单个文件原子替换用户清单。下载、解析或写入失败保留原文件；检查失败不表示“没有更新”。本地来源和获取时间在窗口显示，获取时间不是上游记录更新时间。

## 文件与发布

用户目录文件为 `edtools_catalogue_v1.json`、`edtools_catalogue_pending_v1.json`、`edtools_catalogue_check_v1.json`。EXE 使用 `%LOCALAPPDATA%\EliteDangerousFilter`；源码使用项目 `data/`，也遵守 `ELITE_FILTER_DATA_DIR`。

内置默认数据只读，用户更新不会修改 EXE 或源码内置副本。发布构建通过 spec 打包默认文件，不在构建时联网获取数据。维护者需要更新内置基线时，显式运行 `python scripts/update_bundled_edtools.py`。默认数据包含来源、获取时间、原始 Last-Modified 与内容摘要；第三方数据不因随软件附带而被重新授权为项目代码许可证。

如果用户副本损坏则回到内置默认清单；若两份默认／用户副本都不可用，正常加载可尝试重新下载两份清单，失败会报告错误，不返回冒充完整的空清单。

## English

The development build bundles a full EDTools pair/site baseline. A valid user-updated snapshot takes precedence. Normal searches use local JSON at all radii; dynamic Spansh data retains separate short-lived caching. Queries pin a snapshot generation.

Opening the PvE tool starts a background conditional update check, with a 24-hour automatic-check interval and manual bypass. Changed, validated data is staged and installed only after confirmation. Both resources are atomically replaced together; failures retain the old version. Retrieval time is not upstream record freshness. The bundled file remains unchanged by user updates.
