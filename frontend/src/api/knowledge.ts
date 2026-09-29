import { requestJson } from "./client";
import type {
  KnowledgeCheckInput,
  KnowledgeCheckResult,
  KnowledgeEntry,
  KnowledgeEntryInput,
  KnowledgeEntryList,
} from "./generated/types.gen";

export const knowledgeApi = {
  entries: (
    options: {
      q?: string;
      category?: string;
      offset?: number;
      limit?: number;
      manage?: boolean;
    } = {},
  ) =>
    requestJson<KnowledgeEntryList>(
      `/api/knowledge/entries/?${new URLSearchParams(
        Object.entries(options)
          .filter(([, value]) => value !== undefined)
          .map(([key, value]) => [key, String(value)]),
      )}`,
    ),
  entry: (id: number) =>
    requestJson<KnowledgeEntry>(`/api/knowledge/entries/${id}/`),
  save: (id: number | null, body: KnowledgeEntryInput) =>
    requestJson<KnowledgeEntry>(
      id === null ? "/api/knowledge/entries/" : `/api/knowledge/entries/${id}/`,
      {
        method: id === null ? "POST" : "PATCH",
        body,
      },
    ),
  check: (body: KnowledgeCheckInput) =>
    requestJson<KnowledgeCheckResult>("/api/knowledge/check/", {
      method: "POST",
      body,
    }),
};
