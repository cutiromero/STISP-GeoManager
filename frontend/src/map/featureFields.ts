/** User-facing names and visibility for feature attributes, shared by panel and popup. */
export const priorityFieldLabels: Record<string, readonly [string, string]> = {
  change_old: ["修改前值", "Previous value"],
  change_new: ["修改后值", "Updated value"],
  change_reason: ["修改原因", "Reason for change"],
  change_evidence: ["修改依据", "Change evidence"],
  check_status: ["检查状态", "Check status"],
  change_fields: ["修改字段", "Changed fields"],
  formation: ["地层名称", "Formation"],
  geologic_age: ["地层时代", "Geologic age"],
  source_kind: ["资料性质", "Source type"],
  area_m2: ["面积（平方米）", "Area (square metres)"],
  priority_class: ["调查优先类别", "Survey priority class"],
  priority_rank: ["调查优先顺序", "Survey priority rank"],
  reason: ["判断原因", "Reason"],
  evidence_sources: ["证据来源", "Evidence sources"],
  coverage: ["有效覆盖比例", "Valid coverage fraction"],
  mean_change: ["平均变化值", "Mean change"],
  decline_fraction: ["下降面积占比", "Declining area fraction"],
  name: ["名称", "Name"],
  geo_sym: ["地质代号", "Geologic code"],
  geo_unit: ["地质单元", "Geologic unit"],
  conf: ["分类置信度", "Classification confidence"],
  feature_id: ["图斑编号", "Feature ID"],
  line_id: ["构造编号", "Fault ID"],
  element: ["要素类别", "Element"],
  rule_id: ["命中规则", "Rule"],
  status: ["处理状态", "Status"],
  suggested_action: ["建议处置", "Suggested action"],
  weight: ["证据权重", "Evidence weight"],
  grade: ["优先核查等级", "Priority grade"],
  area_km2: ["面积（平方千米）", "Area (km²)"],
  explanation: ["判断依据", "Explanation"],
};
// Platform bookkeeping and evaluation labels are not attributes users need.
const hiddenFieldNames = new Set([
  "issue_id",
  "inj_id",
  "inj_type",
  "fake_type",
  "uid",
  "snapshot",
  "input_checksum",
]);
export const isHiddenField = (key: string) =>
  key.startsWith("_") || key.endsWith("_json") || hiddenFieldNames.has(key);

const summaryFields = [
  "name",
  "formation",
  "geo_sym",
  "geologic_age",
  "grade",
  "status",
  "priority_class",
  "area_m2",
];

export function fieldLabel(key: string, english = false) {
  return priorityFieldLabels[key]?.[english ? 1 : 0] ?? key;
}

/** Up to four recognisable attributes for a quick look next to the click. */
export function summaryEntries(properties: Record<string, unknown>) {
  const named = summaryFields.filter(
    (key) => properties[key] !== undefined && properties[key] !== "",
  );
  const rest = Object.keys(properties).filter(
    (key) => !named.includes(key) && !isHiddenField(key),
  );
  return [...named, ...rest]
    .slice(0, 4)
    .map((key) => [fieldLabel(key), String(properties[key] ?? "-")] as const);
}
