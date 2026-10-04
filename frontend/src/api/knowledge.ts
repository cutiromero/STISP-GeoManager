import { requestForm, requestJson } from "./client";
import type {
  KnowledgeCheckInput,
  KnowledgeCheckResult,
  KnowledgeEntry,
  KnowledgeEntryInput,
  KnowledgeEntryList,
  KnowledgeDocument,
  KnowledgeDocumentList,
  KnowledgeDocumentSearch,
  KnowledgeWikiList,
} from "./generated/types.gen";

export const knowledgeApi = {
  documents: () =>
    requestJson<KnowledgeDocumentList>("/api/knowledge/documents/"),
  uploadDocument: (body: FormData) =>
    requestForm<KnowledgeDocument>("/api/knowledge/documents/", body),
  retryDocument: (id: number) =>
    requestJson<KnowledgeDocument>(`/api/knowledge/documents/${id}/retry/`, {
      method: "POST",
    }),
  searchDocuments: (query: string) =>
    requestJson<KnowledgeDocumentSearch>("/api/knowledge/documents/search/", {
      method: "POST",
      body: { query, limit: 6 },
    }),
  wiki: () => requestJson<KnowledgeWikiList>("/api/knowledge/wiki/"),
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
