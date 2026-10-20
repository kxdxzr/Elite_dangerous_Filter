# 装备清单独立更新 / Catalogue releases

## 用户

全配件工具的“检查装备清单更新”读取项目GitHub Releases中最新的
`catalog-YYYY.MM.DD.N`标签，而不是应用Release或可随时变化的main分支。
显示版本与维护者的变更摘要，确认后才下载。新版本用于下一次库存数据更新；
已有库存快照、结果、CSV和进行中的查询不改变。没有清单Release时会明确提示。

下载的仅为JSON装备事实及分类，**不执行Python、表达式或插件**。
仅从固定项目GitHub HTTPS地址下载；校验SHA256、数据结构、规则引擎兼容性、
数字ID唯一性、事实与分类的一致性，以及是否有未分类条目。
SHA256用于检测损坏／文件错配，**不是数字签名**；目前信任项目GitHub账号和HTTPS，
尚未实现独立公钥验签。

安装使用同目录临时文件及原子替换，下载、校验失败不会替换有效原版本。
保存`outfitting_release.json`和上一版`outfitting_release.previous.json`，
可点击“回退装备清单”。首次安装的前一版是原目录逻辑；回退后优先用原缓存，
没有原缓存时仍需在线构建，**不是EXE内置完整离线装备事实包**。
新版格式或规则引擎不受支持时拒绝安装，需升级程序。

查询结果记录清单版本、规则版本、事实来源；CSV保留查询时的快照。
清单更新不更新站内库存；手动“更新数据并查询”时通过Spansh／同市场EDSM重新建立库存快照。
普通查询仅本地筛选；“更新数据并查询”本身也不是检查GitHub清单更新。

## 维护者：数据格式 v1

一份清单包含：

```json
{
  "format": 1,
  "engine": 1,
  "version": "2026.10.20.1",
  "built_at": "2026-10-20T00:00:00Z",
  "sources": ["EDCD/FDevIDs@<revision>", "reviewed-rules@<revision>"],
  "ships": ["Sidewinder"],
  "module_facts": [],
  "entries": []
}
```

以上仅为结构示例，空条目不能通过验证。每条`module_facts`必须包含
`ed_id`（正整数）、`ed_symbol`、`name`、`category`、`class`（0至8）、`rating`（A至I），
有挂载／舰船属性时记录`weapon_mode`／`ship`。
`entries`逐数字ID复制对应事实，并增加以下之一的`group`：

| group | 含义 |
|---|---|
| ordinary | 默认普通配件 |
| power | 默认Power配件 |
| ax | AX装备，受AX开关控制 |
| merc | Merc装备，受特殊装备开关控制 |
| armour | 舰船装甲，按所选舰船要求，必须提供ship |
| excluded | 不要求，必须提供reason，建议附source依据 |

两张表的数字ID必须一一对应，规格、身份字段一致；未知分类、重复ID、
遗漏分类或身份冲突均拒绝。新名称可以生效，无需加入旧EXE的名称表。
免费机库在引擎v1中仍明确排除，当前版本也暂不要求Mk II Vessel Hangar及普通／Mk II大型行星车库；通用多功能无人机控制器7A／7C受独立开关控制。不要把免费版ID与付费版合并，也不要把Power或Merc
条目作为普通版别名。Guardian、工程师专售、限定产品等要明确说明排除理由。
AX装备包含2B Extraction Missile；采矿Displacement Missile保留普通分类。

## 发布步骤

1. 在仓库外维护审核过的JSON事实／分类源文件，固定上游来源版本。
2. 更新上游事实后为新增ID补分类；审查删除、改名、规格及类别变化。
3. 使用脚本验证及生成Release资产：

   ```text
   python scripts/build_catalog_release.py reviewed.json output-dir --summary "本次变更说明" --previous previous.json
   ```

   输出`catalog.json`、`catalog-manifest.json`及按ID对比的`catalog-changes.json`。
   必须审核差异；验证器只能证明结构一致，不能证明游戏事实穷尽、正确。
4. 跑单元测试和真实库存回放；对新增排除项、默认必需项和创世正向验收单独检查。
5. 人工发布`catalog-YYYY.MM.DD.N` Release，上传前两个文件，附摘要及数据来源／权利说明。
   标签版本必须与文件版本一致；发布后不覆盖同版本资产，修正应提升版本。
   建议将清单Release标为pre-release，避免它占用应用稳定版latest位置。
6. 用发布版EXE验证实际下载、安装、断网继续使用、回退和版本导出。

检查器读取最近10条Release元数据（不下载10份清单），按清单数字版本选择最新一条；不要让当前清单被10条
后续应用Release埋没。GitHub配额／网络错误直接提示，原清单继续可用。
该功能尚未创建或发布任何清单Release，也没有把下载的第三方事实加入源码仓库。

## English

Manual, data-only updates use versioned `catalog-YYYY.MM.DD.N` GitHub Releases in
the fixed project repository. Confirm the version and summary before installing.
JSON is validated and SHA256-checked, then atomically installed with a previous
version retained. Unsupported formats/engines, unknown groups, duplicate IDs,
unclassified facts and contradictory identities are rejected. No downloaded code
is executed. SHA256 is not a signature: trust currently rests on GitHub and HTTPS.

Use `scripts/build_catalog_release.py` with reviewed source JSON and optionally
`--previous` for a per-ID diff. Publish `catalog.json` and `catalog-manifest.json`
under the matching version tag. Do not replace existing versioned assets. Review
third-party data redistribution terms separately. No catalogue release is created
automatically. No full third-party offline fact database is bundled in the EXE;
rolling back the first update restores the original cache/online-building path.
