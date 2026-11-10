import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResourceSearchLabel } from "./ResourceSearchLabel";
import {
  highlightParts,
  RESOURCE_SEARCH_DELAY_MS,
  scheduleResourceSearch,
  searchTerms,
} from "./resourceSearch";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function deferred() {
  let resolve!: (value: string) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<string>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

it("coalesces continuous input into one request and cancels an unsent search", async () => {
  const request = vi.fn(async (query: string) => query);
  const callbacks = { success: vi.fn(), error: vi.fn(), settled: vi.fn() };
  let cancel = () => {};
  for (const query of ["2", "23", "233"]) {
    cancel();
    cancel = scheduleResourceSearch(() => request(query), callbacks);
    await vi.advanceTimersByTimeAsync(40);
  }
  expect(request).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(RESOURCE_SEARCH_DELAY_MS);
  expect(request).toHaveBeenCalledOnce();
  expect(callbacks.success).toHaveBeenCalledExactlyOnceWith("233");
  expect(callbacks.settled).toHaveBeenCalledOnce();
  cancel();
  scheduleResourceSearch(() => request("取消的查询"), callbacks)();
  await vi.runAllTimersAsync();
  expect(request).toHaveBeenCalledOnce();
});

it("aborts the transport and ignores late success, errors and settled callbacks", async () => {
  const old = deferred(),
    latest = deferred();
  const callbacks = { success: vi.fn(), error: vi.fn(), settled: vi.fn() };
  let oldSignal: AbortSignal | undefined;
  const cancel = scheduleResourceSearch((signal) => {
    oldSignal = signal;
    return old.promise;
  }, callbacks);
  await vi.advanceTimersByTimeAsync(RESOURCE_SEARCH_DELAY_MS);
  cancel();
  expect(oldSignal?.aborted).toBe(true);
  const cancelLatest = scheduleResourceSearch(() => latest.promise, callbacks);
  await vi.advanceTimersByTimeAsync(RESOURCE_SEARCH_DELAY_MS);
  latest.resolve("新结果");
  await vi.runAllTimersAsync();
  old.resolve("迟到的旧结果");
  await vi.runAllTimersAsync();
  expect(callbacks.success).toHaveBeenCalledExactlyOnceWith("新结果");
  expect(callbacks.settled).toHaveBeenCalledOnce();
  const failed = deferred();
  const cancelFailed = scheduleResourceSearch(() => failed.promise, callbacks);
  await vi.advanceTimersByTimeAsync(RESOURCE_SEARCH_DELAY_MS);
  cancelFailed();
  failed.reject(new Error("迟到错误"));
  await vi.runAllTimersAsync();
  expect(callbacks.error).not.toHaveBeenCalled();
  expect(callbacks.settled).toHaveBeenCalledOnce();
  cancelLatest();
});

it("reports an active request failure without reusing an old result", async () => {
  const error = new Error("读取失败");
  const callbacks = { success: vi.fn(), error: vi.fn(), settled: vi.fn() };
  scheduleResourceSearch(async () => {
    throw error;
  }, callbacks);
  await vi.runAllTimersAsync();
  expect(callbacks.error).toHaveBeenCalledExactlyOnceWith(error);
  expect(callbacks.success).not.toHaveBeenCalled();
  expect(callbacks.settled).toHaveBeenCalledOnce();
});

it("highlights every literal keyword safely and shows description-only evidence", () => {
  expect(searchTerms("  地质\tData  地质\n ")).toEqual(["地质", "Data"]);
  expect(
    highlightParts("<地质> A+B data", "地质 A+B DATA")
      .filter((part) => part.matched)
      .map((part) => part.text),
  ).toEqual(["地质", "A+B", "data"]);
  const description = renderToStaticMarkup(
    <ResourceSearchLabel
      name="地质图"
      description="…区域有233个采样点…"
      query="地质 233"
    />,
  );
  expect(description).toContain("<mark>地质</mark>图");
  expect(description).toContain("说明：");
  expect(description).toContain("<mark>233</mark>");
  const named = renderToStaticMarkup(
    <ResourceSearchLabel
      name="233地质图"
      description="未命中说明"
      query="233"
    />,
  );
  expect(named).toContain("<mark>233</mark>");
  expect(named).not.toContain("说明：");
  expect(
    renderToStaticMarkup(
      <ResourceSearchLabel name="<script>" query="script" />,
    ),
  ).toContain("&lt;<mark>script</mark>&gt;");
});

it.each([
  {
    name: "当前查询结果",
    query: "新查询",
    accessibleName: "当前查询结果",
  },
  {
    name: "当前查询结果",
    query: "查询",
    accessibleName: "当前查询结果",
  },
  {
    name: '<地质> A&B "资料"',
    query: "地质",
    accessibleName: "&lt;地质&gt; A&amp;B &quot;资料&quot;",
  },
])(
  "keeps the complete accessible name for $name with query $query",
  (entry) => {
    const markup = renderToStaticMarkup(
      <ResourceSearchLabel
        name={entry.name}
        description="有233个采样点"
        query={entry.query}
        details="（矢量）"
      />,
    );
    expect(markup).toContain('role="group"');
    expect(markup).toContain(`aria-label="${entry.accessibleName}"`);
    expect(markup.replace(/<[^>]*>/g, "")).toBe(
      `${entry.accessibleName}（矢量）`,
    );
  },
);
