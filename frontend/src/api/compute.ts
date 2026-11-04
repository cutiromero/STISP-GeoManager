import { requestJson } from "./client";
import {
  assertAlgorithmList,
  assertCandidateList,
  assertComputeOutput,
  assertComputeTask,
  assertComputeTaskList,
} from "./computeResponse";
import { getActiveProject, projectSignal } from "../projects/session";
import type {
  ComputeAlgorithm,
  ComputeAlgorithmList,
  ComputeAlgorithmWrite,
  ComputeCandidateList,
  ComputeCategory,
  ComputeCategoryList,
  ComputeImportRequest,
  ComputeOutput,
  ComputePreflight,
  ComputePreview,
  ComputeMapPreview,
  ComputeRuntimeStatus,
  ComputeTask,
  ComputeTaskCreate,
  ComputeTaskList,
  ComputeVersion,
  DetailResponse,
} from "./generated/types.gen";
export type {
  ComputeAlgorithm,
  ComputeAlgorithmWrite,
  ComputeCandidate,
  ComputeManifest,
  ComputeOutput,
  ComputeParameterSpec,
  ComputeRuntimeStatus,
  ComputeTask,
  ComputeTaskCreate,
  ComputeVersion,
} from "./generated/types.gen";

const query = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
export const computeApi = {
  runtime: () => requestJson<ComputeRuntimeStatus>("/api/compute/runtime/"),
  algorithms: (
    params: Record<string, string | number | undefined> = {},
    options: { signal?: AbortSignal } = {},
  ) =>
    requestJson<ComputeAlgorithmList>(
      `/api/compute/algorithms/?${query(params)}`,
      { ...options, validate: assertAlgorithmList },
    ),
  saveAlgorithm: (id: number | null, body: ComputeAlgorithmWrite) =>
    requestJson<ComputeAlgorithm>(
      `/api/compute/algorithms/${id ? `${id}/` : ""}`,
      { method: "POST", body },
    ),
  deleteAlgorithm: (id: number) =>
    requestJson<DetailResponse>(`/api/compute/algorithms/${id}/`, {
      method: "DELETE",
    }),
  categories: () =>
    requestJson<ComputeCategoryList>("/api/compute/categories/"),
  createCategory: (name: string) =>
    requestJson<ComputeCategory>("/api/compute/categories/", {
      method: "POST",
      body: { id: 0, name, sortOrder: 100 },
    }),
  versionAction: (id: number, action: "publish" | "archive") =>
    requestJson<ComputeVersion>(`/api/compute/versions/${id}/`, {
      method: "POST",
      body: { action },
    }),
  inputs: (
    params: Record<string, string | number | undefined> = {},
    options: { signal?: AbortSignal } = {},
  ) =>
    requestJson<ComputeCandidateList>(`/api/compute/inputs/?${query(params)}`, {
      ...options,
      validate: assertCandidateList,
    }),
  preflight: (body: ComputeTaskCreate) =>
    requestJson<ComputePreflight>("/api/compute/preflight/", {
      method: "POST",
      body,
    }),
  submit: (body: ComputeTaskCreate) =>
    requestJson<ComputeTask>("/api/compute/tasks/", {
      method: "POST",
      body,
      validate: assertComputeTask,
    }),
  tasks: (params: Record<string, string | number | undefined> = {}) =>
    requestJson<ComputeTaskList>(`/api/compute/tasks/?${query(params)}`, {
      validate: assertComputeTaskList,
    }),
  task: (id: string) =>
    requestJson<ComputeTask>(`/api/compute/tasks/${id}/`, {
      validate: assertComputeTask,
    }),
  action: (id: string, action: "cancel" | "retry" | "read") =>
    requestJson<ComputeTask>(`/api/compute/tasks/${id}/`, {
      method: "POST",
      body: { action },
      validate: assertComputeTask,
    }),
  importOutput: (id: number, body: ComputeImportRequest = { name: "" }) =>
    requestJson<ComputeOutput>(`/api/compute/outputs/${id}/import/`, {
      method: "POST",
      body,
      validate: assertComputeOutput,
    }),
  preview: (id: number) =>
    requestJson<ComputePreview>(`/api/compute/outputs/${id}/preview/`),
  mapPreview: (id: number) =>
    requestJson<ComputeMapPreview>(`/api/compute/outputs/${id}/map-preview/`),
  upload: async (id: number, file: File): Promise<ComputeVersion> => {
    const body = new FormData();
    body.set("file", file);
    const csrf =
      document.cookie
        .split("; ")
        .find((x) => x.startsWith("csrftoken="))
        ?.slice(10) ?? "";
    const response = await fetch(`/api/compute/algorithms/${id}/versions/`, {
      method: "POST",
      credentials: "include",
      signal: projectSignal(),
      headers: {
        "X-CSRFToken": decodeURIComponent(csrf),
        "X-Project-Id": getActiveProject(),
      },
      body,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail);
    return result;
  },
};

export async function downloadComputeFile(url: string, filename: string) {
  const response = await fetch(url, {
    credentials: "include",
    signal: projectSignal(),
    headers: { "X-Project-Id": getActiveProject() },
  });
  if (!response.ok) {
    const result = await response.json();
    throw new Error(result.detail);
  }
  const link = document.createElement("a");
  const blob = URL.createObjectURL(await response.blob());
  link.href = blob;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(blob), 1000);
}
