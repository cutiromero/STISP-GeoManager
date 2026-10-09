# 地矿知识增补（2026-10-09）

本批新增 30 条有公开来源的地矿知识，覆盖斑岩铜矿、火山成因块状硫化物矿床（VMS）、密西西比河谷型铅锌矿床（MVT）、浅成热液金银矿以及两项矿物平衡关系。每条保留适用条件、例外、原文短摘录及定位，可由现有知识检索直接返回。

## 载入方式与数据范围

在项目后端环境、`backend` 目录执行：

```text
python manage.py seed_geology_knowledge --batch geology-20261009 --dry-run
python manage.py seed_geology_knowledge --batch geology-20261009
```

- `--dry-run` 只验证、计数，不写数据库。
- 本批种子为 `backend/apps/knowledge/seed_entries_20261009.json`；30 个 `seedKey` 与原批次互不重合。
- 不带 `--batch` 时仍使用原 `seed_entries.json`，原 20 条种子的内容与范围保持不变。
- 按公开项目（ID 1）和 `seedKey` 查重，只创建不存在的条目。已有知识的全部字段及人工修订保留；重跑本批新增数为 0。
- 完整初次执行仅新增 `knowledge_knowledgeentry` 30 行和 `knowledge_knowledgerevision` 30 行，修订号为 1。SQLite 内部自增序列会随插入更新。条目已部分存在时，按缺少数量新增。
- 复用现有模型及校验，不涉及迁移、API 或权限变更。此命令不创建项目、文档、知识库容器或模型调用任务。
- 全部新条目为 `published`、`ruleKind: none`。知识可检索并用于解释；可执行约束仍由已有明确规则负责。

## 来源与查阅记录

访问日期均为 **2026-10-09**。USGS 来源在其官方网站实际下载或读取；LibreTexts 来源在其教材页面读取。PDF 定位同时给出书内印刷页码和从文件第一页起计数的 PDF 页码。

| 标识 | 来源 | 本次读取与使用范围 |
| --- | --- | --- |
| P | John 等，2010，*Porphyry Copper Deposit Model*，USGS Scientific Investigations Report 2010–5070–B。[官方报告页](https://pubs.usgs.gov/sir/2010/5070/b/)、[全文 PDF](https://pubs.usgs.gov/sir/2010/5070/b/pdf/SIR10-5070B.pdf) | Summary，印刷页 1–6（PDF 15–20）；Spectral Characteristics，印刷页 38（PDF 52）；流体包裹体岩相，印刷页 82（PDF 96）。 |
| V | Shanks 与 Thurston 主编，2012，*Volcanogenic Massive Sulfide Occurrence Model*，USGS Scientific Investigations Report 2010–5070–C。[官方报告页](https://pubs.usgs.gov/sir/2010/5070/c/) | 官方页面 Abstract，涉及海底热液成因、硫化物组合、供矿通道、喷流层、构造环境、蚀变及金属分带。 |
| M | Leach 等，2010，*A Deposit Model for Mississippi Valley-Type Lead-Zinc Ores*，USGS Scientific Investigations Report 2010–5070–A。[官方报告页](https://pubs.usgs.gov/sir/2010/5070/a/) | 官方页面报告概述，涉及碳酸盐容矿、矿物、流体来源、矿体产状、排水缓冲与硅化差异。 |
| E | John 等，2018，*Descriptive Models for Epithermal Gold-Silver Deposits*，USGS Scientific Investigations Report 2010–5070–Q。[DOI](https://doi.org/10.3133/sir20105070Q)、[全文 PDF](https://pubs.usgs.gov/sir/2010/5070/q/sir20105070q.pdf) | 分类讨论印刷页 7（PDF 21）；表 B2，印刷页 10（PDF 24）；图 B2，印刷页 11（PDF 25）；C. Brief Description，印刷页 13（PDF 27）。本报告发表年为 2018，2010 属于报告系列编号。 |
| F | Perkins 等，*Mineralogy*，6.4.4 Feldspathoids。[教材页面](https://geo.libretexts.org/Bookshelves/Geology/Mineralogy_(Perkins_et_al.)/06%3A_Igneous_Rocks_and_Silicate_Minerals/6.04%3A_Silicate_Minerals/6.4.04%3A_Feldspathoids) | 图 6.58–6.61 后的似长石—石英反应式。 |
| A | Perkins 等，*Mineralogy*，8.4.2 Metamorphic Phase Diagrams。[教材页面](https://geo.libretexts.org/Bookshelves/Geology/Mineralogy_(Perkins_et_al.)/08%3A_Metamorphic_Minerals_and_Metamorphic_Rocks/8.04%3A_Metamorphic_Reactions/8.4.02%3A_Metamorphic_Phase_Diagrams) | 图 8.40 后 Al2O3–SiO2–H2O 相图的稳定矿物讨论，以及 Using Phase Diagrams 的适用范围说明。 |

种子中的 `sources` 逐条记录 `title`、`url`、`locator`、`excerpt`。中文正文概括原意，英文摘录保持原文；本次已逐条核对 30 项摘录能在实际读取的来源文本中定位，匹配时仅归一化空白和 PDF 行末断词。

例如，白榴石条目对应原文 “leucite + quartz = orthoclase”；刚玉条目对应 “corundum and quartz cannot be found together”。条目同时保留同阶段、同一平衡域、适用化学体系及温压条件，不将一份矿物名单直接解释为平衡冲突。找矿相关条目区分地质线索、观测异常和经过验证的矿体。

下载 PDF 的 SHA256：

```text
SIR10-5070B.pdf
c2b2bce0eb6f7788fad8c148788790ad43a43f4cffe9efe2d4125a7b82e29e24
sir20105070q.pdf
ff41f276000768ab20f708629ea17a51e7697829dce1d68471e75fa51ba809c3
```

查阅用的网页、PDF 和文本提取物保存在本机忽略目录 `.runtime/kb-expansion-20261009/`，不进入代码仓库。

## 30 条知识目录

| seedKey | 类别 | 标题 | 来源 |
| --- | --- | --- | --- |
| porphyry-copper-arc-setting | 地层与构造 | 斑岩铜矿常与汇聚边缘岩浆弧有关 | P |
| porphyry-copper-disseminated-stockwork | 成矿与蚀变 | 斑岩铜矿可同时呈浸染、细脉和角砾岩胶结物矿化 | P |
| porphyry-potassic-alteration | 成矿与蚀变 | 斑岩钾化蚀变常表现为钾长石和黑云母交代 | P |
| porphyry-sericitic-alteration | 成矿与蚀变 | 斑岩绢云母化常以石英—绢云母—黄铁矿组合出现 | P |
| porphyry-propylitic-alteration | 成矿与蚀变 | 青磐岩化组合常见绿泥石、绿帘石及碳酸盐 | P |
| porphyry-advanced-argillic-leaching | 成矿与蚀变 | 高级泥化记录强烈酸性水解和碱性阳离子淋失 | P |
| porphyry-supergene-copper-enrichment | 成矿与蚀变 | 斑岩铜矿的表生过程可形成淋滤帽与辉铜矿富集带 | P |
| porphyry-fluid-inclusion-paragenesis | 数据质量 | 流体包裹体解释应以同阶段且保存完好的组合为单位 | P |
| porphyry-induced-polarization-nonuniqueness | 数据质量 | 激电异常可帮助追踪浸染硫化物，解释需要地质约束 | P |
| sericite-aloh-swir-absorption | 遥感判读 | 绢云母的 Al–OH 吸收可辅助短波红外蚀变制图 | P |
| vms-seafloor-hydrothermal-formation | 成矿与蚀变 | 火山成因块状硫化物矿床可形成于海底及其附近 | V |
| vms-common-sulfide-minerals | 成矿与蚀变 | VMS 矿石常由黄铁矿、磁黄铁矿及铜铅锌硫化物组成 | V |
| vms-footwall-stringer-feeder | 成矿与蚀变 | VMS 块状矿体下方可见细脉状供矿通道 | V |
| vms-exhalite-marker-horizons | 成矿与蚀变 | 喷流沉积层可超出 VMS 矿体边界 | V |
| vms-extensional-tectonic-settings | 地层与构造 | VMS 常见于海底伸展环境及弧后扩张区 | V |
| vms-hydrothermal-alteration-zonation | 成矿与蚀变 | VMS 围岩可保存绿泥石化和绢云母化等蚀变分带 | V |
| vms-metal-zoning | 成矿与蚀变 | VMS 金属组合及分带应按矿床分别建立 | V |
| mvt-carbonate-platform-hosts | 成矿与蚀变 | 密西西比河谷型铅锌矿主要赋存于台地碳酸盐岩 | M |
| mvt-sphalerite-galena-gangue | 成矿与蚀变 | MVT 常见闪锌矿—方铅矿及碳酸盐脉石组合 | M |
| mvt-basin-brine-transport | 成矿与蚀变 | MVT 成矿流体主要与浓缩海水来源的盆地卤水有关 | M |
| mvt-stratabound-discordant-geometry | 地层与构造 | MVT 可以层控，也可呈穿层和脉状矿体 | M |
| mvt-carbonate-buffering | 成矿与蚀变 | 碳酸盐围岩可缓冲 MVT 矿区排水酸度 | M |
| mvt-silicification-variability | 成矿与蚀变 | 硅化在 MVT 中通常较弱，但部分矿床可较强 | M |
| epithermal-shallow-volcanic-systems | 成矿与蚀变 | 浅成热液金银矿常与近地表火山热液系统有关 | E |
| epithermal-sulfidation-state-classification | 矿物平衡 | 高、低硫化型划分指向硫化状态，不等于硫化物多少 | E |
| epithermal-high-sulfidation-vuggy-quartz | 成矿与蚀变 | 高硫化型系统的残余多孔石英可记录强烈酸性淋滤 | E |
| epithermal-low-sulfidation-vein-textures | 成矿与蚀变 | 低硫化型金银矿常见带状石英和玉髓脉 | E |
| epithermal-steam-heated-overprint | 成矿与蚀变 | 地表蒸汽加热酸性蚀变可覆盖近中性的浅成热液系统 | E |
| leucite-quartz-equilibrium | 矿物平衡 | 白榴石与石英的组合需要限定平衡体系 | F |
| corundum-quartz-equilibrium-domain | 矿物平衡 | 刚玉与石英的稳定组合需按相图与平衡域复核 | A |

类别合计：成矿与蚀变 21，地层与构造 3，矿物平衡 3，数据质量 2，遥感判读 1。

## 验证范围

`backend/tests/integration/test_knowledge_seed_expansion.py` 使用临时测试数据库验证新批次数量和来源字段、旧批次默认行为、试运行零写入、只新增及保留人工字段、重复执行、当前私有项目下仍写公开项目，以及中文/英文别名和自然语言检索。测试数据不进入业务项目。

```text
python -m pytest tests/integration/test_knowledge_seed_expansion.py tests/integration/test_knowledge.py -q
```

2026-10-09 本机验证：上述 16 项测试通过；本次 Python 文件 Ruff 检查通过；Django 系统检查无问题。原 `seed_entries.json` 无差异。

该知识补充自身不新增页面控件；导入后现有知识库列表、类别筛选、关系展示和知识检索可使用这些已发布条目。实际服务器载入情况由发布回执记录。
