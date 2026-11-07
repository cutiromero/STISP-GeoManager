import type { ComputeCandidate } from "../api/generated/types.gen";

export const multiElementType = "geology_multi_element_reasoning";
export const genericGeologyType = "geology_generic";
/** Matches the backend's GEOLOGY_PROJECT_CODES: the 核地院 logic-reasoning projects. */
export const logicReasoningProjectCodes = ["02", "demo-geology-reasoning"];
export const isLogicReasoningProject = (code: string | undefined) =>
  Boolean(code && logicReasoningProjectCodes.includes(code));
export const genericGeologyGoal =
  "请检查我上传的地质资料：核对岩性、构造和蚀变是否符合地质规律，按本次确认范围处理有据的规则建议，保留待裁定和例外，最后仅根据修正后资料圈定少量找矿远景目标。";
/** The generic upload workflow reuses the multi-element results and approvals. */
export const isMultiElementFamily = (workflowType: string) =>
  workflowType === multiElementType || workflowType === genericGeologyType;
export const multiElementSegments = [
  { value: "all", label: "综合推理全流程" },
  { value: "lithology", label: "岩性检查与纠偏" },
  { value: "structure", label: "构造复核与交汇重建" },
  { value: "alteration", label: "蚀变判别与找矿远景圈定" },
] as const;

export const multiElementRoles = [
  {
    key: "lithology",
    label: "岩性图",
    kind: "vector",
    match: /海德乌拉.*岩性|模拟识别岩性/i,
  },
  {
    key: "faults",
    label: "构造图",
    kind: "vector",
    match: /海德乌拉.*构造|模拟构造/i,
  },
  {
    key: "coverage",
    label: "研究区范围",
    kind: "vector",
    match: /海德乌拉.*(?:研究区|范围)|综合.*范围/i,
  },
  {
    key: "rules",
    label: "本案例试用规则",
    kind: "table",
    match: /海德乌拉.*规则|综合.*规则/i,
  },
  {
    key: "hematite",
    label: "赤铁矿识别",
    kind: "raster",
    match: /赤铁矿|chitiekuang|hematite/i,
  },
  {
    key: "chlorite",
    label: "绿泥石识别",
    kind: "raster",
    match: /绿泥石|lvnishi|chlorite/i,
  },
  {
    key: "hydromica",
    label: "水云母识别",
    kind: "raster",
    match: /水云母|shuiyunmu|hydromica/i,
  },
  {
    key: "calcite",
    label: "方解石识别",
    kind: "raster",
    match: /方解石|fangjieshi|calcite/i,
  },
  {
    key: "dolomite",
    label: "白云石识别",
    kind: "raster",
    match: /白云石|baiyunshi|dolomite/i,
  },
];

export function multiElementInputIssues(role: string, input: ComputeCandidate) {
  const definition = multiElementRoles.find((entry) => entry.key === role);
  if (!definition || input.kind !== definition.kind) return ["资料类型不匹配"];
  if (definition.kind === "vector") {
    const geometries =
      role === "faults"
        ? ["LineString", "MultiLineString"]
        : ["Polygon", "MultiPolygon"];
    if (
      !input.geometryTypes.length ||
      input.geometryTypes.some((value) => !geometries.includes(value))
    )
      return [role === "faults" ? "需要线矢量构造资料" : "需要面矢量资料"];
  }
  if (
    role === "lithology" &&
    !["feature_id", "name", "geo_sym"].every((field) =>
      input.fields.includes(field),
    )
  )
    return ["岩性图需包含稳定feature_id、名称name和地质代号geo_sym"];
  if (role === "faults" && !input.fields.includes("line_id"))
    return ["构造图需包含稳定line_id"];
  if (
    role === "rules" &&
    ![
      "rule_id",
      "rule_version",
      "knowledge_id",
      "knowledge_revision",
      "params_json",
      "rule_json",
      "units_json",
      "aliases_json",
    ].every((field) => input.fields.includes(field))
  )
    return ["规则表缺少试用知识版本绑定或名称代号映射"];
  if (
    ["inj_id", "inj_type", "fake_type"].some((field) =>
      input.fields.includes(field),
    )
  )
    return ["请使用已登记的分析输入"];
  return [];
}

export function multiElementPrompt(segment: string) {
  const label =
    multiElementSegments.find((item) => item.value === segment)?.label ??
    "综合推理全流程";
  return `请启动五龙沟-海德乌拉地质综合推理，执行${label}（segment=${segment}）。使用当前项目预设的模拟识别岩性、构造输入与遥感矿物识别结果。请实际检索项目地质规则，调用算法测量并解释疑点；逐项建议经我批准后再修改，保留未批准和待裁定项。明确上游成果版本，输出真实地图、前后统计和报告，远景区以构造与蚀变组合为主，结合岩性，保留少量适中目标。`;
}
