# Elite Dangerous 数据源与API开发参考

核对日期：**2026-10-20**。面向独立开发的新工具；阅读本文不需要本项目代码。

仅需分享公开查询与公开数据集时，使用独立的[公开数据源与API速查](ed-public-data-api-reference.md)，不含账号授权、个人日志或上传流程。

本文不是Frontier或各服务方的官方承诺，也不是所有ED接口的穷尽目录。
接口、字段、权限和配额可能变化，开发前应重新核对章节末尾的原始文档。
**公开可访问不等于允许无限请求、抓取网页或重新分发数据。**

## 目录

1. [按需求选择数据源](#1-按需求选择数据源)
2. [身份、版本与时间](#2-身份版本与时间)
3. [Spansh：搜索、详情与规划](#3-spansh搜索详情与规划)
4. [EDSM：坐标、天体与站点复核](#4-edsm坐标天体与站点复核)
5. [EDTools：PvE与RES目录](#5-edtoolspve与res目录)
6. [本地Journal及状态文件](#6-本地journal及状态文件)
7. [Frontier CAPI与OAuth](#7-frontier-capi与oauth)
8. [EDDN实时消息流](#8-eddn实时消息流)
9. [Inara：账号同步，不是银河搜索API](#9-inara账号同步不是银河搜索api)
10. [EDCD身份表、配船数据和离线数据集](#10-edcd身份表配船数据和离线数据集)
11. [通用请求与缓存设计](#11-通用请求与缓存设计)
12. [复用架构、测试与维护](#12-复用架构测试与维护)
13. [核对记录与来源](#13-核对记录与来源)

### 证据等级

- **[实测]**：本项目开发期间成功读取过该接口；第13节另列本次实际探测项。
- **[文档]**：服务方／维护者文档记载，本次未执行该业务请求。
- **[源码]**：当前项目或独立规划器已有调用实现，不代表本次重新线上验收。
- **[建议]**：工具自身的工程策略，不是服务方规定。

没有进行真实账号授权、Inara账号写入、EDDN上传、全银河数据下载或批量提交航线作业。

## 1. 按需求选择数据源

| 需求 | 优先选择 | 接入形式／授权 | 不能据此保证什么 |
|---|---|---|---|
| 跨星系找站、配件、舰船、天体 | Spansh | 公开HTTPS查询，本项目请求无需key | 实时库存、完整银河覆盖 |
| 星系坐标、附近星系、站点／天体复核 | EDSM | 公开查询通常无需key；个人接口另有授权 | 未记录就不存在、ID与别站相同 |
| 自己的位置、配船、材料、活动 | 本地Journal及附属JSON | 用户同意读取本机文件 | 任意其他玩家的数据 |
| 自己最近停靠站的市场／配件、账号资料 | Frontier CAPI | 注册应用＋玩家OAuth授权 | 任意远程站的实时搜索 |
| 自建市场／库存增量数据库 | EDDN | ZeroMQ订阅；上传另用HTTPS | 历史回放、消息绝不丢失 |
| PvE任务来源配对、RES目录 | EDTools | 公开JSON／网页资源 | 当前任务板一定刷任务 |
| 向Inara同步玩家资料 | Inara API | 应用白名单＋相应API key | 星系／站点／市场全库查询 |
| 物品ID、英文名、符号映射 | EDCD/FDevIDs | 版本化CSV | 各站库存、目录永远完整 |
| 配船计算、舰船／模块参数 | Coriolis数据 | 版本化JSON | 零售站点供应、实时成交价格 |
| 大范围统计、长期离线检索 | Spansh／EDSM dumps等 | 大文件下载＋本地索引 | 获取时刻之后的新状态 |

**不要把Inara网页上能查的内容误认为Inara API也能查。**
多个服务可能消费相同EDDN上游；“两家都这么写”不一定是两次独立游戏观测。

## 2. 身份、版本与时间

### 2.1 不要混用各种ID

| 实体 | 适合作跨源关联的字段 | 常见陷阱 |
|---|---|---|
| 星系 | 游戏`SystemAddress`／对应`id64` | EDSM的`id`是其内部ID，不是`id64` |
| 天体 | 已确认语义的天体`id64`，及所属星系 | 天体`body_id`常是星系内编号，不是全银河主键 |
| 站点市场 | 游戏`MarketID`／`marketId`／`market_id` | 网站自己的站点ID、URL数字不一定是市场ID |
| 装备 | 数字FDev物品ID＋对应身份事实 | 某些响应里的`id`实际是符号字符串 |
| 玩家拥有的舰船 | 玩家身份＋该玩家的ShipID | ShipID不是舰船型号ID，也不是全局玩家船唯一ID |

建议内部把64位外部ID保存为**十进制字符串**或真正64位整数。
JavaScript等环境不要未经处理就用浮点Number保存任意64位ID。
跨源合并站内库存至少核对市场ID、星系和站名；冲突时停止合并。
航母会移动，名字也可能改变，不能永久沿用旧坐标或仅按站名关联。

### 2.2 普通／Power／AX／Merc不是同一分类维度

- `class`／`rating`／挂载／船型装甲归属都要保留，不能用“有8级＋有A级”推导“有8A”。
- 显示名称和内部符号不总是一对一。普通版、Merc预改装版可能共享符号，数字ID不同。
- 本项目遇到过Spansh将共享符号显示为Merc版名称、却未提供独立数字ID的情况。
  仅凭该名字不能证明普通版和Merc版两件都有，也不能证明Merc版单独有货。
- EDSM配件记录里的`id`本次实测是内部符号字符串，不可直接转换成数字物品ID。
- “所有已知配件”必须指明目录版本、排除规则、购买资格假设和检查范围。

### 2.3 时间必须按证据保存

至少区分：`source_observed_at`（来源库存时间）、`fetched_at`（下载时间）、
`snapshot_created_at`（本地快照时间）、`catalog_version`（目录版本）。

- HTTP成功不是库存实时，今天下载的记录可能几个月前上报。
- 配件、市场、船厂时间可能分别是`outfitting_updated_at`、`market_updated_at`、`shipyard_updated_at`。
- 不能用站点`updated_at`替代配件更新时间，也不能给旧库存套上新详情响应的时间。
- EDSM本次配件响应未提供库存时间，应明确标注，而非填成本地下载时间。
- `false`与`0`是有效值；缺字段、`null`、空字符串不能自动改成“没有”。
- Live、Legacy、游戏Beta及第三方工具自身Beta版本应分别处理。

## 3. Spansh：搜索、详情与规划

入口：`https://spansh.co.uk/api`；文档：<https://docs.spansh.co.uk/>。

**重要区分**：本次读取的OpenAPI文档版本为`3.1.1`，列出的是下面4个详情GET。
搜索、枚举及规划端点另有本项目实际调用／源码依据，不能冒称均有OpenAPI契约。
直接GET `/api`本次返回404，**不表示具体API端点不可用**。

### 3.1 详情GET [文档；system/station本次实测]

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/system/{id64}` | 星系详情 |
| GET | `/body/{id64}` | 天体详情 |
| GET | `/station/{marketId}` | 站点详情 |
| GET | `/dump/{id64}` | 单星系dump形态的详细数据 |

示例：

```http
GET https://spansh.co.uk/api/system/3932277478106
GET https://spansh.co.uk/api/station/128666762
```

这两个地址本次实测顶层为`{"record": {...}}`；不要按搜索的`results`读取。
`/dump`文档采用dump数据结构，不能假定与`/system`完全相同。
已有稳定ID时可优先读取详情，避免用模糊名字重新搜索。

### 3.2 POST搜索 [实测]

```text
POST /systems/search
POST /stations/search
POST /bodies/search
Content-Type: application/json
```

下面是“Sol周围50 ly内有配件服务的站”的请求体；`page`从0开始：

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

星系坐标／许可查询示例：

```json
{
  "filters": {"name": {"value": "Shinrarta Dezhra"}},
  "size": 10,
  "page": 0
}
```

天体查询示例：

```json
{
  "filters": {"system_name": {"value": "Sol"}},
  "size": 10,
  "page": 0
}
```

搜索响应本次实测包含`count`、`results`，还可包含`from`、`size`、`reference`等。
消费时只依赖已验证字段，并对类型／缺失做检查，不要求所有搜索类型返回相同字段。

**名字查询可能返回相似名字**，例如查Jameson Memorial时也可能得到Jameson Base。
取`results[0]`不等于精确匹配；应比较完整星系名、站名及ID。
显示用名称不要通过去标点等过度正规化当作唯一身份。

### 3.3 精确模块规格及筛选格式 [源码／实测]

本项目已使用的常见格式：

| 字段类型 | 例子 |
|---|---|
| 字符串 | `"system_name": {"value": "Sol"}` |
| 布尔 | `"has_outfitting": {"value": true}` |
| 枚举集合 | `"type": {"value": ["Orbis Starport"]}` |
| 数值区间 | `"population": {"comparison": "<=>", "value": [1, 1000000]}` |
| 参考距离 | `"distance": {"min": 0, "max": 500}`＋`reference_system` |
| 配件 | 见下面的组合条目 |

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

多个模块组合条目在本项目用作同站AND预筛，随后仍逐项本地核验真实库存。
并非任意集合字段都有相同AND语义；新增筛选器应单独测试“服务端候选超集＋本地精确判断”。
字段值及英文拼写优先使用服务返回的正式值，不随意翻译请求参数。

枚举辅助接口：`GET /{kind}/field_values/{field}`，例如
`https://spansh.co.uk/api/stations/field_values/modules`。[源码]
其`values`可能是列表或嵌套对象；本项目做了兼容解析。
它只能帮助提供名称／枚举，不能证明所有尺寸×评级×挂载组合存在。

### 3.4 关键响应字段 [实测]

| 内容 | 星系搜索 | 站点搜索 |
|---|---|---|
| 身份 | `name`、`id64` | `name`、`market_id`、`system_name`、`system_id64` |
| 坐标 | `x`、`y`、`z` | `system_x`、`system_y`、`system_z` |
| 许可 | `needs_permit`、`known_permit` | 不保证存在，应补查所属星系 |
| Power | `controlling_power`、`power_state` | `system_controlling_power`、`system_power_state` |
| 库存／服务 | 视响应而定 | `modules`、`ships`、`market`、`services`、`technology_broker` |
| 距离 | `distance`，相对请求的参考点，ly | `distance`为ly；`distance_to_arrival`为Ls |

字段可能缺失。`system_power`等关联列表不等于实际控制Power。
`Technology Broker`服务不等于明确的Guardian经纪人；有服务也不证明玩家已解锁产品。
舰船库存、Power配件购买资格、舰队航母访问权限和许可是不同条件。

### 3.5 分页与负载 [建议／项目经验]

- 常用每页100～500；这是本项目取值，不是所有端点的固定服务上限。
- `count`可能封顶，分页期间数据也会变化，不能单凭它证明遍历完成。
- 检测空页／短页、重复页、无新增ID，记录停止原因，跨页按稳定ID去重。
- 本项目满配件采集限制单来源深分页到10,000条以内；这是安全策略，不是全服务规范。
- 达到页数／数量上限应标“部分覆盖”，不能说范围内不存在其他站。
- 若要频繁扫描超大范围，应优先考虑dump＋本地空间索引，而不是反复扫HTTP分页。

### 3.6 航线规划 [源码；未在本次提交作业]

独立规划器使用：

```text
POST https://spansh.co.uk/api/generic/route
Content-Type: application/x-www-form-urlencoded

GET https://spansh.co.uk/api/results/{job}
```

这是**表单请求，不是搜索接口的JSON请求体**。
`source`／`destination`、舰船参数、`ship_build`、燃料储备、货物和超充选项等
应以对应规划器页面当前请求和已验证实现为准；不能把简易中子路线`/route`的
`from`／`to`参数直接套给`/generic/route`，也不能只给一个跳距就假装完整配船计算。

流程：提交一次→取得`job`→以该job轮询→确认完成且结果结构正确。
本项目源码处理`queued/unstarted/started/running`，以2秒起步逐渐退避到10秒；
识别`failed/error`和完成状态，设置总截止时间及取消操作。
遇到未认识的状态应报错；超时不自动重复提交计算任务。
完整请求参考独立项目的`src/route_tool.py`，不是本参考文档里的公共搜索示例。

## 4. EDSM：坐标、天体与站点复核

文档入口：<https://www.edsm.net/en/api-v1>、<https://www.edsm.net/en/api-system-v1>。
本次直接抓取文档页遇到403，但公开查询端点读取成功；部分参数另由搜索索引中的
服务方文档核对。文档页403不表示API查询也被拒绝，不应尝试绕过访问控制。

### 4.1 GET星系坐标 [本次实测]

```http
GET https://www.edsm.net/api-v1/system?systemName=Sol&showCoordinates=1&showId=1
```

关键字段是`name`、`id`、`id64`和`coords: {x,y,z}`；坐标未知时`coords`可能不存在。
参数必须URL编码，例如`Shinrarta%20Dezhra`，不要手工拼接含空格、`&`的名称。

其他有文档依据的选项：`showPermit=1`、`showInformation=1`、`showPrimaryStar=1`。
许可字段叫`requirePermit`，不是Spansh的`needs_permit`；命名应在适配层转换。[文档]

### 4.2 星系／站点接口

| 路径（均为GET） | 主要参数 | 状态 |
|---|---|---|
| `/api-system-v1/stations` | `systemName` | 本次实测 |
| `/api-system-v1/bodies` | `systemName`；重名身份参数见原文档 | 文档 |
| `/api-system-v1/stations/outfitting` | `marketId` | 本次实测 |
| `/api-v1/sphere-systems` | `systemName`或`x/y/z`、`radius` | 文档 |
| `/api-v1/systems` | 名称／名称数组或时间窗口等 | 文档 |

球形搜索文档列出的`radius`最大为100 ly；不要拿它直接请求全银河。
批量／增量接口有各自范围和窗口限制，不能认为单星系参数可原样套用。
EDSM还提供市场、船厂、派系、交通及个人接口；接入未列出的路径前重新查原始文档，
不要按命名猜接口。本文不声称这些端点本次全部测试过。

### 4.3 同市场库存复核 [本次实测]

```http
GET https://www.edsm.net/api-system-v1/stations/outfitting?marketId=128666762
```

响应字段含义很容易看错：

| 字段 | 本次实测含义 |
|---|---|
| `name` | 星系名称，不是站名 |
| `sName` | 站点名称 |
| `marketId` | 游戏市场ID |
| `id`、`sId` | EDSM自身ID语境，不要混当装备／市场ID |
| `outfitting` | 配件记录列表 |
| `outfitting[].id` | 本次是内部符号字符串 |
| `outfitting[].name` | 含规格／挂载的可读名称，例如`2E Multi-Cannon (Fixed)` |

使用前严格确认`marketId`、`name`、`sName`三者匹配目标，再解析配件身份。
本项目只将“符号＋明确普通版名称”能唯一对应数字ID的记录作为普通库存补证。
不能因为同一符号有普通版记录，就顺便确认Merc版也存在。

该配件响应本次没有库存时间；星系站点列表的`updateTime`字段并不自动成为这份
配件响应的专属时间。合并时保持各自来源及时间的不确定性。

## 5. EDTools：PvE与RES目录

以下为第三方工具公开资源，**不是游戏任务板API**：[实测／源码]

```text
GET https://edtools.cc/pve.php?s=Sol&md=50
GET https://edtools.cc/pve.json
GET https://edtools.cc/res.json
```

- `pve.php`为网页结果，需HTML解析，不是JSON；`s`为参考星系，`md`为查询距离参数。
- `pve.json`为任务来源配对目录；本次顶层是按来源星系名索引的对象。
  项目解析其`target`及`x/y/z`等字段。
- `res.json`为地点目录，本次同样为按星系名索引的对象；具体地点字段应做版本／结构校验。
- 使用明确的`/pve.php`，不要随意缩成`/pve`。本项目遇到过Apache内容协商导致406。
- 来源派系数只是潜在发任务条件，不等于实时任务数量；声望、BGS和当期任务需游戏内确认。
- 星环存在不等于已确认RES，更不能推定Low／High／Haz。特定RES级别需要明确地点证据。
- 一个站／星系没有目录记录不能证明没有RES；网络失败不能解释成零命中。

建议缓存公开目录、记录下载时间，避免每次改筛选条件重新抓HTML。
项目曾采用1小时目录缓存；这是项目策略，不是EDTools的公开SLA或规定配额。

## 6. 本地Journal及状态文件

这是**本地数据接口，不是HTTP API**。[文档]
PC常见目录：

```text
%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\
```

Saved Games可能被重定向，不应只硬编码上述路径；提供用户选择目录的入口。

| 文件 | 读取方式／用途 |
|---|---|
| `Journal.*.log` | 逐行JSON（JSON Lines），会话事件、位置、配船、交易等 |
| `Status.json` | 常更新的座舱状态，不是追加日志 |
| `Market.json` | 打开市场交互后产生的商品快照 |
| `Outfitting.json` | 打开配件交互后产生的配件／价格快照 |
| `Shipyard.json` | 打开船厂交互后产生的舰船／价格快照 |

按需处理`Location`、`FSDJump`、`CarrierJump`、`Docked`、`Loadout`、`Materials`等事件；
新增游戏机制可能带来新事件，不要遇到未知事件就让整个读取器退出。

**最小读取示例**（离线完整日志，不是生产级tail实现）：

```python
import json
from pathlib import Path

def read_events(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)

# for event in read_events(user_selected_path):
#     if event.get("event") == "FSDJump":
#         print(event.get("StarSystem"), event.get("SystemAddress"), event.get("StarPos"))
```

生产级读取器还需处理：半行尚未写完、文件轮换／Continued、新会话、重启后的读取位置、
重复事件，以及附属JSON恰好处于改写过程的短暂解析失败。不要因一次解析失败清空用户数据。
使用`MarketID`、`SystemAddress`、事件时间核对附属快照，不要把上一次停靠站库存挂到新站。

Journal含玩家名、FID、位置、资产等隐私；默认本地处理，上传需明确同意及字段过滤。
事件中的`*_Localised`是显示文本，不适合做稳定身份键。
不要假设日志覆盖整个实时任务板或完整银河，只能处理实际写出的事件。

文档优先看Frontier的[Player Tools & API讨论区](https://forums.frontier.co.uk/forums/elite-api-and-tools/)
中最新Journal Manual；[社区可检索手册](https://doc.elitedangereuse.fr/)用于方便检索，
需要核对其更新版本。旧版PDF不能当作2026年所有事件的完整规范。

## 7. Frontier CAPI与OAuth

**需要开发者注册和玩家授权，不是免key公共银河查询。**[文档；本次未授权实测]

开发入口：<https://user.frontierstore.net/>；开发文档通常需登录：
<https://user.frontierstore.net/developer/docs>。
优先核对该入口以及EDCD/FDevIDs的[Frontier API社区文档](https://github.com/EDCD/FDevIDs/tree/master/Frontier%20API)。
旧`Athanasius/fd-api`示例项目已标记不再维护，不要直接照搬历史Token期限／PKCE细节。

### 7.1 授权流程

```text
注册自己的应用、回调地址和权限
    → 用户浏览器访问Frontier授权页（/auth）
    → 校验回调state
    → POST /token交换授权码
    → 用访问Token读取CAPI
    → 依返回有效期刷新Token／必要时重新授权
```

授权服务为`https://auth.frontierstore.net`。
桌面程序按当前开发者规范使用Authorization Code＋PKCE，不能把可保密的client secret
硬塞进EXE当成安全措施，也不要向用户索取Frontier密码或复用别的应用client ID。
Token交换是`application/x-www-form-urlencoded`，不是JSON搜索请求。
`audience`、scope及回调地址按账号平台和已注册应用配置，不要固定套用旧示例。
社区文档提示部分情况下需要`auth capi`，不能未经验证删掉`auth`权限。

Token存入操作系统凭据存储等适当位置；日志、CSV、截图和Git均不得包含Token／API key。
收到401先判断Token失效、撤权或权限不完整，不能无限刷新重试。

### 7.2 读取端点

| 基础地址／GET路径 | 用途（社区文档记载） |
|---|---|
| `https://companion.orerve.net` | Live CAPI |
| `https://legacy-companion.orerve.net` | Legacy CAPI，不与Live混用 |
| `/profile` | 当前玩家资料、停靠状态、舰船等 |
| `/market` | 该玩家最近停靠站的市场 |
| `/shipyard` | 该玩家最近停靠站的船厂及配件 |
| `/fleetcarrier` | 该玩家自己的航母资料；无航母可能204 |
| `/journal`及日期路径 | 服务器保存的玩家日志，不是本地实时事件流 |
| `/communitygoals` | CG及玩家贡献，字段以当前服务为准 |

请求示意（占位Token不可直接使用）：

```http
GET /profile HTTP/1.1
Host: companion.orerve.net
Authorization: Bearer <ACCESS_TOKEN>
User-Agent: EDCD-YourApp-0.1.0
```

EDCD社区文档要求自定义User-Agent形如`EDCD-[A-Za-z]+-[.0-9]+`；使用自己真实的应用标识。
文档建议低频、事件触发地查询，不要靠每秒轮询模拟实时；这不是可依赖的固定配额承诺。

**处理数据滞后**：先检查玩家确实停靠，再将CAPI返回的星系、站点／市场身份与Journal
最近`Docked/Location`核对；不一致则不使用、不上传该库存。
`/market`不是任意远程站搜索，也没有“实时查全银河所有站”的CAPI接口。
社区文档列出401（授权）、418（维护）等特殊返回；应分别处理，不能一律当空JSON。

## 8. EDDN实时消息流

权威入口：<https://github.com/EDCD/EDDN/tree/live>。
**使用`live`分支规范**，不能假设`master`正好等于当前线上服务。[文档]

EDDN是转发网络，自己不提供完整历史数据库或按站名查询的REST接口。
适合长期运行的采集服务，不适合仅为一次搜索临时接几秒就宣称拿到完整库存。

### 8.1 接收

```text
ZeroMQ SUB连接 tcp://eddn.edcd.io:9500
    → 订阅空topic接收消息
    → 对消息做zlib解压
    → 解析UTF-8 JSON
    → 按$schemaRef分派处理
    → 核对游戏版本、身份和事件时间
    → 入队／存储／更新本地索引
```

这是ZeroMQ，不是WebSocket、HTTP GET或SSE；不能用普通浏览器fetch读取该TCP端口。
协议接收例子见服务方[examples](https://github.com/EDCD/EDDN/tree/live/examples)。
本次未实际订阅；具体客户端库配置按其当前文档确认。

常见结构为`$schemaRef`、`header`、`message`。消息Schema可能分别覆盖商品、配件、
船厂及不同Journal事件，**不要在代码里永久锁死一个所有消息共用的版本号**。

生产消费者需处理重连、重复／乱序、队列积压和停机期间缺失。
EDDN本身不提供你离线期间的自动历史补发；完整性需要dump／归档补齐或明确标记缺口。
给解压后的消息设置大小上限，不盲信输入。

### 8.2 上传

```http
POST https://eddn.edcd.io:4430/upload/
Content-Type: application/json
```

- 非标准4430端口及结尾`/`不可遗漏；当前维护者规范要求HTTP/1.1。
- 正文必须满足线上相应Schema，不是直接上传整个Journal／CAPI响应。
- 正式与测试消息要按规范分离，测试使用相应`/test` Schema或自己的测试服务。
- 过滤玩家私有字段和不允许的`*_Localised`等字段；保留规范要求的软件／游戏版本。
- `horizons/odyssey`未知时不能编造false，按Schema允许的方式省略。
- 服务方规定失败重试至少等待1分钟；400或426不应原样自动重试。
  **不要将通用HTTP的短退避策略直接套到EDDN上传。**
- 每种Schema的`.json`是具体字段权威；README辅助解释。上传前做本地Schema校验。

本参考文档没有提交任何测试数据到正式网络。

## 9. Inara：账号同步，不是银河搜索API

接口：`POST https://inara.cz/inapi/v1/`，JSON请求／响应。[服务方文档；本次未调用]
开发指南明确表示：**不提供市场、小派系影响力、星系、站点等数据库查询输出**。
不要发明`getStations`／`getMarketPrices`之类不存在的事件。

发布前联系维护者登记应用准确名称及用途，申请白名单。
个人写入需用户个人key；通用只读事件是否可用以分配的应用key及事件文档为准。

文档中现有只读事件的请求结构示意：

```json
{
  "header": {
    "appName": "YOUR_APPROVED_APP",
    "appVersion": "0.1.0",
    "isBeingDeveloped": true,
    "APIkey": "REPLACE_WITH_AUTHORIZED_KEY"
  },
  "events": [
    {
      "eventName": "getCommanderProfile",
      "eventTimestamp": "REPLACE_WITH_CURRENT_UTC_ISO8601",
      "eventCustomID": 1,
      "eventData": {"searchName": "REPLACE_WITH_ALLOWED_COMMANDER_NAME"}
    }
  ]
}
```

这是结构示意，必须替换占位值并遵守玩家隐私／用途要求，不能直接当可用请求。
当前文档要求事件时间与事件实际发生时间相符，且不应早于30天；不要复制历史示例日期。
处理响应时检查`header.eventStatus`及每个事件的`eventStatus`，不是只检查HTTP 200。
文档状态包括200成功、202警告、204无结果、400错误。

批量提交事件，避免每次材料拾取单独发HTTP请求；去重且只同步新增变化。
只发送允许的Live数据，不能混入Legacy或正式账号上的游戏Beta测试数据。
`setCommanderInventory`等事件具有覆盖／清空语义，不能把不完整本地快照当完整库存上传。

若只是让用户打开网页，可使用维护者给出的链接形式，搜索值需URL编码：

```text
https://inara.cz/elite/starsystem/?search=Shinrarta%20Dezhra
https://inara.cz/elite/station/?search=Jameson%20Memorial%20%5BShinrarta%20Dezhra%5D
```

网页链接不是API授权；不要把网页抓取当作受支持的数据库接口，更不能绕过访问限制。

## 10. EDCD身份表、配船数据和离线数据集

### 10.1 FDevIDs

仓库：<https://github.com/EDCD/FDevIDs>；装备身份常用`outfitting.csv`。
原始文件可按提交固定版本，例如：

```text
https://raw.githubusercontent.com/EDCD/FDevIDs/<COMMIT>/outfitting.csv
```

维护者明确指出目录可能不完整，尤其不能假设Power等新增产品总是及时覆盖；
英文`name`也不保证与CAPI／EDDN显示字符串相同。
它是**身份映射表，不是零售库存或购买资格数据库**。
新增数字ID、改名或规格修正要出差异报告；新装备未分类时报警，不静默丢弃。

### 10.2 Coriolis数据

仓库：<https://github.com/EDCD/coriolis-data>；维护者同时提供
<https://coriolis.io/data/>及<https://beta.coriolis.io/data/>的编译数据入口。
本项目使用固定提交归档：

```text
https://codeload.github.com/EDCD/coriolis-data/tar.gz/<COMMIT>
```

这是配船事实数据，不是HTTP业务查询。解析前限制下载／解压大小，逐文件读取，
不要对未经验证的归档路径做任意磁盘解压。
解析真实模块记录，不根据独立尺寸／评级列表笛卡尔积生成虚构规格。

### 10.3 dumps、归档和废弃数据源

- Spansh dumps：<https://spansh.co.uk/dumps>。
- EDSM nightly dumps：<https://www.edsm.net/en/nightly-dumps>。
- EDDN维护者列出的消息归档入口：<https://edgalaxydata.space/>。

先看生成时间、压缩大小、实际格式、是否仅覆盖增量／时间窗口。
全银河数据可能极大，应流式解压／解析、建索引，避免一次`json.load`吃满内存。
EDSM的完整天体数据导出曾受体量限制，不能把某个“最近7天”文件当全量。
归档也可能有采集停机缺口，不意味着官方完整数据库。

**EDDB已停止服务**，旧教程中的EDDB接口／下载地址不能作为新工具运行依赖。
EDAstro、EDGIS等可作为进一步寻找专题数据的入口，但本文未核实其当前具体API契约，
不在此编造地址或参数；按各自维护者说明接入。

代码许可证不自动授权第三方数据、图片、价格表、字体或所有批量再分发。
存储／发布／嵌入EXE前逐项核对来源条款，保留来源版本和署名要求。

## 11. 通用请求与缓存设计

### 11.1 无额外依赖的HTTPS JSON示例

以下只演示公开、只读查询；无自动重试、OAuth或大文件流式支持。
不要拿它直接发送EDDN消息或处理所有服务的状态码。

```python
import json
import urllib.parse
import urllib.request

def get_json(url, params=None, payload=None, timeout=30, max_bytes=8 * 1024 * 1024):
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
        raise ValueError("Response exceeds configured size limit")
    return json.loads(content.decode("utf-8-sig"))

# Spansh星系查询：POST JSON
response = get_json(
    "https://spansh.co.uk/api/systems/search",
    payload={"filters": {"name": {"value": "Sol"}}, "size": 10, "page": 0},
)
exact = next((row for row in response.get("results", [])
              if str(row.get("name", "")).casefold() == "sol"), None)

# EDSM坐标查询：GET参数
system = get_json("https://www.edsm.net/api-v1/system", params={
    "systemName": "Sol", "showCoordinates": 1, "showId": 1,
})
```

这个示例不申请压缩响应；若正式客户端启用压缩，应另外限制解压后体积。
HTTP错误会抛出异常，调用方必须捕获并显示真实错误，不能返回`[]`掩盖失败。

### 11.2 错误和请求节制

| 情况 | 推荐处理 |
|---|---|
| 400、参数／Schema错误 | 修正请求，不重复同一个坏请求 |
| 401、403 | 检查授权、范围和访问政策，不绕过限制 |
| 404 | 区分资源不存在、端点变动、站点根路径没有路由 |
| 429 | 尊重`Retry-After`，暂停排队请求并降低并发 |
| 500／502／503／504、超时 | 对适合重试的只读请求有限退避，带抖动及截止时间 |
| HTML代替JSON | 报协议错误／维护／防护页，不当成空数据 |
| HTTP成功但业务失败 | 检查服务自己的status／error／eventStatus |
| 取消／页数不足／部分响应 | 保留可证明的结果并显式标记不完整 |

上表是通用建议；**EDDN上传的至少1分钟失败重试、CAPI授权刷新、Inara写入批量语义
必须使用各自规则**。写入／提交计算任务不应像幂等GET一样盲目重试。
从每主机1～2个在途请求等保守策略开始，遇到429减少负载；没有查到官方配额就不要
宣称“每分钟允许N次”。做产品级后台采集前与维护者确认合理用途。

### 11.3 把三类缓存分开

1. **身份／规则目录**：版本化、审核后更新，记录上游提交及分类理由。
2. **库存／市场／BGS快照**：独立保存来源观测时间，按用户操作或业务TTL更新。
3. **稳定坐标**：按星系ID／精确名称缓存，换参考点只需重算距离。

两星系间直线距离为`math.dist((x1,y1,z1), (x2,y2,z2))`，单位ly；
它不是实际航线长度，也不能代替`distance_to_arrival`（Ls）。

**小名单工具模式**：先发现站点并保存完整原始证据，之后改变折扣／AX等条件本地筛选；
换参考星系只补查坐标，重算距离并重新排序。手动更新时才重新发现站点及刷新库存。
扩大半径不会补出名单外站点；远离Bubble后旧名单可能不适用，不能把无结果解释为当地无供应。

目录更新不应中途改写正在执行查询的需求；快照要绑定自己的目录／规则版本。
下载先写临时文件，校验成功后原子替换；保留上版，失败不覆盖有效缓存。
SHA256是完整性校验，不是发布者数字签名。

## 12. 复用架构、测试与维护

建议每种来源一个适配器，向上层输出统一实体，而不是在GUI里拼URL：

```text
UI／CLI
  → 查询条件／业务规则
  → 本地索引与版本化快照
  → 来源适配器（Spansh／EDSM／Journal／CAPI／EDDN／EDTools）
  → 超时、限流、取消、错误分类、凭据存储
```

至少保留：实体ID、原始名称、来源、观测时间、下载时间、身份可信度、覆盖范围、
完整性标记及目录版本。可以保存原始响应用于诊断，但不能泄露个人／授权数据。

发布前用脱敏回放测试：

- 同名异站、模糊星系名、错误市场ID、64位整数精度。
- 缺字段／null／false／0；未知身份不能算有货。
- 普通／Merc共享符号、数字ID冲突、真实挂载组合。
- 429／500／超时／断网／返回HTML／重复分页／计数封顶。
- 中途取消、快照写入失败、目录版本不兼容、保留旧快照。
- Live／Legacy分离，EDDN测试消息和私有字段过滤。
- 换参考星系重算距离及排序，但不重抓库存；扩大半径不误报新范围全覆盖。
- CSV保存本次查询条件、快照时间和目录版本，而不是导出时已修改的表单。

当前仓库中可参考的实现（相对路径，可独立重写，不要求依赖本项目）：

| 实现 | 位置 |
|---|---|
| Spansh过滤、分页及精确本地复核 | `src/filter_engine.py` |
| 字段枚举缓存 | `src/field_options.py` |
| EDSM同市场库存身份复核 | `src/outfitting_identity.py` |
| 装备事实目录及版本 | `src/outfitting_catalog.py` |
| 站点小名单与坐标重算 | `src/outfitting_snapshot.py` |
| EDTools目录及网页解析 | `src/pve_tool.py` |
| 数据清单更新与校验 | `src/catalog_updates.py`、`docs/catalog-updates.md` |
| 航线异步任务 | [独立规划器](https://github.com/kxdxzr/Elite_dangerous_Neutron_Planner)的`src/route_tool.py` |

本文只提供接口开发参考，不意味着当前筛选器已接入CAPI、Inara账号或EDDN订阅。

## 13. 核对记录与来源

### 13.1 本次只读探测

2026-10-20以下请求成功返回可解析JSON；仅检查结构与少量记录，不构成服务可用性保证：

| 请求 | 本次结果 |
|---|---|
| Spansh POST `/systems/search`，Sol | `results`对象列表，可读取坐标等 |
| Spansh POST `/bodies/search`，Sol | `results`对象列表 |
| Spansh GET `/system/3932277478106` | `record`星系对象 |
| Spansh GET `/station/128666762` | `record`站点对象 |
| EDSM GET `/api-v1/system`，Sol＋坐标／ID | `name/id/id64/coords` |
| EDSM GET `/api-system-v1/stations`，Shinrarta Dezhra | `stations`列表 |
| EDSM GET `/api-system-v1/stations/outfitting?marketId=128666762` | `outfitting`列表，ID为符号字符串；未提供库存时间 |
| EDTools GET `/pve.json`、`/res.json` | 按星系名索引的对象 |

Spansh POST `/stations/search`及具体规格过滤在本项目多次线上检索中成功使用。
没有为验证本文而提交任何有副作用的账号写入／上传／规划请求。
未来更新本文时，应修改核对日期并补上变化，而不是保留“永远有效”的措辞。

### 13.2 原始资料索引

- Spansh服务方OpenAPI：<https://docs.spansh.co.uk/>。
- EDSM Systems API：<https://www.edsm.net/en/api-v1>。
- EDSM System API：<https://www.edsm.net/en/api-system-v1>。
- EDTools PvE页面：<https://edtools.cc/pve.php>。
- Frontier开发者入口：<https://user.frontierstore.net/developer/docs>（需相应账号权限）。
- Frontier Player Tools & API：<https://forums.frontier.co.uk/forums/elite-api-and-tools/>。
- Journal社区可检索手册：<https://doc.elitedangereuse.fr/>（核对手册覆盖版本）。
- EDCD Frontier API社区文档：<https://github.com/EDCD/FDevIDs/tree/master/Frontier%20API>。
- EDMarketConnector维护中实现：<https://github.com/EDCD/EDMarketConnector>。
- EDDN线上开发规范：<https://github.com/EDCD/EDDN/blob/live/docs/Developers.md>。
- EDDN线上Schema：<https://github.com/EDCD/EDDN/tree/live/schemas>。
- Inara开发指南：<https://inara.cz/elite/inara-api-devguide/>。
- Inara事件文档：<https://inara.cz/elite/inara-api-docs/>。
- FDevIDs维护者说明：<https://github.com/EDCD/FDevIDs>。
- Coriolis数据维护者说明：<https://github.com/EDCD/coriolis-data>。
- EDDN维护者的数据源／归档目录：<https://github.com/EDCD/EDDN/blob/live/README.md>。

整理方法：Context7未检索到相关EDSM项目，未使用其返回的同名无关库；
改用以上原始文档、当前源码及明确列出的只读探测。EDSM文档直读403时，
参数由服务方文档的搜索索引辅助核对，未冒称成功抓取了其完整文档页。
