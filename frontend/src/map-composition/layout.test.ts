import { describe, expect, it } from "vitest";
import {
  defaultCompositionLayout,
  normalizeCompositionLayout,
  pagePixelSize,
  panMapBounds,
  suggestedGeographicGridInterval,
  suggestedProjectedGridInterval,
  zoomMapBounds,
} from "./layout";
import {
  applyPaperPreset,
  restoreStandardCompositionLayout,
} from "./layoutPaper";
import { overviewExtentPixelBox } from "./canvasGrid";
import { fitOverviewBounds, tileZoomForTarget } from "./mapImage";
import { compositionIssues } from "./render";

describe("map composition layout", () => {
  it("creates a complete A4 landscape layout", () => {
    const layout = defaultCompositionLayout(
      "胡杨样地专题图",
      [87.4, 43.6, 87.8, 44],
      "数据来源：样地调查",
    );

    expect(layout.title.text).toBe("胡杨样地专题图");
    expect(layout.legend.enabled).toBe(true);
    expect(layout.overview.enabled).toBe(true);
    expect(layout.source.text).toContain("样地调查");
    expect(pagePixelSize(layout)).toEqual({ width: 3508, height: 2480 });
  });

  it("switches to A3 portrait and keeps boxes on the page", () => {
    const base = defaultCompositionLayout("专题图", [80, 35, 90, 45]);
    const layout = applyPaperPreset(base, "A3", "portrait");

    expect(layout.page.widthMm).toBe(297);
    expect(layout.page.heightMm).toBe(420);
    expect(
      compositionIssues(layout, []).some((item) => item.level === "error"),
    ).toBe(false);
  });

  it("does not keep portrait-only positions when switching back to landscape", () => {
    const base = defaultCompositionLayout("专题图", [80, 35, 90, 45]);
    const portrait = applyPaperPreset(base, "A4", "portrait");
    const landscape = applyPaperPreset(portrait, "A4", "landscape");

    expect(
      landscape.legend.yMm + landscape.legend.heightMm,
    ).toBeLessThanOrEqual(landscape.page.heightMm);
    expect(landscape.legend.xMm).toBeGreaterThan(
      landscape.mapFrame.xMm + landscape.mapFrame.widthMm,
    );
    expect(
      compositionIssues(landscape, []).some((item) => item.level === "error"),
    ).toBe(false);
  });

  it("repairs out-of-page boxes from legacy stored layouts", () => {
    const layout = normalizeCompositionLayout(
      {
        page: { preset: "A4", orientation: "landscape" },
        legend: {
          enabled: false,
          xMm: 226,
          yMm: 227,
          widthMm: 59,
          heightMm: 37,
        },
      },
      "专题图",
      [70, 30, 100, 50],
    );

    expect(layout.legend.yMm + layout.legend.heightMm).toBeLessThanOrEqual(210);
    expect(layout.legend.xMm).toBeGreaterThan(
      layout.mapFrame.xMm + layout.mapFrame.widthMm,
    );
  });

  it("restores the standard white layout without losing map content", () => {
    const base = defaultCompositionLayout("专题图", [80, 35, 90, 45]);
    const customized = {
      ...base,
      page: { ...base.page, backgroundColor: "#b03030" },
      title: { ...base.title, text: "自定义标题" },
    };

    const restored = restoreStandardCompositionLayout(customized);

    expect(restored.page.backgroundColor).toBe("#ffffff");
    expect(restored.title.text).toBe("自定义标题");
    expect(restored.mapFrame.bounds).toEqual([80, 35, 90, 45]);
  });

  it("normalizes invalid stored bounds", () => {
    const layout = normalizeCompositionLayout(
      { mapFrame: { bounds: [90, 40, 80, 30] } },
      "专题图",
      [70, 30, 100, 50],
    );

    expect(layout.mapFrame.bounds).toEqual([70, 30, 100, 50]);
  });

  it("pans and zooms the map range while preserving valid bounds", () => {
    expect(panMapBounds([80, 35, 90, 45], 0.1, -0.1)).toEqual([81, 34, 91, 44]);
    expect(zoomMapBounds([80, 35, 90, 45], 0.8)).toEqual([81, 36, 89, 44]);
    expect(panMapBounds([175, 80, 180, 85], 1, 1)[2]).toBe(180);
  });

  it("selects a larger tile zoom for higher target resolution", () => {
    const low = tileZoomForTarget([87, 43, 88, 44], 600, 400);
    const high = tileZoomForTarget([87, 43, 88, 44], 2400, 1600);

    expect(high).toBeGreaterThan(low);
  });

  it("expands overview bounds to contain the main map extent", () => {
    const bounds = fitOverviewBounds(
      [50, 35, 100, 48],
      [72, 18, 135, 55],
      640,
      360,
    );

    expect(bounds[0]).toBeLessThan(50);
    expect(bounds[1]).toBeLessThan(18);
    expect(bounds[2]).toBeGreaterThan(135);
    expect(bounds[3]).toBeGreaterThan(55);
  });

  it("clips overview extent boxes to the inset frame", () => {
    const frame = { x: 10, y: 20, width: 120, height: 70 };
    const extent = overviewExtentPixelBox(
      frame,
      [50, 35, 100, 48],
      [72, 18, 135, 55],
    );

    expect(extent.x).toBeGreaterThanOrEqual(frame.x);
    expect(extent.y).toBeGreaterThanOrEqual(frame.y);
    expect(extent.x + extent.width).toBeLessThanOrEqual(frame.x + frame.width);
    expect(extent.y + extent.height).toBeLessThanOrEqual(
      frame.y + frame.height,
    );
  });

  it("suggests usable grid intervals for local map extents", () => {
    const bounds: [number, number, number, number] = [
      88.3807, 40.1414, 88.3869, 40.1438,
    ];

    expect(suggestedGeographicGridInterval(bounds)).toBe(0.002);
    expect(suggestedProjectedGridInterval(bounds)).toBe(200);
  });
});
