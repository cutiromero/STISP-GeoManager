import type { AgentWorkflowReport } from "../api/generated/types.gen";

export function workflowReport(
  extra: Partial<AgentWorkflowReport> = {},
): AgentWorkflowReport {
  return {
    fileName: "ecology-analysis-report.md",
    label: "生态调查分析报告",
    contentType: "text/markdown",
    sizeBytes: 2048,
    checksum: "a".repeat(64),
    previewUrl: "/api/agent/workflows/example/report/preview/",
    downloadUrl: "/api/agent/workflows/example/report/download/",
    resourceId: null,
    resourceName: "",
    resourceLocation: "",
    canDownload: true,
    canImport: true,
    ...extra,
  };
}
