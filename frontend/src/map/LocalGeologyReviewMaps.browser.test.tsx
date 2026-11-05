import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import LocalGeologyReviewMaps from "./LocalGeologyReviewMaps";
import GeologyReviewMaps from "./GeologyReviewMaps";
import {
  beforeReviewMap,
  afterReviewMap,
  reviewDifferences,
} from "./geologyReview.testFixtures";
import reviewStyles from "./geology-review-workspace.css?inline";
import compareStyles from "./geology-workbench-compare.css?inline";

const props = {
  before: beforeReviewMap,
  after: afterReviewMap,
  differences: reviewDifferences,
  bounds: [98.4, 35.6, 98.45, 35.62] as [number, number, number, number],
};

it("routes standalone comparison and explanation maps to the same service-free renderer", () => {
  expect(GeologyReviewMaps).toBe(LocalGeologyReviewMaps);
});

function show(onSelect = vi.fn(), onInspect = vi.fn()) {
  return render(
    <>
      <style>{reviewStyles + compareStyles}</style>
      <LocalGeologyReviewMaps
        {...props}
        onSelect={onSelect}
        onInspect={onInspect}
      />
    </>,
  );
}

function maps() {
  return screen.getAllByRole("group", { name: "本地矢量图层" });
}

it("paints local vectors without token, network, workers or Mapbox branding and reports first-paint cost", async () => {
  const fetch = vi.spyOn(window, "fetch");
  const xhr = vi.spyOn(XMLHttpRequest.prototype, "open");
  const worker = vi.spyOn(window, "Worker");
  try {
    const start = performance.now();
    const { container } = show();
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    const duration = performance.now() - start;
    expect(maps()).toHaveLength(2);
    for (const map of maps()) {
      expect(
        map.querySelector('[data-layer="geological-units"] path'),
      ).toBeVisible();
      expect(
        map.querySelector('[data-layer="geological-units"] path'),
      ).toHaveAttribute("fill-rule", "evenodd");
    }
    expect(fetch).not.toHaveBeenCalled();
    expect(xhr).not.toHaveBeenCalled();
    expect(worker).not.toHaveBeenCalled();
    expect(
      container.querySelector(
        '[class*="mapbox"], a[href*="mapbox"], canvas, image, use',
      ),
    ).toBeNull();
    const requests = performance
      .getEntriesByType("resource")
      .filter(
        (entry) =>
          entry.startTime >= start &&
          /mapbox|tianditu|\/tiles\b|\/styles\b|\.pbf\b/.test(entry.name),
      );
    expect(requests).toHaveLength(0);
    console.info(
      JSON.stringify({
        renderer: "local-svg",
        maps: maps().length,
        basemapRequests: requests.length,
        firstPaintMs: Math.round(duration * 10) / 10,
      }),
    );
  } finally {
    fetch.mockRestore();
    xhr.mockRestore();
    worker.mockRestore();
  }
});

it("synchronizes zoom, pan, reset and selection in both real vector views", () => {
  const select = vi.fn(),
    inspect = vi.fn();
  show(select, inspect);
  const [left, right] = maps();
  const initial = left!.getAttribute("viewBox");
  fireEvent.click(screen.getAllByRole("button", { name: "放大地图" })[0]!);
  expect(left).not.toHaveAttribute("viewBox", initial);
  expect(left!.getAttribute("viewBox")).toBe(right!.getAttribute("viewBox"));
  const zoomed = left!.getAttribute("viewBox");
  fireEvent.keyDown(right!, { key: "ArrowRight" });
  expect(left).not.toHaveAttribute("viewBox", zoomed);
  expect(left!.getAttribute("viewBox")).toBe(right!.getAttribute("viewBox"));
  const panned = left!.getAttribute("viewBox");
  const rectangle = right!.getBoundingClientRect();
  fireEvent.wheel(right!, {
    deltaY: -120,
    clientX: rectangle.left + rectangle.width / 2,
    clientY: rectangle.top + rectangle.height / 2,
  });
  expect(left).not.toHaveAttribute("viewBox", panned);
  expect(left!.getAttribute("viewBox")).toBe(right!.getAttribute("viewBox"));
  fireEvent.click(screen.getAllByRole("button", { name: "重置地图范围" })[1]!);
  expect(left).toHaveAttribute("viewBox", initial);
  const change = left!.querySelector(
    '[data-layer="actual-differences"] [role="button"]',
  )!;
  fireEvent.click(change);
  expect(select).toHaveBeenCalledExactlyOnceWith(0);
  const unit = within(left!).getAllByRole("button", { name: "八宝山组" })[0]!;
  fireEvent.keyDown(unit, { key: "Enter" });
  expect(inspect).toHaveBeenCalledExactlyOnceWith(
    beforeReviewMap.features[0],
    0,
  );
});
