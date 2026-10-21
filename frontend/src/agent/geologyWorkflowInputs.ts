import type { ComputeCandidate } from "../api/generated/types.gen";

export const geologyRequiredFields: Record<string, string[]> = {
  initial_map: [
    "feature_id",
    "class",
    "name",
    "code",
    "path",
    "formation",
    "region",
    "geologic_age",
  ],
  coverage: [
    "coverage_id",
    "role",
    "complete_coverage",
    "no_water",
    "no_uninvestigated",
    "region",
    "source",
    "source_locator",
  ],
  rules: [
    "rule_id",
    "kind",
    "name",
    "scope",
    "conditions",
    "exceptions",
    "evidence_id",
    "evidence_kind",
    "source",
    "source_locator",
    "region",
    "region_bbox_wgs84",
    "formation",
    "expected_age",
    "knowledge_seed",
  ],
};

export const geologyRoleHelp: Record<string, string> = {
  initial_map:
    "待检查的分类面图，包含稳定图斑编号、类别和地层时代。支持 .gpkg、.geojson、.json，Shapefile 请将完整配套打包为 .zip 入库。",
  coverage:
    "本次承诺完整制图的边界及水体、未调查区等例外，用于区分真正漏填和合理空白。支持与地质图相同的面矢量格式，须含覆盖与例外字段。",
  rules:
    "把专家知识转成可执行的检查条件、允许操作与例外，保留来源和知识条目标识。支持 .csv、.tsv、.xls、.xlsx 结构化表格；普通文字文档不作为规则表。",
};

export function geologyInputIssues(
  role: string,
  candidate: ComputeCandidate | undefined,
) {
  if (!candidate) return ["资料不存在或当前不可访问，请重新选择。"];
  const issues: string[] = [];
  const spatial = role !== "rules";
  if (candidate.kind !== (spatial ? "vector" : "table"))
    issues.push(spatial ? "必须选择面矢量资料。" : "必须选择结构化规则表。");
  if (
    spatial &&
    (!candidate.geometryTypes.length ||
      candidate.geometryTypes.some(
        (type) => !["Polygon", "MultiPolygon"].includes(type),
      ))
  )
    issues.push("几何类型须为 Polygon 或 MultiPolygon，不能使用点、线或栅格。");
  const fields = new Set(candidate.fields);
  const missing = (geologyRequiredFields[role] ?? []).filter(
    (field) => !fields.has(field),
  );
  if (missing.length) issues.push(`缺少必需字段：${missing.join("、")}。`);
  return issues;
}

export function geologyWorkflowIssues(
  inputs: Record<string, number>,
  candidates: ComputeCandidate[],
) {
  const labels: Record<string, string> = {
    initial_map: "待检查地质图",
    coverage: "制图范围",
    rules: "专家规则",
  };
  const issues: string[] = [];
  for (const role of Object.keys(geologyRequiredFields)) {
    if (!inputs[role]) continue;
    for (const message of geologyInputIssues(
      role,
      candidates.find((item) => item.id === inputs[role]),
    ))
      issues.push(`${labels[role]}：${message}`);
  }
  const ids = Object.values(inputs).filter(Boolean);
  if (new Set(ids).size !== ids.length)
    issues.push(
      "三个资料角色须分别选择，不能把同一资料重复用作地质图、制图范围或规则。",
    );
  return issues;
}
