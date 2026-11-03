import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agentApi } from "./agent";
import { ApiError } from "./client";
import { assertConversationDetail, assertRunPoll } from "./agentResponse";
import {
  RESPONSE_DIAGNOSTICS_KEY,
  recordResponseDiagnostic,
  ResponseFormatError,
} from "./responseDiagnostics";

const conversation = {
  id: 1,
  projectId: 1,
  mode: "agent",
  title: "Private title",
  archived: false,
  createdAt: "2026-11-03",
  updatedAt: "2026-11-03",
};
const run = {
  id: 2,
  conversationId: 1,
  model: "configured",
  status: "succeeded",
  prompt: "Secret prompt",
  answer: "Secret answer",
  detail: "",
  evidence: [],
  attachments: [],
  interaction: null,
  interactionHistory: [],
  createdAt: "2026-11-03",
  updatedAt: "2026-11-03",
};

function response(data: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}
function diagnostics() {
  return JSON.parse(sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY) ?? "[]");
}

describe("agent response boundary", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
  });

  it("accepts real empty history and populated history without rewriting either", async () => {
    for (const runs of [[], [run]]) {
      fetchMock.mockResolvedValue(response({ conversation, runs }));
      expect(await agentApi.detail(1)).toEqual({ conversation, runs });
    }
    expect(diagnostics()).toEqual([]);
  });

  it.each([
    undefined,
    null,
    {},
    "not a list",
    [null],
    [{ ...run, answer: null }],
  ])(
    "rejects invalid runs %j before a caller can overwrite history",
    async (runs) => {
      fetchMock.mockResolvedValue(response({ conversation, runs }));
      await expect(agentApi.detail(1)).rejects.toBeInstanceOf(
        ResponseFormatError,
      );
      expect(diagnostics()).toHaveLength(1);
      expect(diagnostics()[0].issue).toMatch(/runs/);
    },
  );

  it("records actual null vs missing fields and redacts response values", async () => {
    fetchMock.mockResolvedValue(
      response({ conversation, runs: null, token: "secret-token" }),
    );
    await expect(agentApi.detail(1)).rejects.toThrow("当前聊天记录已保留");
    const record = diagnostics()[0];
    expect(record.structure.fields.runs).toEqual({ type: "null" });
    expect(record.structure.fields.conversation.fields.title.type).toBe(
      "string",
    );
    const serialized = JSON.stringify(record);
    for (const secret of [
      "Private title",
      "Secret answer",
      "Secret prompt",
      "secret-token",
    ])
      expect(serialized).not.toContain(secret);
    sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
    fetchMock.mockResolvedValue(response({ conversation }));
    await expect(agentApi.detail(1)).rejects.toThrow();
    expect(diagnostics()[0].structure.fields).not.toHaveProperty("runs");
  });

  it("records content type, final URL, redirect and actual HTML structure on HTTP 200", async () => {
    const html = new Response("<html>Private login page</html>", {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
    Object.defineProperties(html, {
      url: {
        value: "https://login.example/login?token=secret-value&next=%2Fagent",
      },
      redirected: { value: true },
    });
    fetchMock.mockResolvedValue(html);
    await expect(agentApi.detail(1)).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    const record = diagnostics()[0];
    expect(record).toMatchObject({
      contentType: "text/html; charset=utf-8",
      redirected: true,
      finalUrlAvailable: true,
      status: 200,
      structure: { type: "string" },
    });
    expect(new URL(record.finalUrl).pathname).toBe("/login");
    expect(new URL(record.finalUrl).origin).toBe("https://login.example");
    expect(new URL(record.finalUrl).searchParams.get("token")).toBe(
      "[redacted]",
    );
    expect(JSON.stringify(record)).not.toContain("Private login page");
    expect(JSON.stringify(record)).not.toContain("secret-value");
  });

  it("records malformed JSON without storing the parse error body", async () => {
    fetchMock.mockResolvedValue(
      new Response('{"runs":SECRET', {
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(agentApi.detail(1)).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    expect(diagnostics()[0].issue).toBe("invalid_json");
    expect(JSON.stringify(diagnostics())).not.toContain("SECRET");
  });

  it("keeps explicit authorization failures as ApiError instead of treating them as history", async () => {
    fetchMock.mockResolvedValue(
      response({ detail: "已撤权" }, { status: 403 }),
    );
    await expect(agentApi.detail(1)).rejects.toMatchObject({ status: 403 });
    fetchMock.mockResolvedValue(
      new Response("{", {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(agentApi.detail(1)).rejects.toBeInstanceOf(ApiError);
    expect(
      diagnostics().map((item: { status: number }) => item.status),
    ).toEqual([403, 401]);
  });

  it("rejects corrupt list, events and mismatched history without losing valid empty lists", async () => {
    fetchMock.mockResolvedValue(response({ items: null }));
    await expect(agentApi.conversations("agent")).rejects.toThrow();
    expect(() =>
      assertConversationDetail({
        conversation,
        runs: [{ ...run, conversationId: 7 }],
      }),
    ).toThrow();
    expect(() => assertRunPoll({ run, events: null, cursor: 1 })).toThrow();
    expect(() => assertRunPoll({ run, events: [null], cursor: 1 })).toThrow();
    expect(() => assertRunPoll({ run, events: [], cursor: "1" })).toThrow();
    expect(() => assertRunPoll({ run, events: [], cursor: 1 })).not.toThrow();
  });

  it("records a valid-looking response sent for the wrong conversation or task", async () => {
    fetchMock.mockResolvedValue(
      response({ conversation: { ...conversation, id: 7 }, runs: [] }),
    );
    await expect(agentApi.detail(1)).rejects.toThrow();
    expect(diagnostics()[0].issue).toBe("conversation.id: request mismatch");
    fetchMock.mockResolvedValue(response({ run, events: [], cursor: 1 }));
    await expect(agentApi.poll(9)).rejects.toThrow();
    expect(diagnostics()[1].issue).toBe("run.id: request mismatch");
  });

  it("keeps aborted body reads as cancellation without recording a malformed response", async () => {
    const aborted = response(null);
    vi.spyOn(aborted, "json").mockRejectedValue(
      new DOMException("cancelled", "AbortError"),
    );
    fetchMock.mockResolvedValue(aborted);
    await expect(agentApi.detail(1)).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(diagnostics()).toEqual([]);
  });

  it("bounds stored diagnostics and still fails safely when storage is unavailable", async () => {
    for (let i = 0; i < 25; i++) {
      recordResponseDiagnostic(
        "/api/agent/runs/2/",
        response(null),
        null,
        `test:${i}`,
      );
    }
    expect(diagnostics()).toHaveLength(20);
    expect(diagnostics()[0].issue).toBe("test:5");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    fetchMock.mockResolvedValue(response({ runs: null }));
    await expect(agentApi.detail(1)).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
  });
});
