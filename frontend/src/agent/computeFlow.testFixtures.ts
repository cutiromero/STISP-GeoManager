import type {
  AgentComputeIntent,
  AgentRun,
  ComputeTask,
  ComputeVersion,
} from "../api/generated/types.gen";

export const computeVersion: ComputeVersion = {
  id: 4,
  version: "1.0.0",
  status: "published",
  checksum: "verified",
  runtimeDigest: "verified",
  validated: true,
  createdAt: "2026-10-09",
  manifest: {
    schemaVersion: 1,
    identifier: "ndvi",
    name: "NDVI植被指数",
    version: "1.0.0",
    description: "植被指数",
    author: "平台",
    runtime: "geospatial",
    timeoutSeconds: 60,
    deterministic: true,
    inputs: [
      {
        key: "image",
        label: "输入影像",
        kind: "raster",
        required: true,
        minBands: 2,
      },
    ],
    parameters: [
      {
        key: "red",
        label: "红光波段",
        type: "band",
        required: true,
        input: "image",
        default: 1,
      },
      {
        key: "nir",
        label: "近红外波段",
        type: "band",
        required: true,
        input: "image",
        default: 2,
      },
    ],
    outputs: [
      {
        key: "ndvi",
        label: "NDVI指数栅格",
        kind: "raster",
        file: "ndvi.tif",
        required: true,
      },
    ],
  },
};
export const computeIntent: AgentComputeIntent = {
  status: "collecting",
  message: "请选择红光和近红外波段，随后开始计算。",
  algorithm: computeVersion,
  inputs: { image: 10 },
  parameters: {},
  missingInputs: [],
  missingParameters: ["red", "nir"],
  inputCandidates: [
    {
      id: 10,
      name: "研究区影像",
      kind: "raster",
      projectTagId: 1,
      fields: [],
      bands: 8,
      crs: "EPSG:3857",
      geometryTypes: [],
      sizeBytes: 1024,
    },
    {
      id: 11,
      name: "另一幅影像",
      kind: "raster",
      projectTagId: 1,
      fields: [],
      bands: 4,
      crs: "EPSG:3857",
      geometryTypes: [],
      sizeBytes: 1024,
    },
  ],
  warnings: ["当前影像未标注波段光谱名称，请按资料或您的确认选择。"],
  knowledgeEvidenceIds: [],
  taskId: null,
  autoImport: false,
  planRevision: "checked-plan-1",
};
export function computeRun(
  intent: AgentComputeIntent = computeIntent,
): AgentRun {
  return {
    id: 8,
    conversationId: 1,
    model: "mock",
    status: "succeeded",
    prompt: "计算这张影像的NDVI",
    answer: "",
    detail: "",
    evidence: [],
    attachments: [],
    createdAt: "2026-10-09",
    updatedAt: "2026-10-09",
    contextTruncated: false,
    computeIntent: intent,
  };
}
export function liveComputeTask(
  status: ComputeTask["status"] = "queued",
): ComputeTask {
  return {
    id: "6feaa1a7-4b65-4b3e-849a-9d3f8429f8dc",
    name: "研究区影像 · NDVI",
    projectTagId: 1,
    ownerName: "研究员",
    algorithmName: "NDVI植被指数",
    version: computeVersion,
    status,
    stage: status === "queued" ? "正在等待计算环境" : "计算完成",
    progress: status === "queued" ? 0 : 100,
    error: "",
    parameters: { red: 3, nir: 8 },
    inputs: [{ key: "image", name: "研究区影像", resourceId: 10 }],
    outputs:
      status === "succeeded"
        ? [
            {
              id: 30,
              key: "ndvi",
              label: "NDVI指数栅格",
              kind: "raster",
              fileName: "ndvi.tif",
              sizeBytes: 1024,
              checksum: "verified",
              metadata: { width: 259, height: 260, bands: 1, crs: "EPSG:3857" },
              expired: false,
              importStatus: "none",
              resourceId: null,
              importError: "",
              downloadUrl: "",
              previewUrl: "",
            },
          ]
        : [],
    createdAt: "2026-10-09",
    startedAt: null,
    finishedAt: null,
    trial: false,
    unread: false,
    retryOf: null,
    attemptCount: 1,
  };
}
