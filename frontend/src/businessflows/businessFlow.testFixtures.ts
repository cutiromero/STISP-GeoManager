import type {
  BusinessFlowDefinition,
  BusinessFlowDetail,
  BusinessFlowSpec,
  BusinessFlowSummary,
  BusinessFlowVersion,
  BusinessFlowInputPreparation,
  BusinessFlowInputPlan,
} from "../api/generated/types.gen";
export function directInputPlan(
  request: BusinessFlowInputPreparation,
): BusinessFlowInputPlan {
  return {
    ready: true,
    items: Object.entries(request.inputs).map(([role, id]) => {
      const base = role.split(":")[0]!;
      const kind = ["lithology", "structure", "faults", "coverage"].includes(
        base,
      )
        ? "vector"
        : [
              "alteration",
              "hematite",
              "chlorite",
              "hydromica",
              "calcite",
              "dolomite",
              "alterations",
            ].includes(base)
          ? "raster"
          : "table";
      return {
        role,
        sourceId: id,
        sourceName: `资料 ${id}`,
        sourceType: kind,
        sourceRevision: "2026-11-10T00:00:00Z",
        targetTypes: [kind],
        targetSemantics: "",
        status: "direct",
      };
    }),
  };
}
export const researchSpec: BusinessFlowSpec = {
  schemaVersion: 1,
  adapter: "research_flow",
  inputRequirements: [],
  nodes: [
    {
      id: "analyse",
      title: "分析项目资料",
      description: "基于实际资料完成分析。",
      kind: "agent",
      dependsOn: [],
      dataRoles: [],
      instruction: "根据授权资料回答任务，保留来源。",
      review: { ai: false, human: false, maxRevisions: 0 },
    },
    {
      id: "finish",
      title: "交付摘要",
      description: "汇总有依据的结论。",
      kind: "result",
      dependsOn: ["analyse"],
      dataRoles: [],
      instruction: "汇总上游结果。",
      review: { ai: false, human: false, maxRevisions: 0 },
    },
  ],
  outputRequirements: ["有来源依据的资料摘要"],
};
export const geologySpec: BusinessFlowSpec = {
  schemaVersion: 1,
  adapter: "geology_generic",
  inputRequirements: [
    {
      key: "lithology",
      label: "岩性资料",
      description: "覆盖研究区的岩性识别成果。",
      dataTypes: ["vector"],
      required: true,
      requiredFields: ["class"],
    },
    {
      key: "structure",
      label: "构造资料",
      description: "断裂与构造线。",
      dataTypes: ["vector"],
      required: true,
      requiredFields: [],
    },
    {
      key: "alteration",
      label: "蚀变资料",
      description: "蚀变矿物分布。",
      dataTypes: ["raster"],
      required: true,
      requiredFields: [],
    },
  ],
  nodes: [
    {
      id: "inputs",
      title: "确认资料与字段",
      description: "智能体识别资料角色，重要映射由您确认。",
      kind: "agent",
      dependsOn: [],
      dataRoles: ["lithology", "structure", "alteration"],
      instruction: "",
      review: { ai: false, human: true, maxRevisions: 0 },
    },
    {
      id: "check",
      title: "综合检查",
      description: "核对岩性、构造与蚀变关系。",
      kind: "operator",
      dependsOn: ["inputs"],
      dataRoles: ["lithology", "structure", "alteration"],
      instruction: "",
      review: { ai: false, human: false, maxRevisions: 0 },
    },
    {
      id: "apply",
      title: "审核与处置建议",
      description: "独立审核建议和实际依据，处置范围由您批准。",
      kind: "agent",
      dependsOn: ["check"],
      dataRoles: [],
      instruction: "",
      review: { ai: true, human: true, maxRevisions: 1 },
    },
    {
      id: "recheck",
      title: "修正后复核",
      description: "依据批准的处置重新检查。",
      kind: "operator",
      dependsOn: ["apply"],
      dataRoles: [],
      instruction: "",
      review: { ai: false, human: false, maxRevisions: 0 },
    },
    {
      id: "relations",
      title: "重建构造关系",
      description: "依据修正结果重建构造关系。",
      kind: "operator",
      dependsOn: ["recheck"],
      dataRoles: [],
      instruction: "",
      review: { ai: false, human: false, maxRevisions: 0 },
    },
    {
      id: "prospect",
      title: "推算找矿远景区",
      description: "综合构造、蚀变与岩性圈定远景。",
      kind: "operator",
      dependsOn: ["relations"],
      dataRoles: [],
      instruction: "",
      review: { ai: false, human: false, maxRevisions: 0 },
    },
    {
      id: "finish",
      title: "整理报告与成果",
      description: "审核结论与证据，整理成果入口。",
      kind: "result",
      dependsOn: ["prospect"],
      dataRoles: [],
      instruction: "",
      review: { ai: true, human: false, maxRevisions: 1 },
    },
  ],
  outputRequirements: ["综合推理报告", "修正后数据与地图", "找矿远景区"],
};
export const geologyFlow: BusinessFlowDefinition = {
  id: 1,
  projectId: 3,
  ownerId: 2,
  code: "geology_reasoning",
  name: "岩性—构造—蚀变综合推理",
  description:
    "沿专业流程检查三类地质要素，审核处置建议，再形成修正成果与找矿远景区。",
  isActive: true,
  currentVersionId: 11,
  createdAt: "2026-11-09T12:00:00Z",
  updatedAt: "2026-11-09T12:00:00Z",
};
export const researchFlow: BusinessFlowDefinition = {
  ...geologyFlow,
  id: 2,
  code: "project_summary",
  name: "项目资料摘要",
  description: "把当前项目资料整理成有依据的研究摘要，简单任务无需额外审批。",
  currentVersionId: 21,
};
export const geologyVersion: BusinessFlowVersion = {
  id: 11,
  flowId: 1,
  version: 1,
  status: "published",
  definition: geologySpec,
  createdAt: geologyFlow.createdAt,
  publishedAt: geologyFlow.createdAt,
};
export const researchVersion: BusinessFlowVersion = {
  id: 21,
  flowId: 2,
  version: 1,
  status: "published",
  definition: researchSpec,
  createdAt: researchFlow.createdAt,
  publishedAt: researchFlow.createdAt,
};
export const summary = (
  flow: BusinessFlowDefinition,
  version: BusinessFlowVersion,
): BusinessFlowSummary => ({
  ...flow,
  version: version.version,
  nodeCount: version.definition.nodes.length,
  aiReviewCount: version.definition.nodes.filter((node) => node.review.ai)
    .length,
  humanReviewCount: version.definition.nodes.filter(
    (node) => node.review.human || node.kind === "human",
  ).length,
  inputCount: version.definition.inputRequirements.length,
});
export const geologyDetail: BusinessFlowDetail = {
  flow: geologyFlow,
  version: geologyVersion,
  versions: [geologyVersion],
  canManage: false,
};
export const researchDetail: BusinessFlowDetail = {
  flow: researchFlow,
  version: researchVersion,
  versions: [researchVersion],
  canManage: false,
};

export function businessFlowRun(
  extra: Partial<import("../api/generated/types.gen").BusinessFlowRun> = {},
): import("../api/generated/types.gen").BusinessFlowRun {
  const spec = {
    ...researchSpec,
    nodes: researchSpec.nodes.map((node, index) =>
      index === 0
        ? { ...node, review: { ai: true, human: true, maxRevisions: 1 } }
        : node,
    ),
  };
  return {
    id: "00000000-0000-4000-8000-000000000001",
    flowId: 2,
    versionId: 21,
    projectId: 3,
    conversationId: 31,
    runId: 41,
    name: "项目资料审阅",
    goal: "根据资料整理可信的研究线索。",
    status: "waiting_approval",
    currentNode: "analyse",
    definitionSnapshot: spec,
    revision: 4,
    createdAt: "2026-11-10T00:00:00Z",
    updatedAt: "2026-11-10T00:01:00Z",
    nodes: spec.nodes.map((node, index) => ({
      nodeId: node.id,
      status: index === 0 ? "waiting_human" : "pending",
      attempt: index === 0 ? 1 : 0,
      executor:
        index === 0
          ? {
              status: "succeeded",
              model: "executor",
              answer: "执行结果已核对真实资料。",
            }
          : { status: "pending" },
      reviewer:
        index === 0
          ? {
              status: "passed",
              model: "reviewer",
              reason: "引用与结果相符。",
              decision: "accept",
            }
          : { status: "not_required" },
      human: {
        required: index === 0,
        status: index === 0 ? "pending" : "not_required",
        reason: index === 0 ? "此处需要用户明确批准。" : "",
      },
      outputs: {},
    })),
    events: [
      {
        id: 1,
        nodeId: "analyse",
        actor: "executor",
        kind: "node_executed",
        status: "reviewing",
        message: "执行分析已形成，交给独立审核。",
        createdAt: "2026-11-10T00:00:30Z",
      },
      {
        id: 2,
        nodeId: "analyse",
        actor: "reviewer",
        kind: "review_passed",
        status: "waiting_approval",
        message: "审核通过，仍需用户批准。",
        createdAt: "2026-11-10T00:01:00Z",
      },
    ],
    ...extra,
  };
}
