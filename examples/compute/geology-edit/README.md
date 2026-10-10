# 地质调查一致性受约束编辑

入口 `run(context)` 使用平台隔离计算输入/输出路径。输入为 `features` 当前地图、`changes` 有限属性修改表、`surveys` 调查记录及 `rules` 允许使用的结构化规则；算法只读取这四项输入。地图须有唯一非空 `feature_id`、已知CRS和非空面几何。空间核验及校验和在 `working_epsg`（默认32645）米制投影下计算；调查x/y须采用该工作投影。

修改CSV必需字段：`feature_id,field,old_value,new_value,evidence_id,rule_id,reason,input_checksum`。允许修改字段为 `contact_type` 和 `lithology`，一个要素字段每次只有一条修改。`input_checksum` 使用与 `geology-check` 完全相同的规范内容校验：工作CRS、要素编号、规范化几何、接触类型和岩性；按编号排序，因此GeoPackage字节变化或要素行顺序变化不改变内容校验和。检查和编辑须使用同一实际入库资源与同一工作投影；入库坐标规范化后重新检查再提出计划。

规则CSV：`rule_id,field,allowed_values,min_confidence,operation`，新值列表用 `|` 分隔，操作为 `set_attribute`。调查CSV：`feature_id,field,value,confidence,evidence_id,source,x,y,date`；坐标与地图同一投影，证据ID唯一。修改新值须与明确调查值一致，调查对象/字段匹配，点与目标面的距离在 `tolerance_m` 范围内（默认1米），置信度达到规则门槛，来源非空。同一对象存在互相冲突的高置信调查值时保留待复核。

所有修改先完成核对；过期校验和、错误原值、重复修改、非法字段/新值、假证据、低置信度、位置不匹配或缺来源均直接拒绝计划，结果文件生成之前保持输入完整。空修改表可以保留原图并输出零修改统计。

- `corrected.gpkg` 的 `data` 图层保留所有要素、输入CRS和原几何坐标，添加 `change_fields/old/new/reason/evidence/rule`、`check_status`，供地图点击；修改字段显示 `field=value`，未修改要素标为 `unchanged`。
- `changes.csv` 记录实际修改、核实来源、调查置信度、坐标、日期和前后内容校验和。
- `statistics.csv` 记录修改数、正确保留要素数、几何有效性及前后内容校验和。
- `quality.json` 使用平台质量协议。属性核验通过且几何有效时为 `passed`；保留的输入几何仍无效时为 `needs_review`，随后通过几何修复和检查流程处理。

算法完成的是调查资料一致性核对后的有限属性修改。输出生成后重跑 `geology-check`，核实原有问题的实际变化和仍需复核的对象；更复杂的边界、年代或矿物关系依照相应资料及验证规则扩展。
