# 知识分区与智能体资源选择

## 页面与交互

知识库在原有细分类上新增四个领域：遥感基础、油气管道相关、遥感地质填图逻辑推理、干旱区生态安全治理。原条目、资料原件、来源和修订记录保留，历史内容补充分区归属；可在管理入口修改归属。

智能体输入区显式提供“调用算法”“选择数据”“知识库”三个入口。算法与数据可自动筛选或手选；知识可自动选择、选择一个或多个分区、参考全部或不参考。每轮运行保存选项，重新进入会话后从后台恢复。分区改变检索范围，保持原有项目与个人数据权限。

自动知识范围依据本轮主题和已选择算法确定。例如 NDVI 可同时涉及遥感基础和干旱区生态；油气管道任务也可结合遥感知识。手选算法只允许所选已发布版本，手选数据只允许所选授权资源；缺少必要参数时显示现有参数卡。选择不参考时停止本轮知识工具调用，并隔离带有旧知识引用的历史回答。

“让知识连成线”改为稳定的领域簇和紧凑关系布局，缩小节点，减少默认标签，支持缩放和平移；重点关系在选择节点后展开。真实关系来自条目的主体、关系和客体，分区背景表达归属，不制造科学连接。图谱概览显示部分高关联知识，完整条目仍可按分区和检索发现。

## 本批内容

新增40条公开来源知识，每区10条，采用已有种子载入流程，只新增不存在的标识，保留人工修改。来源摘录经本轮实际读取核对，记录链接、章节或PDF页码、适用条件和例外。条目为资料归纳，不将文本作为计算代码。

| 领域 | 内容举例 | 本批公开来源 |
| --- | --- | --- |
| 遥感基础 | NDVI、NDWI、NDMI，波段对应，反射率尺度，云掩膜与网格对齐 | NASA，USGS产品的Google Earth Engine目录，Sentinel Hub公开方法 |
| 油气管道相关 | 完整性威胁、多源数据、空间风险关联、走廊巡查、洪水与地面运动 | 美国49 CFR管道安全条文，Cornell LII公开文本 |
| 遥感地质填图逻辑推理 | 光谱混淆、矿物组、布尔组合、岩性背景、有效掩膜、独立验证 | USGS Scientific Investigations Map 3190 |
| 干旱区生态安全治理 | NDVI距平和物候，土壤背景，NDMI，干旱类型，火险及土地治理 | NASA，NOAA/NIDIS Drought.gov，UNCCD，Sentinel Hub |

国外管道条文用于技术参考，国内项目依据现行适用规范和业主要求判断。NDVI和NDMI提供监测线索，解释干旱或治理成效时结合气象、水资源和现场资料。

### 主要来源

- [NASA：Measuring Vegetation (NDVI & EVI)](https://science.nasa.gov/earth/earth-observatory/measuring-vegetation-ndvi-evi/)
- [USGS Landsat 8 C2 L2 产品目录](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2)
- [Sentinel-2 Harmonized SR 产品目录](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)
- [Sentinel Hub：NDWI](https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/ndwi/)、[NDMI](https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/ndmi/)、[SAVI](https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/savi/)
- [49 CFR 192.917：管道威胁识别与风险分析](https://www.law.cornell.edu/cfr/text/49/192.917)
- [49 CFR 192.935：预防与缓解](https://www.law.cornell.edu/cfr/text/49/192.935)
- [49 CFR 192.705：巡查](https://www.law.cornell.edu/cfr/text/49/192.705)
- [49 CFR 192.911：完整性管理方案](https://www.law.cornell.edu/cfr/text/49/192.911)
- [Rockwell（2012），USGS SIM 3190](https://pubs.usgs.gov/sim/3190/contents/SIM3190_pam.pdf)
- [Drought.gov：Drought Basics](https://www.drought.gov/what-is-drought/drought-basics)
- [UNCCD：Land Degradation Neutrality](https://www.unccd.int/land-and-life/land-degradation-neutrality/overview)

## 载入与验收

在已配置项目运行环境的backend目录执行迁移后，运行：

```text
python manage.py seed_geology_knowledge --batch knowledge-zones-20261010 --dry-run
python manage.py seed_geology_knowledge --batch knowledge-zones-20261010
```

验收覆盖领域过滤、手选执行约束、不参考模式、历史隔离、文档读取与Wiki权限、种子幂等、来源检索、缩放平移、恢复和窄屏。服务器按冻结提交先候选验收，后正式切换；保留业务内容和模型/WeKnora服务，新增知识与迁移单独核对。
