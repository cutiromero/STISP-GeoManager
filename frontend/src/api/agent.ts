import { requestForm, requestJson } from "./client";
import { ResponseFormatError } from "./responseDiagnostics";
import {
  assertAgentRun,
  assertConversation,
  assertConversationDetail,
  assertConversationList,
  assertRunPoll,
} from "./agentResponse";
import type {
  AgentBootstrap,
  AgentConversation,
  AgentConversationDetail,
  AgentConversationList,
  AgentConversationUpdate,
  AgentRun,
  AgentRunInput,
  AgentRunPoll,
  AgentResourceList,
  AgentAdmin,
  AgentAdminUpdate,
  AgentWorkflow,
  AgentWorkflowInput,
  AgentWorkflowList,
  AgentComputeTaskList,
  AgentAttachment,
  AgentComputeIntentUpdate,
  AgentResearchDemoList,
  AgentResearchDemoSummaryList,
  AgentResearchScenario,
  AgentWorkflowSummaryList,
  AgentResearchIntentUpdate,
  AgentWorkflowReport,
  AgentWorkflowReportPreview,
  AgentWorkflowValidation,
  AgentWorkflowConfirmation,
  AgentWorkflowUpload,
  AgentWorkflowUploadList,
  AgentInteractionUpdate,
  CancelAgentWorkflowData,
} from "./generated/types.gen";

export const agentApi = {
  researchDemos: (
    options: { scenario?: AgentResearchScenario; signal?: AbortSignal } = {},
  ) =>
    requestJson<AgentResearchDemoList>(
      `/api/agent/research-demos/${options.scenario ? `?scenario=${encodeURIComponent(options.scenario)}` : ""}`,
      { signal: options.signal },
    ),
  researchDemoSummaries: (options: { signal?: AbortSignal } = {}) =>
    requestJson<AgentResearchDemoSummaryList>(
      "/api/agent/research-demos/?view=summary",
      options,
    ),
  updateResearchIntent: (id: number, body: AgentResearchIntentUpdate) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/research-intent/`, {
      method: "POST",
      body,
      validate: assertAgentRun,
    }),
  bootstrap: (options: { signal?: AbortSignal } = {}) =>
    requestJson<AgentBootstrap>("/api/agent/bootstrap/", options),
  conversations: (mode: "chat" | "agent", q = "", archived = false) =>
    requestJson<AgentConversationList>(
      `/api/agent/conversations/?${new URLSearchParams({ mode, q, archived: String(archived) })}`,
      { validate: assertConversationList },
    ),
  create: (mode: "chat" | "agent") =>
    requestJson<AgentConversation>("/api/agent/conversations/", {
      method: "POST",
      body: { mode },
      validate: assertConversation,
    }),
  detail: (id: number) =>
    requestJson<AgentConversationDetail>(`/api/agent/conversations/${id}/`, {
      validate: (data) => {
        assertConversationDetail(data);
        if (data.conversation.id !== id)
          throw new ResponseFormatError("conversation.id: request mismatch");
      },
    }),
  update: (id: number, body: AgentConversationUpdate) =>
    requestJson<AgentConversation>(`/api/agent/conversations/${id}/`, {
      method: "PATCH",
      body,
      validate: assertConversation,
    }),
  remove: (id: number) =>
    requestJson<{ detail: string }>(`/api/agent/conversations/${id}/`, {
      method: "DELETE",
    }),
  submit: (id: number, body: AgentRunInput) =>
    requestJson<AgentRun>(`/api/agent/conversations/${id}/runs/`, {
      method: "POST",
      body,
      validate: assertAgentRun,
    }),
  uploadAttachment: (conversationId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return requestForm<AgentAttachment>(
      `/api/agent/conversations/${conversationId}/attachments/`,
      form,
    );
  },
  uploadWorkflowFile: (
    batchId: string,
    file: File,
    onUploadProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    form.append("batchId", batchId);
    form.append("file", file);
    return requestForm<AgentWorkflowUpload>(
      "/api/agent/workflow-uploads/",
      form,
      onUploadProgress ? { onUploadProgress } : {},
    );
  },
  workflowUploads: (batchId: string, options: { signal?: AbortSignal } = {}) =>
    requestJson<AgentWorkflowUploadList>(
      `/api/agent/workflow-uploads/?batchId=${encodeURIComponent(batchId)}`,
      options,
    ),
  deleteWorkflowUpload: (id: string) =>
    requestJson<void>(
      `/api/agent/workflow-uploads/${encodeURIComponent(id)}/`,
      {
        method: "DELETE",
      },
    ),
  poll: (id: number, after = 0) =>
    requestJson<AgentRunPoll>(`/api/agent/runs/${id}/?after=${after}`, {
      validate: (data) => {
        assertRunPoll(data);
        if (data.run.id !== id)
          throw new ResponseFormatError("run.id: request mismatch");
      },
    }),
  cancel: (id: number) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/cancel/`, {
      method: "POST",
      validate: assertAgentRun,
    }),
  answerInteraction: (id: number, body: AgentInteractionUpdate) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/interaction/`, {
      method: "POST",
      body,
      validate: assertAgentRun,
    }),
  computeTasks: (id: number) =>
    requestJson<AgentComputeTaskList>(`/api/agent/runs/${id}/compute-tasks/`),
  computeIntent: (id: number) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/compute-intent/`, {
      validate: assertAgentRun,
    }),
  updateComputeIntent: (id: number, body: AgentComputeIntentUpdate) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/compute-intent/`, {
      method: "POST",
      body,
      validate: assertAgentRun,
    }),
  resources: (q = "", options: { signal?: AbortSignal } = {}) =>
    requestJson<AgentResourceList>(
      `/api/agent/resources/?q=${encodeURIComponent(q)}`,
      options,
    ),
  admin: () => requestJson<AgentAdmin>("/api/agent/admin/"),
  savePolicy: (body: AgentAdminUpdate) =>
    requestJson<AgentAdmin>("/api/agent/admin/", { method: "PUT", body }),
  createWorkflow: (body: AgentWorkflowInput) =>
    requestJson<AgentWorkflow>("/api/agent/workflows/", {
      method: "POST",
      body,
    }),
  workflow: (id: string, options: { signal?: AbortSignal } = {}) =>
    requestJson<AgentWorkflow>(
      `/api/agent/workflows/${encodeURIComponent(id)}/`,
      options,
    ),
  workflowHistory: (options: {
    workflowType: string;
    offset?: number;
    limit?: number;
    signal?: AbortSignal;
  }) =>
    requestJson<AgentWorkflowSummaryList>(
      `/api/agent/workflows/?${new URLSearchParams({
        view: "summary",
        workflowType: options.workflowType,
        offset: String(options.offset ?? 0),
        limit: String(options.limit ?? 20),
      })}`,
      { signal: options.signal },
    ),
  workflowValidation: (id: string) =>
    requestJson<AgentWorkflowValidation>(
      `/api/agent/workflows/${encodeURIComponent(id)}/validation/`,
    ),
  workflowValidationPreview: (id: string, fileKey: string) =>
    requestJson<AgentWorkflowReportPreview>(
      `/api/agent/workflows/${encodeURIComponent(id)}/validation/files/${encodeURIComponent(fileKey)}/preview/`,
    ),
  workflows: (options: { signal?: AbortSignal } = {}) =>
    requestJson<AgentWorkflowList>("/api/agent/workflows/", options),
  confirmWorkflow: (
    id: string,
    planHash: string,
    review?: Pick<
      AgentWorkflowConfirmation,
      "decision" | "feedback" | "selectedSuggestionIds" | "fieldMapping"
    >,
  ) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/confirm/`, {
      method: "POST",
      body: { planHash, ...review },
    }),
  cancelWorkflow: (id: string, body?: CancelAgentWorkflowData["body"]) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/cancel/`, {
      method: "POST",
      ...(body ? { body } : {}),
    }),
  pauseWorkflow: (id: string) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/pause/`, {
      method: "POST",
    }),
  resumeWorkflow: (id: string) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/resume/`, {
      method: "POST",
    }),
  prepareWorkflowReport: (id: string) =>
    requestJson<AgentWorkflowReport>(`/api/agent/workflows/${id}/report/`, {
      method: "POST",
    }),
  previewWorkflowReport: (id: string) =>
    requestJson<AgentWorkflowReportPreview>(
      `/api/agent/workflows/${id}/report/preview/`,
    ),
  importWorkflowReport: (id: string) =>
    requestJson<AgentWorkflowReport>(
      `/api/agent/workflows/${id}/report/import/`,
      {
        method: "POST",
      },
    ),
};
