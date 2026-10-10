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
  KnowledgeDomain,
} from "./generated/types.gen";

export const knowledgeApi = {
  documents: (domain?: KnowledgeDomain) =>
    requestJson<KnowledgeDocumentList>(
      `/api/knowledge/documents/${domain ? `?domain=${domain}` : ""}`,
    ),
  uploadDocument: (body: FormData) =>
    requestForm<KnowledgeDocument>("/api/knowledge/documents/", body),
  classifyDocument: (id: number, domain: KnowledgeDomain) =>
    requestJson<KnowledgeDocument>(`/api/knowledge/documents/${id}/`, {
      method: "PATCH",
      body: { domain },
    }),
  retryDocument: (id: number) =>
    requestJson<KnowledgeDocument>(`/api/knowledge/documents/${id}/retry/`, {
      method: "POST",
    }),
  searchDocuments: (query: string, domains?: KnowledgeDomain[]) =>
    requestJson<KnowledgeDocumentSearch>("/api/knowledge/documents/search/", {
      method: "POST",
      body: { query, limit: 6, ...(domains ? { domains } : {}) },
    }),
  wiki: (domain?: KnowledgeDomain) =>
    requestJson<KnowledgeWikiList>(
      `/api/knowledge/wiki/${domain ? `?domain=${domain}` : ""}`,
    ),
  entries: (
    options: {
      q?: string;
      category?: string;
      domain?: KnowledgeDomain;
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
