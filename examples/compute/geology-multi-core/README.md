# 海德乌拉综合地质试用算子

四个职责分别为检查、获批执行、关系重建、前后远景区比较。源码共享，构建包独立：

```powershell
python examples/compute/geology-multi-core/build.py <本机输出目录>
```

每个 ZIP 含 `operator.yaml`、`main.py`、说明及完整核心源码。只有 worker 运行包，Django 请求进程不导入这些算法。

规则输入为 CSV：`rule_id,rule_version,knowledge_id,knowledge_revision,params_json,rule_json,units_json,aliases_json`。单元与别名字典可只在首行填写；重复填写时必须相同。条件参数从当前项目和场景明确绑定的试用知识冻结，原条目保持草拟性质。未启用规则不参与检测。输出带具体规则和知识修订。

岩性需要中性 `feature_id,name,geo_sym`；构造需要中性 `line_id`；制图范围为面。禁止把评价专用的注入标签、参照类别或透露准备过程的编号交给算子。1.1.0起，五类矿物输入为米制投影、北向网格的单波段0/1 TIF；各矿物可以有不同网格。保留每张原栅格的 CRS、transform、范围，以像元中心栅格化岩性单元与研究区，不再将蚀变矢量化。非米制或旋转网格应在输入准备时显式重投影，不静默重采样。

检查保留岩性、构造原有问题表与疑点矢量输出。名称与代号按多对一别名表核验；较老岩体被包围等空间关系只提出复核。构造沿界比例采用去重岩性界线缓冲内的构造线长度/该线长度，同类别内部接缝不算岩性界线。岩性几何不简化。

## 蚀变逐像元协议 alteration-pixels-v1

- 每种矿物输出`<mineral>_hits.tif`（uint8：0无问题，1至5对应A-01至A-05）、`<mineral>_groups.tif`（uint32：0无命中，其余查`group_index.csv`）和`<mineral>_before.tif`。同一像元以A-04、A-01、A-02、A-03、A-05的顺序选择有效规则，避免相反动作覆盖；统计为互斥的最终处置组，不将同一像元重复加总。
- 岩性按`geo_sym`聚合。混合边界先用all_touched筛选，再按像元与不同单元的正面积交集确认；仅触边不算混合。边界像元按中心单元判断、单独归组。未覆盖单元单列为空代号，不推断为碳酸盐背景。
- A-01至A-04沿用冻结单元分组与矿物条件，取消整图斑`dominant_ratio`判断。非碳酸盐/非夹层/非覆盖的已知基岩上的碳酸盐化保留原值，统计为可能热液叠加证据；仍需地质核验。
- A-05对同一矿物、同一单元做8邻域连通分量，分量像元数乘像元面积小于`min_area_m2`才命中，默认降权0.5。不会跨岩性或跨矿物拼接面积。
- 稳定组ID为`AG-`加协议、规则、矿物、单元代号、岩性分组、边界标记、建议动作的SHA-256前24位；不含像元数或模型理由。规则版本、知识修订及全部输入内容由检查快照另行冻结。`group_index.csv`保存组ID、矿物及当次整数索引，整数索引不作为跨运行标识。
- `alteration_summary.csv`字段：`group_id,rule_id,rule_version,knowledge_id,knowledge_revision,mineral,unit_code,rock_group,boundary,suggested_action,status,pixel_count,area_m2,component_count,bbox_json,representatives_json`。bbox与代表分量位置使用对应矿物原CRS；每组最多3个面积最大的代表，含bbox与面积；不保存像元级或图斑级几何、重复规则正文。`issues.csv`中蚀变每组一行，仅使用bbox作为审批导航预览，规则正文由知识引用读取。
- `alteration_quality.csv`每矿物一行：原始、命中、保留像元数和面积、可能热液叠加像元数/面积、边界像元数。检查阶段“保留”即尚未执行删除；执行阶段更新为实际保留数量。像元数按矿物分别统计，叠加矿物不去重为地面唯一像元。
- 执行在任何成果写出前重测并校验完整检查清单、输入快照与批准CSV。按组索引逐像元生成`<mineral>_corrected.tif`（uint8 0/1 COG）、`<mineral>_weight.tif`（float32 0..1 COG）、`<mineral>_changes.tif`（uint8 0未改、1..5规则编码）。未批准组不变；降权取现有权重与批准权重的较小值，不恢复已降低的证据。变更表每获批组一行，含实际变化像元数、面积及组ID；不输出蚀变变更面。
- 远景区使用修正栅格及权重，以average重投影至现有分析网格（默认100 m），累加每种矿物的加权像元比例。新流程不再对蚀变面缓冲；岩性、构造的规则与处理不变。前后计算使用相同范围、网格与阈值。原P-02的`min_types`现在约束加权覆盖比例之和，需结合实际资料重新核查其地质适用性，不能把旧缓冲覆盖结果与新结果直接等同。

执行额外接收完整检查清单和批准 CSV：`issue_id,feature_id,rule_id,rule_version,snapshot_hash,action,target_code,weight,reason`。类别动作 `set_code/reclassify/merge` 精确绑定检查目标；`keep/review/downweight/exclude` 不接受类别目标。允许用户明确不选任何操作，生成零变更版本。所有批准在写入输出前重新检查；输入、规则或批准范围发生变化即停止。

保留、待裁定、降权、剔除分别保存，原始识别资料始终保留。岩性重分类、改代号后与相邻同单元图斑融合，维持覆盖范围并记录涉及对象。岩性、构造仍逐对象批准；蚀变逐组批准，可选择保留、降权或剔除。新工作流只在发布清单声明`alteration_summary`时启用栅格协议；旧任务仍绑定其原算法包与矢量成果，不回写旧快照。

关系输出分开记录真实几何相交与端点延伸推测，不移动构造线。远景区在相同范围、网格、知识与参数下计算前后结果。A类满足加权蚀变组合、构造条件、有利岩性；B类满足蚀变组合及另外至少一项。每区依据链直接统计参与分级的网格条件，背景资料另列，避免把邻近信息误写成满足条件的证据。

零疑点、零交汇或零远景区通过真实统计表及质量报告记录0。对应可选 GPKG 不生成，避免虚构几何或向目录导入空对象。缺少非空交汇成果时远景区计算会明确报错；不会恢复已剔除构造。

1.1.0使用numpy/pandas/geopandas/rasterio/shapely/pyproj及scipy.ndimage。平台现有Conda锁文件含scipy；native worker需先检查实际解释器可导入，缺失时由运维显式安装后再登记运行环境。Docker计算镜像也需重新构建并登记新digest；不将旧digest误报为含新依赖。所有临时和结果路径局限在当前任务输出目录，导入模块不产生文件。
