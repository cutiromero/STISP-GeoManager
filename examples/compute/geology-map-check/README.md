# 地质成果智能检查 1.0.1

输入为当前地图 `features`、完整制图边界及例外资料 `coverage` 和专家规则 `rules`。全部数据由平台的隔离计算 SDK 提供，只读取声明的输入。

- 地图字段：`feature_id,class,name,code,path,formation,region,geologic_age`。class是稳定分类键；同名不同class独立统计，同class的name/code/path须一致。
- 覆盖字段：`coverage_id,role,complete_coverage,no_water,no_uninvestigated,region,source,source_locator`。role为coverage或exclusion。三项前提明确为true且空洞没有例外、位于边界内、被唯一图斑完整包围时，才建议填补。面积只作为小范围筛查上限。
- 规则字段：`rule_id,kind,name,scope,conditions,exceptions,evidence_id,evidence_kind,source,source_locator,region,region_bbox_wgs84,formation,expected_age,knowledge_seed`。fill_gap是project_rule；set_age是dictionary_definition，须匹配地层、地区和适用边界。可附knowledge_id/knowledge_revision以绑定平台知识版本。

输出实际问题CSV、WGS84问题位置GPKG和按class分开的面积统计。问题的geometry_json和bounds_json来自当次计算；修改表兼容feature_id/field/old_value/new_value/evidence_id/rule_id/reason，另需issue_id/kind/input_checksum。input_checksum覆盖当前地图、覆盖资料和全部规则。

fill_gap的feature_id为唯一宿主，field=class、old_value=未分类、new_value=宿主class；操作是填补宿主的空洞，保持其编号与分类。set_age仅更新时代属性。条件不充分时标为needs_review。检查阶段只生成建议和位置，用户批准由平台工作流负责。
