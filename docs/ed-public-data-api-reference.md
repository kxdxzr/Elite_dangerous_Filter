# Elite Dangerous 公开数据源与API速查

核对日期：**2026-10-20**。本文可作为独立文件分享，不依赖任何项目代码。

只整理公开游戏世界数据及公开数据集，不包含玩家账号接口、OAuth、Token、
个人日志读取、个人资产或账号同步。本文是社区开发参考，不是各服务方的官方文档。

**无需登录不等于允许无限抓取或自由再分发。** 接入前仍须核对服务方政策、
数据来源条款和当前接口。公开数据库可能陈旧、不完整；空结果不证明游戏中不存在。

## 1. 选哪个来源

| 来源 | 适合做什么 | 接入形式 | 主要限制 |
|---|---|---|---|
| Spansh | 星系、天体、站点、配件、舰船搜索 | 公开HTTPS查询 | 记录非实时，搜索接口并非都包含在OpenAPI文档中 |
| EDSM | 星系坐标、附近星系、天体及站点复核 | 公开GET查询 | 不同实体的ID含义不同，字段可能缺失 |
| EDTools | PvE来源配对、RES地点参考 | 公开JSON／HTML资源 | 不是实时任务板API |
| EDDN | 自建市场／库存数据库的持续增量 | 公开ZeroMQ消息订阅 | 不是REST查询，不提供历史补发／完整数据库 |
| EDCD/FDevIDs | 数字物品ID、符号和名称映射 | GitHub版本化CSV | 不是库存表，覆盖可能不完整 |
| Coriolis数据 | 舰船／模块参数、配船计算 | GitHub版本化JSON | 不是站点供应或实时价格 |
| Spansh／EDSM dumps | 大范围离线检索与统计 | 压缩数据集 | 数据量大，注意生成时间及全量／增量范围 |

本文所列公开查询在核对时无需玩家API key；不表示这些服务的其他个人接口也免授权。
**Inara网站的市场／站点搜索不是可调用的Inara公开数据库API**，因此不列入这里。
EDDB已停止服务，不建议把旧EDDB接口作为新工具依赖。

### 核对标记

- **实测**：项目开发中或本次核对成功调用过的只读接口。
- **文档**：维护者文档有记载，本次未调用该端点。
- **源码**：已有调用实现可参考，但本次没有重新执行。
- 示例JSON中的星系、站点及条件只演示请求，不保证未来返回结果相同。

## 2. Spansh

基础地址：`https://spansh.co.uk/api`。
服务方文档：<https://docs.spansh.co.uk/>。

本次读取到OpenAPI版本`3.1.1`，其中列出4个详情GET；下面的搜索、枚举另标依据，
不要将其全部当成已有稳定OpenAPI契约。直接访问`/api`根地址本次返回404，
并不表示下面的具体端点不可用。

### 2.1 详情接口

| 方法 | 路径 | 参数 | 核对 |
|---|---|---|---|
| GET | `/system/{id64}` | 游戏星系ID64 | 文档＋实测 |
| GET | `/body/{id64}` | 游戏天体ID64 | 文档 |
| GET | `/station/{marketId}` | 游戏市场ID | 文档＋实测 |
| GET | `/dump/{id64}` | 游戏星系ID64 | 文档 |

```http
GET https://spansh.co.uk/api/system/3932277478106
GET https://spansh.co.uk/api/station/128666762
```

上述两个实测详情响应顶层是`{"record": {...}}`。
`/dump`采用dump数据结构，不应假定与`/system`完全相同。

### 2.2 搜索接口（实测）

```text
POST https://spansh.co.uk/api/systems/search
POST https://spansh.co.uk/api/stations/search
POST https://spansh.co.uk/api/bodies/search
Content-Type: application/json
```

星系查询请求体：

```json
{
  "filters": {"name": {"value": "Sol"}},
  "size": 10,
  "page": 0
}
```

Sol周围50 ly内有配件服务的站点：

```json
{
  "filters": {
    "has_outfitting": {"value": true},
    "distance": {"min": 0, "max": 50}
  },
  "reference_system": "Sol",
  "sort": [{"distance": {"direction": "asc"}}],
  "size": 20,
  "page": 0
}
```

天体搜索请求体：

```json
{
  "filters": {"system_name": {"value": "Sol"}},
  "size": 10,
  "page": 0
}
```

搜索响应使用`results`列表，通常含`count`等辅助字段；不要与详情的`record`混淆。
`page`从0开始。名字过滤可能返回相似名称，必须在本地核对完整名称及ID，
不能直接把第一条当作精确命中。

### 2.3 配件规格过滤（实测）

```json
{
  "filters": {
    "modules": [
      {
        "name": {"value": ["Fuel Scoop"]},
        "class": {"value": [8]},
        "rating": {"value": ["A"]}
      }
    ]
  },
  "size": 20,
  "page": 0
}
```

需逐项核对真实规格、挂载与身份，不能根据分别存在“8级”和“A级”推导有8A。
多个模块组合条目曾用于同站AND预筛，最终仍需本地精确复核；不要把该语义推广到
所有枚举字段。新增过滤器应各自测试。

枚举辅助端点（源码依据）：

```text
GET https://spansh.co.uk/api/stations/field_values/modules
GET https://spansh.co.uk/api/{kind}/field_values/{field}
```

仅使用已确认支持的`kind/field`组合。`values`可能是列表或嵌套对象；
枚举名称列表不是所有尺寸、评级、挂载规格的完整证明。

### 2.4 常用字段及限制

| 内容 | 星系搜索 | 站点搜索 |
|---|---|---|
| 身份 | `name`、`id64` | `name`、`market_id`、`system_name`、`system_id64` |
| 坐标 | `x/y/z` | `system_x/system_y/system_z` |
| 许可 | `needs_permit` | 不保证提供，必要时补查所属星系 |
| Power | `controlling_power`、`power_state` | `system_controlling_power`、`system_power_state` |
| 库存 | 视响应而定 | `modules`、`ships`、`market` |
| 距离 | `distance`，ly | `distance`为ly，`distance_to_arrival`为Ls |
| 时间 | `updated_at`等 | 配件、市场、船厂可能分别有各自更新时间 |

- `system_power`等关联名单不等于控制Power。
- 一般Technology Broker服务不等于明确的Guardian经纪人。
- 航母可能移动；类型／名称证据也可能不完整。
- `count`可能封顶，分页期间数据也会变化；按稳定ID去重，并检测重复页／无新增数据。
- 命中条数、页数或深分页预算用尽，都不代表范围内已完整遍历。
- 不确定官方配额时保守控制并发，遇429尊重`Retry-After`，不要反复扫全银河。

Spansh也有航线规划能力，但提交计算任务会消耗服务端资源。
不同规划器的路径、参数及编码不同；本文只提供公开**数据查询**参考，
不提供未经核验即可批量提交的航线请求模板。

## 3. EDSM

服务方文档入口：

- <https://www.edsm.net/en/api-v1>
- <https://www.edsm.net/en/api-system-v1>

本次文档页直读返回403，但以下标“实测”的公开查询成功；
部分文档参数由服务方文档的搜索索引辅助核对。不要绕过访问限制。

### 3.1 星系与坐标（实测）

```http
GET https://www.edsm.net/api-v1/system?systemName=Sol&showCoordinates=1&showId=1
```

主要响应字段：`name`、`id`、`id64`、`coords: {x,y,z}`。
其中`id`是EDSM内部ID，**不是**游戏`id64`。
未知坐标可能没有`coords`字段，不能用`(0,0,0)`代替。

文档选项还包括：

| 参数 | 用途 |
|---|---|
| `showPermit=1` | 返回已知许可信息，字段为`requirePermit` |
| `showInformation=1` | 势力、政府等信息 |
| `showPrimaryStar=1` | 已知主恒星信息 |

这些参数不能直接当作其他服务的同名字段使用。

### 3.2 站点、天体与附近星系

| 方法／完整路径 | 主要参数 | 核对 |
|---|---|---|
| GET `https://www.edsm.net/api-system-v1/stations` | `systemName` | 实测 |
| GET `https://www.edsm.net/api-system-v1/bodies` | `systemName` | 文档 |
| GET `https://www.edsm.net/api-system-v1/stations/outfitting` | `marketId` | 实测 |
| GET `https://www.edsm.net/api-v1/sphere-systems` | `systemName`或`x/y/z`、`radius` | 文档 |
| GET `https://www.edsm.net/api-v1/systems` | 名称、名称数组或指定时间窗口 | 文档 |

球形搜索文档列出的`radius`上限是100 ly，不适合直接请求整个银河。
批量、增量及重名星系身份参数需看对应原文档，不要猜测参数。
本文没有把所有EDSM个人／提交接口纳入公开查询清单。

### 3.3 按市场ID复核配件（实测）

```http
GET https://www.edsm.net/api-system-v1/stations/outfitting?marketId=128666762
```

| 响应字段 | 实测含义 |
|---|---|
| `name` | 星系名称 |
| `sName` | 站点名称 |
| `marketId` | 游戏市场ID |
| `outfitting` | 配件列表 |
| `outfitting[].id` | 本次是内部符号字符串，不是数字物品ID |
| `outfitting[].name` | 可读的规格／挂载名称 |

跨来源补证前同时核对市场ID、星系名和站名。不可把附近站或同名站库存合并。
本次配件响应没有库存更新时间，不能把下载时间或其他响应的时间冒充它的库存时间。

## 4. EDTools

这些是公开目录／网页资源，不是实时任务服务（实测／源码）：

```text
GET https://edtools.cc/pve.php?s=Sol&md=50
GET https://edtools.cc/pve.json
GET https://edtools.cc/res.json
```

- `pve.php`是HTML，参数`s`为参考星系，`md`为查询距离。
- `pve.json`本次为按任务来源星系名索引的对象，包含目标及坐标等配对资料。
- `res.json`本次为按星系名索引的地点目录。
- 显式使用`pve.php`；曾遇到`/pve`触发服务器内容协商导致406的情况。
- 这些信息可能陈旧；“潜在任务来源”不等于当前任务板有任务。
- 星环不等于明确RES；Low／High／Haz等类型必须有相应地点证据。
- 查不到记录不能证明没有RES，下载失败也不等于空目录。

建议低频下载并缓存目录，本地反复筛选，而不是每改一个条件就重新抓网页。

## 5. EDDN：公开增量消息流

维护者文档：<https://github.com/EDCD/EDDN/blob/live/docs/Developers.md>。
Schema：<https://github.com/EDCD/EDDN/tree/live/schemas>。
**以`live`分支为线上依据**，不要假设`master`始终与线上一致。

公开监听地址（文档，本次没有实际订阅）：

```text
tcp://eddn.edcd.io:9500
```

接收流程：

```text
ZeroMQ SUB连接 → 订阅空topic → 接收消息
    → zlib解压 → UTF-8 JSON解析 → 按$schemaRef分派
    → 核对版本、实体身份及事件时间 → 更新自己的数据库
```

不是WebSocket、SSE或REST API，不能用普通浏览器fetch查询该地址。
消息通常含`$schemaRef`、`header`、`message`，不同消息使用不同Schema。
给压缩及解压后的数据设置大小上限，处理重复、乱序、重连及积压。

EDDN只转发，不替你保存完整历史或当前全银河状态。消费者停机期间可能漏数据，
需通过合适的dump／归档补齐，或明确标记覆盖缺口。订阅几秒不能得到完整站点目录。
不同网站可能消费相同EDDN上游，多个网站一致不代表多次独立游戏观测。

本文只介绍消费公开消息，**不包括上传入口、玩家上报或账号数据传输**。

## 6. 公开静态数据与离线数据集

### 6.1 EDCD/FDevIDs

仓库：<https://github.com/EDCD/FDevIDs>。

```text
https://raw.githubusercontent.com/EDCD/FDevIDs/<COMMIT>/outfitting.csv
```

用于装备数字ID、英文名称和内部符号映射。`<COMMIT>`需替换为审核过的提交版本，
不是可以原样发送的地址。仓库说明指出覆盖可能不完整；不能假定所有新增Power等
产品已被收录。名称也不保证与CAPI／EDDN显示字符串完全相同。

这是身份表，不是零售库存、购买资格或实时价格表。
普通／Merc版本可能共享符号，不能用符号简单合并成一个产品。

### 6.2 Coriolis数据

仓库：<https://github.com/EDCD/coriolis-data>。
维护者公布的编译数据入口：<https://coriolis.io/data/>、<https://beta.coriolis.io/data/>。

```text
https://codeload.github.com/EDCD/coriolis-data/tar.gz/<COMMIT>
```

用于配船参数和真实模块规格，不证明任何站有货。
限制下载与解压体积；不要将未经检查的归档路径直接解压到任意磁盘位置。
固定版本，更新时对新增ID、改名、规格变化和分类做差异审查。

### 6.3 大范围离线数据

| 入口 | 用途 |
|---|---|
| <https://spansh.co.uk/dumps> | 星系、天体、站点等dump入口 |
| <https://www.edsm.net/en/nightly-dumps> | EDSM周期性数据导出入口 |
| <https://edgalaxydata.space/> | EDDN维护者列出的公开归档入口 |

核对生成时间、格式、全量／增量范围、压缩大小和使用条款。本文未下载完整数据集。
大文件使用流式解压／解析并建立本地索引，不建议一次性加载全银河JSON。
仅覆盖最近数天的文件不能称为完整银河数据，历史归档也可能有采集缺口。

公开仓库的代码许可证不自动授予所有游戏数据、图片等内容的再分发权。
将数据嵌入EXE、镜像或公开下载前需分别核对来源条款。

## 7. 可复制的公开只读请求示例

Python标准库，无需额外依赖；不是生产级重试器，也不适合大型dump下载。

```python
import json
import urllib.parse
import urllib.request

def fetch_json(url, params=None, payload=None, timeout=30, max_bytes=8 * 1024 * 1024):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    headers = {"User-Agent": "YourEDTool/0.1.0", "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("Response too large")
    return json.loads(content.decode("utf-8-sig"))

# EDSM：GET参数
system = fetch_json("https://www.edsm.net/api-v1/system", params={
    "systemName": "Sol", "showCoordinates": 1, "showId": 1,
})
print(system.get("coords"))

# Spansh：POST JSON
data = fetch_json("https://spansh.co.uk/api/systems/search", payload={
    "filters": {"name": {"value": "Sol"}}, "size": 10, "page": 0,
})
exact = next((row for row in data.get("results", [])
              if str(row.get("name", "")).casefold() == "sol"), None)
print(exact)
```

调用方必须处理HTTP错误、超时、非JSON及结构变化，不能捕获异常后悄悄返回空列表。
此示例不申请压缩响应；若正式客户端启用压缩，需限制解压后体积。

## 8. 通用规则与常见误判

1. **身份关联**：游戏星系`id64`、游戏`MarketID`与网站内部ID要分开；64位ID用字符串
   或真正64位整数保存，避免JavaScript Number精度丢失。
2. **坐标**：`x/y/z`单位ly；`math.dist`计算直线距离，不是实际航线距离，
   也不是到站距离Ls。换参考星系需重算距离、重新排序。
3. **时间**：分别保存来源观测时间、下载时间和本地快照时间。不能把今天下载的
   旧库存称为今天的实时库存。
4. **缺失值**：false和0有效，缺字段／null不能自动变成“没有”。
5. **库存身份**：数字ID不明、普通／特殊版共享符号时标记不确定，不能直接算两件都有。
6. **版本**：Live、Legacy、游戏Beta不要混库；目录和数据快照也要各自标明版本。
7. **价格**：规则推算的折扣／加价不是实时成交验证；个人资格、解锁和站点优惠不能混淆。
8. **限流**：从低并发开始，429尊重`Retry-After`；不要宣称未经核对的每分钟固定配额。
9. **失败**：400修参数、401／403核对权限与政策、5xx／超时只对合适的只读请求有限退避。
   不绕过反爬或访问限制。
10. **完整性**：达到页数上限、重复页、服务失败和空目录含义不同；部分结果要明确标注。
11. **缓存**：稳定坐标、版本化身份目录、易变化库存分别缓存，更新成功后原子替换，
    失败保留有效旧版本。内容哈希不是发布者数字签名。
12. **范围**：保存的小名单不等于全银河；扩大查询半径不会凭空新增名单外的站点。

## 9. 本次核对范围与资料链接

2026-10-20成功只读探测：Spansh星系／天体搜索、星系／站点详情；
EDSM单星系坐标、星系站点列表及按市场ID配件列表；EDTools两个JSON目录。
Spansh站点搜索及配件规格过滤在项目开发中多次实测成功。
没有实际订阅EDDN或下载全银河dump；“文档／源码”项不冒称本次全部线上验证。

原始资料：

- Spansh文档：<https://docs.spansh.co.uk/>。
- EDSM Systems API：<https://www.edsm.net/en/api-v1>。
- EDSM System API：<https://www.edsm.net/en/api-system-v1>。
- EDTools：<https://edtools.cc/pve.php>。
- EDDN线上说明：<https://github.com/EDCD/EDDN/blob/live/README.md>。
- EDDN消费者规范：<https://github.com/EDCD/EDDN/blob/live/docs/Developers.md>。
- EDDN线上Schema：<https://github.com/EDCD/EDDN/tree/live/schemas>。
- FDevIDs：<https://github.com/EDCD/FDevIDs>。
- Coriolis数据：<https://github.com/EDCD/coriolis-data>。
- Inara“不提供市场／站点数据库输出”的说明：<https://inara.cz/elite/inara-api-devguide/>。

分享本文不等于分享任何服务的API凭据，也不构成对第三方数据再分发的授权。
接口变更时应更新本文核对日期、对应示例及限制说明。
