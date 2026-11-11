import { requestForm, requestJson } from "./client";
import { assertProjectList } from "./projectResponse";
import type {
  ContentArticle,
  ContentArticleInput,
  ContentArticleList,
  ContentAsset,
  ProjectTag,
  ProjectTagInput,
  ProjectTagList,
  ProjectAssignment,
  ProjectFeature,
  ProjectFeatureInput,
  ProjectDeletionPreview,
  ProjectDeletionInput,
  ProjectDeletionResult,
} from "./generated/types.gen";

export type { ContentArticle, ContentArticleInput, ProjectTag };
export const platformApi = {
  projects: () =>
    requestJson<ProjectTagList>("/api/projects/", {
      validate: assertProjectList,
    }),
  createProject: (body: ProjectTagInput) =>
    requestJson<ProjectTag>("/api/projects/", { method: "POST", body }),
  updateProject: (id: number, body: ProjectTagInput) =>
    requestJson<ProjectTag>(`/api/projects/${id}/`, { method: "POST", body }),
  previewProjectDeletion: (id: number, options: { signal?: AbortSignal } = {}) =>
    requestJson<ProjectDeletionPreview>(`/api/projects/${id}/deletion-preview/`, options),
  deleteProject: (id: number, body: ProjectDeletionInput) =>
    requestJson<ProjectDeletionResult>(`/api/projects/${id}/`, { method: "DELETE", body }),
  setProjectFeature: (id: number, key: string, body: ProjectFeatureInput) =>
    requestJson<ProjectTag>(
      `/api/projects/${id}/features/${encodeURIComponent(key)}/`,
      { method: "POST", body },
    ),
  setGlobalProjectFeature: (key: string, enabled: boolean) =>
    requestJson<ProjectFeature>(
      `/api/projects/features/${encodeURIComponent(key)}/`,
      { method: "POST", body: { enabled } },
    ),
  assignment: (id: number) =>
    requestJson<ProjectAssignment>(`/api/projects/assignments/${id}/`),
  assign: (userId: number, projectIds: number[], allowPublicProject: boolean) =>
    requestJson<ProjectAssignment>(`/api/projects/assignments/${userId}/`, {
      method: "POST",
      body: { userId, projectIds, allowPublicProject },
    }),
  articles: (options: Record<string, string | number> = {}) =>
    requestJson<ContentArticleList>(
      `/api/content/articles/?${new URLSearchParams(Object.entries(options).map(([k, v]) => [k, String(v)]))}`,
      { projectTagId: "1" },
    ),
  article: (id: number) =>
    requestJson<ContentArticle>(`/api/content/articles/${id}/`, {
      projectTagId: "1",
    }),
  saveArticle: (id: number | null, body: ContentArticleInput) =>
    requestJson<ContentArticle>(
      id ? `/api/content/articles/${id}/` : "/api/content/articles/",
      {
        method: "POST",
        body,
        projectTagId: "1",
      },
    ),
  discardAsset: (id: number) =>
    requestJson<{ detail: string }>(`/api/content/assets/${id}/`, {
      method: "DELETE",
      projectTagId: "1",
    }),
  uploadAsset: async (id: number, file: File): Promise<ContentAsset> => {
    const body = new FormData();
    body.set("file", file);
    return requestForm<ContentAsset>(
      `/api/content/articles/${id}/assets/`,
      body,
      { projectTagId: 1 },
    );
  },
};
