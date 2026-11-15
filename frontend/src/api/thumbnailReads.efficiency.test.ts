import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readThumbnail } from "./thumbnailReads";

const state = vi.hoisted(() => ({
  project: "1",
  epoch: 1,
  fetch: vi.fn(),
  release: vi.fn(),
  attach: vi.fn((request: Request) => request),
}));
vi.mock("../auth/browserSession", () => ({
  browserSessionEpoch: () => state.epoch,
}));
vi.mock("../projects/session", () => ({
  getActiveProject: () => state.project,
  attachProjectHeader: state.attach,
  fetchProjectRequest: state.fetch,
  releaseProjectResponse: state.release,
}));
beforeEach(() => {
  state.project = "1";
  state.epoch++;
  vi.clearAllMocks();
  vi.stubGlobal("window", { location: { origin: "http://thumbnail.test" } });
});
afterEach(() => vi.unstubAllGlobals());
const url = "/api/catalog/results/1/file/?variant=thumbnail&v=one";
const ready = () =>
  new Response("small-image", {
    headers: { "Content-Type": "image/webp", "X-Thumbnail-Status": "ready" },
  });

it("shares identical in-flight thumbnail reads and releases the scoped body once", async () => {
  state.fetch.mockImplementation(async () => ready());
  const [a, b] = await Promise.all([
    readThumbnail(url, new AbortController().signal),
    readThumbnail(url, new AbortController().signal),
  ]);
  expect(state.fetch).toHaveBeenCalledOnce();
  expect(state.attach).toHaveBeenCalledOnce();
  expect(state.release).toHaveBeenCalledOnce();
  expect(a.blob).toBeInstanceOf(Blob);
  expect(a.blob).not.toBe(b.blob);
});

it("does not cache pending placeholders or failures as successful thumbnails", async () => {
  state.fetch
    .mockResolvedValueOnce(
      new Response("pending", { headers: { "X-Thumbnail-Status": "pending" } }),
    )
    .mockResolvedValueOnce(new Response(null, { status: 403 }))
    .mockResolvedValueOnce(ready());
  expect(await readThumbnail(url, new AbortController().signal)).toEqual({
    pending: true,
    blob: null,
  });
  await expect(
    readThumbnail(url, new AbortController().signal),
  ).rejects.toMatchObject({ status: 403 });
  expect(
    (await readThumbnail(url, new AbortController().signal)).blob,
  ).toBeInstanceOf(Blob);
  expect(state.fetch).toHaveBeenCalledTimes(3);
  expect(state.release).toHaveBeenCalledTimes(3);
});

it("keeps different project and account reads separate", async () => {
  state.fetch.mockImplementation(async () => ready());
  const a = readThumbnail(url, new AbortController().signal);
  state.project = "2";
  const b = readThumbnail(url, new AbortController().signal);
  state.epoch++;
  const c = readThumbnail(url, new AbortController().signal);
  await Promise.all([a, b, c]);
  expect(state.fetch).toHaveBeenCalledTimes(3);
});

it("cancels transport only when the last thumbnail consumer leaves", async () => {
  let signal: AbortSignal | undefined;
  state.fetch.mockImplementation(
    (request: Request) =>
      new Promise((_resolve, reject) => {
        signal = request.signal;
        signal.addEventListener("abort", () => reject(signal!.reason), {
          once: true,
        });
      }),
  );
  const first = new AbortController(),
    second = new AbortController();
  const a = readThumbnail(url, first.signal),
    b = readThumbnail(url, second.signal);
  const rejectedA = expect(a).rejects.toBeDefined(),
    rejectedB = expect(b).rejects.toBeDefined();
  await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledOnce());
  first.abort();
  await rejectedA;
  expect(signal?.aborted).toBe(false);
  second.abort();
  await rejectedB;
  expect(signal?.aborted).toBe(true);
});
