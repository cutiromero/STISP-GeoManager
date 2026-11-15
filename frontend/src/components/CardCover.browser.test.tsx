import { fireEvent, render, waitFor, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import CardCover from "./CardCover";
import { readThumbnail } from "../api/thumbnailReads";

vi.mock("../api/thumbnailReads", () => ({ readThumbnail: vi.fn() }));
beforeEach(() => {
  vi.mocked(readThumbnail).mockReset();
});

it("加载成功、失败和内容更换均不回退原图", () => {
  const view = render(<CardCover thumbnailUrl="/small-v1.webp" alt="封面" />);
  const cover = view.container.querySelector(".card-cover")!;
  const image = view.container.querySelector("img")!;
  expect(cover.getAttribute("data-state")).toBe("placeholder");
  fireEvent.load(image);
  expect(cover.getAttribute("data-state")).toBe("ready");
  fireEvent.error(image);
  expect(view.container.querySelector("img")).toBeNull();
  view.rerender(<CardCover thumbnailUrl="/small-v2.webp" alt="封面" />);
  expect(view.container.querySelector("img")?.getAttribute("src")).toBe(
    "/small-v2.webp",
  );
  expect(cover.getAttribute("data-state")).toBe("placeholder");
  view.unmount();
});

it("waits for a generated thumbnail instead of treating the pending placeholder as a finished image", async () => {
  const bytes = Uint8Array.from(
    atob(
      "UklGRjgAAABXRUJQVlA4ICwAAAAQAwCdASogABQAPrVWpE0nJKOiKAgA4BaJaQDA3BanFAAA/vJB236jwpgAAA==",
    ),
    (value) => value.charCodeAt(0),
  );
  vi.mocked(readThumbnail)
    .mockResolvedValueOnce({ pending: true, blob: null })
    .mockResolvedValueOnce({
      pending: false,
      blob: new Blob([bytes], { type: "image/webp" }),
    });
  const revoke = vi.spyOn(URL, "revokeObjectURL");
  const view = render(
    <CardCover
      thumbnailUrl="/api/catalog/results/1/file/?variant=thumbnail"
      alt="成果小图"
      priority
    />,
  );
  await waitFor(() => expect(readThumbnail).toHaveBeenCalledOnce());
  expect(view.container.querySelector("img")).toBeNull();
  expect(view.container.querySelector(".card-cover")).toHaveAttribute(
    "data-state",
    "placeholder",
  );
  await waitFor(
    () =>
      expect(view.container.querySelector(".card-cover")).toHaveAttribute(
        "data-state",
        "ready",
      ),
    { timeout: 4000 },
  );
  const url = view.container.querySelector("img")!.src;
  expect(url.startsWith("blob:")).toBe(true);
  expect(readThumbnail).toHaveBeenCalledTimes(2);
  const signal = vi.mocked(readThumbnail).mock.calls[0]![1];
  view.unmount();
  expect(signal.aborted).toBe(true);
  expect(revoke).toHaveBeenCalledWith(url);
  revoke.mockRestore();
});

it("shows a clear missing-file state without falling back to the original image", async () => {
  vi.mocked(readThumbnail).mockRejectedValue(
    Object.assign(new Error("missing"), { status: 404 }),
  );
  const view = render(
    <CardCover
      thumbnailUrl="/api/catalog/results/2/file/?variant=thumbnail"
      alt="已清理成果"
      priority
    />,
  );
  expect(await screen.findByText("图片暂不可用")).toBeVisible();
  expect(view.container.querySelector("img")).toBeNull();
  expect(readThumbnail).toHaveBeenCalledOnce();
});
