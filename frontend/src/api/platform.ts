import { requestJson } from "./client";
import { projectSignal } from "../projects/session";
import type {
  ContentArticle,
  ContentArticleInput,
  ContentArticleList,
  ContentAsset,
  ProjectTag,
  ProjectTagInput,
  ProjectTagList,
  ProjectAssignment,
} from "./generated/types.gen";

export type { ContentArticle, ContentArticleInput, ProjectTag };
export const platformApi = {
  projects: () => requestJson<ProjectTagList>("/api/projects/"),
  createProject: (body: ProjectTagInput) =>
    requestJson<ProjectTag>("/api/projects/", { method: "POST", body }),
  updateProject: (id: number, body: ProjectTagInput) =>
    requestJson<ProjectTag>(`/api/projects/${id}/`, { method: "POST", body }),
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
    const csrf =
      document.cookie
        .split("; ")
        .find((x) => x.startsWith("csrftoken="))
        ?.split("=")[1] ?? "";
    const response = await fetch(`/api/content/articles/${id}/assets/`, {
      method: "POST",
      credentials: "include",
      signal: projectSignal(),
      headers: {
        "X-CSRFToken": decodeURIComponent(csrf),
        "X-Project-Id": "1",
      },
      body,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail ?? "上传失败");
    return result;
  },
};
