# 填图检查（小规则集）

输入为初始地图、调查记录、结构化规则，完全不读取参考图或设错清单。
面要素须有唯一 feature_id、contact_type/lithology 字段及米制投影。检查几何有效性、面重叠以及调查属性一致性。
调查 CSV：feature_id,field,value,confidence,evidence_id,source,x,y,date。坐标必须与地图同一投影。
规则 CSV：rule_id,field,allowed_values,min_confidence,operation。允许值用竖线连接；operation 为 set_attribute。
稳定内容校验包括 CRS、要素编号、规范化几何与审计字段，不受 GeoPackage 导出字节变化影响。
没有研究区边界时不判断缝隙；证据冲突、置信不足或空间不匹配均保留待复核。
