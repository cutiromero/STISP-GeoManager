import { fireEvent, render } from "@testing-library/react";
import { expect, it } from "vitest";
import CardCover from "./CardCover";

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
