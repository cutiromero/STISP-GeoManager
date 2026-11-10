# 算子制作规范

## 一页上手

算子是计算中心登记的不可变 ZIP 包。包根目录包含 `operator.yaml`、`main.py` 和 `README.md`，入口固定为 `run(context)`。科学数据由平台固定为只读输入，算子只向独立输出目录写声明的结果。不要把研究区路径、矿物名单、数据库地址或账号写进算法。

新算子使用 `schemaVersion: 2`，按以下清单制作即可：

1. 写清身份：稳定的 `identifier`、名称、语义化 `version`、用途、作者和平台支持的 `runtime`。
2. 写清能力：从 `check / correct / convert / statistics / infer / map` 选择操作类别，列出作用的数据类型，再说明适用与不适用条件。
3. 按任务角色声明输入，不为每个具体矿物、年份或地区增加一个键。每个输入写 `description`、`fields` 和 `crs`；字段按语义角色声明，可通过提交时的 `fieldMappings` 对应任意真实字段名。无需属性字段的输入使用 `fields: []`。
4. 多个同类输入只声明一个 `repeat` 端口；每份资料带自己的资源编号和真实名称标签。
5. 每个参数写原有类型、合法范围、默认值或必填标记，以及 `help`、`agent.adjustable` 和 `agent.advice`。不能由智能体调整的参数明确设为 `false`。
6. 每个输出写类型、单层文件名、`description`、字段语义和 `final`。中间数据不标为最终科学成果。
7. 在 `errors` 中列出前置条件、错误码、含义和补救类别。可预期失败使用 SDK 报告，不输出 Python traceback 作为调度协议。
8. 写 `resources` 的耗时、内存量级和规模关系；附至少一组小样例 `selfTests`，验证实际入口及输出摘要。

```sh
cd backend
PY=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python
"$PY" manage.py new_operator my-table-copy --directory ../.runtime/operator-work
"$PY" manage.py check_operator ../.runtime/operator-work/my-table-copy
```

`new_operator` 生成可执行的小表格样例，默认关闭智能体调用，拒绝覆盖现有目录。`check_operator` 检查清单、上传包安全约束，并通过 TOML 已配置的计算运行环境执行样例；没有可用环境时失败，不退回 Django 进程执行上传代码。脚本衔接算子必须使用支持专用内核隔离的运行机。

第1版清单仍接受上传并返回升级提示；已经登记的旧清单不因缺少新字段而重新验证或拒绝任务。第2版必须完整填写语义字段与自检。上传只做静态检查，不执行算子代码；发布仍须遵循计算中心的草稿试运行和发布权限要求。

## 完整字段参考

### 身份、运行与包结构

| 字段 | 要求 |
| --- | --- |
| `schemaVersion` | 新算子为整数 `2`；兼容 `1` |
| `identifier` | 1至80字符，小写英文开头，允许数字、`_`、`-`；不随版本变化 |
| `name / description / author` | 名称最多160字；描述最多4000字；作者最多160字 |
| `version` | 第2版为 `主.次.修订`，可带预发布后缀；新增兼容端口递增次版本，说明性补充递增修订版本 |
| `runtime` | `python-geospatial-v1` 或 `python-data-script-v1`；后者只由平台受限解释器执行，不导入包内入口 |
| `timeoutSeconds` | 1至7200秒，缺省1800；实际仍受平台配置上限约束 |
| `deterministic` | 是否确定性执行；影响中断恢复，不代表结果正确性保证 |
| `agent.enabled` | 是否允许智能体调用；省略沿用旧规则，`false` 明确禁止；不授予权限 |
| `qualityReport.file` | 可选有界质量报告，沿用平台既有协议，与普通输出不重名 |
| `inputAdapter / inputScriptBridge` | 沿用现有适配能力与受限脚本端口协议，不另声明另一套转换能力 |

每组输入、参数、输出至多30项。清单最多256 KiB，禁止 YAML 锚点、别名和非有限数值。ZIP 压缩大小最多50 MiB、解压大小最多500 MiB、最多5000项，拒绝路径穿越、链接、重复路径、加密和异常压缩比。不可增加安装命令或任意运行环境标识来绕过平台环境。

### 能力说明 `capabilities`

| 字段 | 要求 |
| --- | --- |
| `operations` | 非空、不重复；`check`检查、`correct`修正、`convert`转换、`statistics`统计、`infer`推断、`map`制图 |
| `dataTypes` | 非空、不重复；作用对象为 `raster / vector / table / image / document / gene / report / archive` |
| `summary` | 简明说明算子做什么，最多2000字 |
| `useWhen` | 什么条件下适合调用，最多2000字 |
| `avoidWhen` | 不适用条件、科学适用边界，最多2000字 |

能力词汇只用于发现和选择，不能替代数据权限或输入实测检查。

### 输入 `inputs[]`

| 字段 | 要求 |
| --- | --- |
| `key / label / kind` | 稳定端口键、显示名称、真实资料类型；输入类型沿用平台已登记的六类资料 |
| `required` | 缺省 `true`；只接受布尔值 |
| `description` | 说明资料含义、有效值、处理状态与限制，最多2000字 |
| `minBands / geometryTypes` | 沿用第1版波段和几何约束 |
| `fields` | 至多100个语义角色，无属性需求时为 `[]` |
| `crs` | 必填；见坐标系规范 |
| `spatial` | 可选；输入包围范围与另一个单输入的关系 |
| `repeat` | 可选；将该端口变为同类资料集合 |

每个 `fields[]` 项：

| 字段 | 要求 |
| --- | --- |
| `role` | 唯一稳定语义标识，例如 `stratum_name`、`abundance`、`fault_azimuth`；小写英文开头，最多64字符 |
| `description` | 角色的真实含义，不以某个文件的列名代替定义 |
| `types` | 非空、不重复的 `string / integer / number / boolean / datetime`；整数可满足 `number` |
| `required` | 必填布尔值；可选角色未绑定时不产生缺失差距 |
| `unit` | 可选精确单位标识，例如 `m`、`degree`、`1`；不自动换算，不因坐标系是米制就猜测属性单位 |
| `min / max` | 可选有限数值范围，仅用于数值类型；值域完整性仍须由算子检查，预检不为此全扫描像元 |
| `parameter` | 可选；关联该输入已有的 `field` 或 `band` 参数，映射将填入对应参数；显式参数冲突时拒绝 |
| `legacyName` | 仅供旧算法迁移，声明其内部规范列名；缺省可从同名实际列绑定。显式映射到其他列时，运行器在临时目录创建字段别名视图，原资料不变。新算法优先直接读取SDK映射 |

栅格字段角色映射到从1开始的波段号；表格、矢量映射到实际列名。`types`、`unit` 使用候选来源实际元信息；类型或单位未知不会被当成符合要求。矢量和表格目前不自动提供可靠的属性单位，需由输入准备阶段形成带单位证据的来源；没有证据时返回 `UNKNOWN_FIELD_UNIT`，不能仅提交一个单位字符串让检查通过。

`crs` 的三种形式：

```yaml
crs: {mode: any}
crs: {mode: projected}
crs: {mode: same_as, input: reference}
```

`projected` 要求真实投影坐标系，不自动承诺米制；需要米制的算子必须进一步检查轴单位。`same_as` 比较解析后的 CRS，不仅比较字符串。参照必须是另一个单输入；参照缺失也构成差距。

空间关系与集合示例：

```yaml
spatial: {relation: within, input: coverage}
repeat: {min: 1, max: 64, labelRequired: true}
```

`relation` 为 `intersects` 或 `within`。预检将来源包围范围转换到参照坐标系后比较，不能替代精确几何相交、覆盖与有效性检查；精确判据在算子内部执行。`repeat` 数量满足 $0 \le min \le max \le 64$，必需集合的 `min` 至少1。标签至多160字，同端口不可重复；整个任务最多128份实际输入。

提交绑定示例：

```json
{
  "inputs": {
    "geology": 12,
    "minerals": [
      {"resourceId": 21, "label": "石英"},
      {"resourceId": 22, "label": "白云石"}
    ]
  },
  "fieldMappings": {
    "geology": {"stratum_name": "地层名称"},
    "minerals__1": {"abundance": 1},
    "minerals__2": {"abundance": 1}
  }
}
```

集合固定为 `端口键__1`、`端口键__2` 等实际输入键，名称保存在 `inputCollections`。映射、集合和参数参与第2版任务幂等摘要；重试保持相同标签和绑定。不要在清单中另外占用集合展开键。

### 参数 `parameters[]`

沿用 `key / label / type / required / default / min / max / choices / input / when / maxLength`。类型为 `integer / number / string / boolean / enum / field / band`。数值必须有限，默认值也必须满足类型与范围。`field / band` 必须引用实际输入；集合成员的参数应由算子通过映射读取，不使用单值字段控件参数代表整个集合。

第2版每个参数还必须有：

```yaml
help: 有效像元覆盖率门槛，取值0至1。
agent:
  adjustable: true
  advice: 只有在数据覆盖证据支持时调整，不得为了输出更多结果而降低可靠性要求。
```

`adjustable` 是调度提示，不替代审批与参数校验；运行时仍校验所有显式参数。字段绑定依据语义证据，不按列名相似度默默猜测。

### 输出 `outputs[]`

沿用 `key / label / kind / file / required`，文件必须是与类型匹配的单层文件名。新增：

- `description`：输出代表什么、判据、单位与适用限制。
- `fields`：字段语义，结构同输入；可用 `name` 指定实际列名，不使用 `parameter` 或 `legacyName`。影像按波段值角色解释，几何型输出说明坐标与几何含义。
- `final`：是否最终交付成果；中间转换结果应为 `false`。`true` 不表示无需人工检查或具备地质真值效力。

### 前置条件和错误 `errors[]`

第2版必须包含1至64项：

```yaml
errors:
  - code: MISSING_NAME
    meaning: 对象名称语义角色尚未绑定。
    precondition: 来源必须提供对象名称。
    remedy: complete_mapping
```

错误码为2至64位大写字母、数字或下划线，字母开头、全表唯一；`PLATFORM_` 前缀保留给平台。补救类别固定为：

| 类别 | 含义 |
| --- | --- |
| `adjust_parameters` | 在已声明边界内调整参数 |
| `convert_input` | 通过已登记转换能力改变格式、字段类型、单位或坐标系 |
| `complete_mapping` | 补充或修正字段/波段语义映射 |
| `replace_data` | 更换来源、缩小规模或补齐真实数据 |
| `human_review` | 需要人判断资料含义、适用条件或科学例外 |
| `unrecoverable` | 本版本或当前条件下不可恢复 |

补救类别是建议，不自动授权执行转换、修改原件或跳过人工批准。`inputAdapter` 中已发布的真实来源/目标类型、`fieldHints`、`fieldTargets` 和 `outputFields` 仍是转换能力事实来源。

### 资源 `resources`

```yaml
resources:
  duration: minutes
  memory: medium
  scaling: 耗时随像元数线性增加；分块处理，峰值内存主要取决于块大小与同时打开的图层。
```

`duration` 为 `seconds / minutes / hours`。`memory` 为 `small / medium / large`，建议分别表示小于512 MiB、约512 MiB至2 GiB、高于2 GiB。`scaling` 说明规模关系和可能退化的情形，最多2000字。资源提示不是容量预留或耗时保证，实际限制来自平台 TOML。

### 自检 `selfTests`

```yaml
selfTests:
  - name: 单行表格
    fixture: selftest/smoke.json
    expect:
      files:
        result.csv: {rows: 1, columns: [title]}
```

每包1至10组；`fixture` 必须是包内安全相对路径，单个 JSON 最多1 MiB。内容为 `inputs`、`parameters` 和可选 `fieldMappings`。为避免携带大型二进制资料，小样例使用以下可移植数据描述，由检查工具生成实际文件：

集合端口的值为以下小样例对象的数组，每个成员附 `label`；`fieldMappings` 使用展开后的 `端口键__序号`。检查工具通过与任务提交相同的集合展开规则生成 `inputCollections`，SDK可直接读取。样例 `parameters` 填入本次入口实际使用的参数值，包括默认值，避免将包内自检依赖于外部表单补全。

- 表格：`kind: table`、`rows` 对象列表；空表须附 `columns`。
- 矢量：`kind: vector`、GeoJSON `features`、`crs`，生成 GeoPackage。
- 栅格：`kind: raster`、`shape: [高, 宽]`、`crs`、六项仿射 `transform`、可选 `dtype / nodata / fill / name / pixels`；单边最多128像元，`pixels` 为 `[行, 列, 值]` 非默认像元列表。每项生成单波段 GeoTIFF。
- 文档或基因：`kind: document / gene` 和 `text`。

期望摘要可包括 `rows`、`columns`、`bands`、`sha256`、`contains`；也可用 `expect: {errorCode: 已声明错误码}` 验证预期失败。成功 `files` 与失败 `errorCode` 二选一。摘要不得引用未声明的输出。样例应包含可以判定成功的实际输出，而不只检查入口可以导入。

## 运行协议与 SDK

### 支持节点内恢复的清单

智能体恢复只使用已发布、`agent.enabled` 允许且当前用户有权使用的版本。`capabilities.operations / dataTypes / summary` 应准确描述操作能力、支持资料和适用限制；替换版本还必须保留原必需输出键和类型，不能用相同能力标签掩盖科学方法差异。字段使用稳定语义 `role`、真实类型、单位、坐标系及明确的映射参数，不能把示范数据的列名当作唯一合法名称。开放类别用具名 `repeat` 集合及其真实数量边界，不枚举固定矿物名单。

每个可调参数明确 `agent.adjustable=true`、有效范围、默认值和 `advice` 中的科学限制；未标记参数不会被智能体自动改动，字段映射也不能绕过关联参数的不可调约束。需要按实际字段改变的映射参数应明确标记可调；补救以实际规范化参数和映射为比较基准，空修改或同值修改不计作有效补救。错误码保持稳定，`meaning / precondition / remedy` 写清资料缺口及可行补救，使节点能区别补映射、转换资料、改参数和必须询问用户的情形。实际任务按规范输出结构化 `failure`，不要只抛含糊文本或将平台故障伪装成数据问题。同一错误码同类补救至多尝试一次，清单应避免把不同根因混成一个泛化错误码。

输出必须可读取并说明含义、字段和限制；非成功或失败文件不作为合同成果。格式、单位或坐标系衔接由已有审核脚本与隔离运行负责，提交到目标算子前仍做真实预检。独立脚本审核与科研人工门禁不会因为清单声称“可恢复”而被省略。

SDK 由平台运行器提供，导入名为 `operator_sdk`；不需要作者复制后端 Django 代码，也不需要新增依赖。共享科学代码仍可在构建 ZIP 时复制到包根目录，运行时不依赖相邻源码目录。

```python
from operator_sdk import fail, field_mapping, repeated_inputs

mapping = field_mapping(context, "source")
sources = repeated_inputs(context, "minerals")
fail(context, "MISSING_NAME", "请绑定对象名称", remedy="complete_mapping", inputs=["source"])
```

`field_mapping` 返回角色到列名/波段号的字典；`repeated_inputs` 返回每个成员的 `key / label / path / fieldMappings`。`fail` 原子写入 `context.output_path("__operator_error.json")` 后抛出终止异常；不要捕获该异常继续生成成功输出。

错误文件 UTF-8 JSON，最多8192字节：

```json
{
  "code": "MISSING_NAME",
  "message": "来源尚未绑定对象名称",
  "inputs": ["source"],
  "parameters": [],
  "remedy": "complete_mapping",
  "details": {"role": "name"}
}
```

`message` 为1至1000字；`inputs` 引用清单端口键，集合报告使用逻辑端口名；`parameters` 引用已声明参数。`details` 为对象，不得包含令牌、主机路径、原始数据或 traceback。平台要求第2版错误码及补救类别与清单一致；格式不符、过大或未知错误码归为 `PLATFORM_INVALID_ERROR`。

旧算法已有 `ValueError / TypeError / KeyError` 校验可用 `diagnosed()(run)` 补充 `INPUT_INVALID / replace_data` 报告；必须在清单中声明该错误码。需要精确可修复建议时，应在原校验边界直接调用 `fail`。SDK 不拦截 `MemoryError` 或未知崩溃来伪造业务错误。

| 平台通用错误码 | 含义 | 补救类别 |
| --- | --- | --- |
| `PLATFORM_CRASH` | 未报告的异常或进程提前退出 | `human_review` |
| `PLATFORM_TIMEOUT` | 超过平台或算子时限 | `adjust_parameters` |
| `PLATFORM_OOM` | 捕获到内存不足，或 Docker 明确报告 OOMKilled | `replace_data` |
| `PLATFORM_INVALID_ERROR` | 状态或错误报告不符合协议 | `unrecoverable` |
| `PLATFORM_VALIDATION` | 平台输入、权限或输出检查失败 | `human_review` |
| `PLATFORM_INTERRUPTED` | worker 中断且未重新排队 | `human_review` |

原生进程被系统强杀但没有可靠 OOM 证据时归为 `PLATFORM_CRASH`，不凭错误文字认定内存不足。任务查询保留人读 `error`，并返回机器读 `failure`；旧任务和成功任务为 `null`。平台写入与查询仍执行原有任务权限，不开放额外错误文件下载入口。

预检失败沿用现有400响应，新增 `gaps`：

```json
{
  "detail": "输入语义预检未通过，请按gaps补齐映射或转换数据",
  "gaps": [{
    "code": "MISSING_ROLE", "input": "source", "role": "stratum_name",
    "field": "", "expected": {"types": ["string"]}, "actual": null,
    "remedy": "complete_mapping"
  }]
}
```

差距码包括 `INPUT_COUNT / MISSING_INPUT / INPUT_KIND / BAND_COUNT / GEOMETRY_TYPE / MISSING_ROLE / MISSING_FIELD / FIELD_TYPE / UNKNOWN_FIELD_TYPE / FIELD_UNIT / UNKNOWN_FIELD_UNIT / FIELD_ALIAS_CONFLICT / CRS_MISMATCH / SPATIAL_RELATION`。先核验资源存在、项目和用户权限，再返回差距；无权限资料不返回字段或 CRS 信息。

## 完整例子：从零制作表格算子

目录：

```text
table-copy/
  operator.yaml
  main.py
  README.md
  selftest/smoke.json
```

`operator.yaml`：

```yaml
schemaVersion: 2
identifier: table-copy
name: 保留字段的表格复制
version: 0.1.0
description: 复制来源表格，保留实际字段名；用于表格链路验证，不执行科学推断。
author: 示例作者
runtime: python-geospatial-v1
agent: {enabled: true}
capabilities:
  operations: [convert]
  dataTypes: [table]
  summary: 生成来源表格的独立副本。
  useWhen: 需要保留列名和行内容的表格副本。
  avoidWhen: 需要单位换算、清洗或科学统计。
inputs:
  - key: source
    label: 来源表格
    kind: table
    required: true
    description: 具有对象名称角色的表格，实际列名由提交者映射。
    crs: {mode: any}
    fields:
      - role: object_name
        description: 对象的名称，不是分类代码。
        types: [string]
        required: true
parameters: []
outputs:
  - key: result
    label: 独立表格副本
    kind: table
    file: result.csv
    required: true
    description: 原表格的逐字节副本，保留全部列和实际名称列名。
    final: false
    fields:
      - role: object_name
        description: 来源对象名称，字段名与输入映射值相同。
        types: [string]
        required: true
errors:
  - code: MISSING_NAME
    meaning: 缺少对象名称角色映射。
    precondition: source必须绑定object_name角色。
    remedy: complete_mapping
resources:
  duration: seconds
  memory: small
  scaling: 流式复制，耗时随输入字节数线性增加，额外内存为常数量级。
selfTests:
  - name: 单行复制
    fixture: selftest/smoke.json
    expect:
      files:
        result.csv: {rows: 1, columns: [title]}
timeoutSeconds: 60
deterministic: true
```

`main.py`：

```python
import shutil

from operator_sdk import fail, field_mapping

OUTPUT_FILE = "result.csv"


def run(context):
    mapping = field_mapping(context, "source")
    if "object_name" not in mapping:
        fail(context, "MISSING_NAME", "请绑定对象名称", remedy="complete_mapping", inputs=["source"])
    shutil.copyfile(context.input_path("source"), context.output_path(OUTPUT_FILE))
```

`selftest/smoke.json`：

```json
{
  "inputs": {"source": {"kind": "table", "rows": [{"title": "样例对象"}]}},
  "parameters": {},
  "fieldMappings": {"source": {"object_name": "title"}}
}
```

`README.md` 说明用途、输入角色、输出含义、依赖的平台运行环境和自检命令。将这四个文件按目录结构压缩，保持清单位于 ZIP 根目录；自检通过后上传新草稿，实际试运行成功再发布。

## 旧端口与开放集合的兼容约定

`geology-multi-check` 保留 `hematite / chlorite / hydromica / calcite / dolomite` 以及权重、类别栈端口，增加可选 `minerals` 集合。旧键提交和计算路径保持不变。

当集合恰好包含五个旧矿物类别时，类别名或带“化”后缀的名称直接映射到原输入端口，仍输出原固定文件；输入路径、科学计算与快照标签均保持旧协议。当包含其他类别或类别子集时，集合须为同 CRS、同尺寸、同仿射变换、同数据类型与同 NoData 的单波段栅格，且不携带额外掩膜；无重采样构建 VRT 后进入既有类别栈协议，输出已声明的 `alteration_stack_*`，名称保存在波段描述中。不同网格或掩膜语义先使用已登记输入适配能力整理，不在该桥接层自动重采样。

集合与旧固定矿物、权重或类别栈不能混用；冲突须明确报告，不通过覆盖来源决定优先级。新算法应直接定义开放集合，不复制这一迁移分支。
