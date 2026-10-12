import { requestForm, requestJson } from "./client";
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
  AgentResearchIntentUpdate,
  AgentWorkflowReport,
  AgentWorkflowReportPreview,
} from "./generated/types.gen";

export const agentApi = {
  researchDemos: () =>
    requestJson<AgentResearchDemoList>("/api/agent/research-demos/"),
  updateResearchIntent: (id: number, body: AgentResearchIntentUpdate) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/research-intent/`, {
      method: "POST",
      body,
    }),
  bootstrap: () => requestJson<AgentBootstrap>("/api/agent/bootstrap/"),
  conversations: (mode: "chat" | "agent", q = "", archived = false) =>
    requestJson<AgentConversationList>(
      `/api/agent/conversations/?${new URLSearchParams({ mode, q, archived: String(archived) })}`,
    ),
  create: (mode: "chat" | "agent") =>
    requestJson<AgentConversation>("/api/agent/conversations/", {
      method: "POST",
      body: { mode },
    }),
  detail: (id: number) =>
    requestJson<AgentConversationDetail>(`/api/agent/conversations/${id}/`),
  update: (id: number, body: AgentConversationUpdate) =>
    requestJson<AgentConversation>(`/api/agent/conversations/${id}/`, {
      method: "PATCH",
      body,
    }),
  remove: (id: number) =>
    requestJson<{ detail: string }>(`/api/agent/conversations/${id}/`, {
      method: "DELETE",
    }),
  submit: (id: number, body: AgentRunInput) =>
    requestJson<AgentRun>(`/api/agent/conversations/${id}/runs/`, {
      method: "POST",
      body,
    }),
  uploadAttachment: (conversationId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return requestForm<AgentAttachment>(
      `/api/agent/conversations/${conversationId}/attachments/`,
      form,
    );
  },
  poll: (id: number, after = 0) =>
    requestJson<AgentRunPoll>(`/api/agent/runs/${id}/?after=${after}`),
  cancel: (id: number) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/cancel/`, { method: "POST" }),
  computeTasks: (id: number) =>
    requestJson<AgentComputeTaskList>(`/api/agent/runs/${id}/compute-tasks/`),
  computeIntent: (id: number) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/compute-intent/`),
  updateComputeIntent: (id: number, body: AgentComputeIntentUpdate) =>
    requestJson<AgentRun>(`/api/agent/runs/${id}/compute-intent/`, {
      method: "POST",
      body,
    }),
  resources: (q = "") =>
    requestJson<AgentResourceList>(
      `/api/agent/resources/?q=${encodeURIComponent(q)}`,
    ),
  admin: () => requestJson<AgentAdmin>("/api/agent/admin/"),
  savePolicy: (body: AgentAdminUpdate) =>
    requestJson<AgentAdmin>("/api/agent/admin/", { method: "PUT", body }),
  createWorkflow: (body: AgentWorkflowInput) =>
    requestJson<AgentWorkflow>("/api/agent/workflows/", {
      method: "POST",
      body,
    }),
  workflow: (id: string) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/`),
  workflows: () => requestJson<AgentWorkflowList>("/api/agent/workflows/"),
  confirmWorkflow: (id: string, planHash: string) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/confirm/`, {
      method: "POST",
      body: { planHash },
    }),
  cancelWorkflow: (id: string) =>
    requestJson<AgentWorkflow>(`/api/agent/workflows/${id}/cancel/`, {
      method: "POST",
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
