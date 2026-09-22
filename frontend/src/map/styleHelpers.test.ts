import type { Map as MapboxMap } from "mapbox-gl";
import { describe, expect, it, vi } from "vitest";
import type { VectorSymbolization } from "../symbolization";
import {
  buildVectorPaintProperties,
  normalizeMapboxColorValue,
  removeStyleLayer,
} from "./styleHelpers";
import { removeLayerGroup } from "./vectorLayerSync";

function makeStyle(
  overrides: Partial<VectorSymbolization> = {},
): VectorSymbolization {
  return {
    opacity: 90,
    pointMode: "circle",
    circle: {
      circleColor: "#d9a441",
      circleRadius: 6,
      circleBlur: 0,
      circleOpacity: 1,
      circlePitchAlignment: "viewport",
      circlePitchScale: "map",
      circleSortKey: 0,
      circleStrokeColor: "#ffffff",
      circleStrokeOpacity: 1,
      circleStrokeWidth: 1.2,
      circleTranslate: [0, 0],
      circleTranslateAnchor: "map",
      circleEmissiveStrength: 0,
    },
    symbol: {
      symbolPlacement: "point",
      symbolSpacing: 250,
      symbolAvoidEdges: false,
      symbolSortKey: 0,
      symbolZOrder: "auto",
      iconImage: "marker-15",
      iconSize: 1,
      iconSizeScaleRange: [0.8, 2],
      iconAllowOverlap: true,
      iconIgnorePlacement: false,
      iconOptional: false,
      iconAnchor: "center",
      iconOffset: [0, 0],
      iconPadding: 2,
      iconKeepUpright: false,
      iconRotate: 0,
      iconPitchAlignment: "auto",
      iconRotationAlignment: "auto",
      iconTextFit: "none",
      iconTextFitPadding: [0, 0, 0, 0],
      iconColor: "#2f7d62",
      iconOpacity: 1,
      iconHaloColor: "#ffffff",
      iconHaloWidth: 0,
      iconHaloBlur: 0,
      iconTranslate: [0, 0],
      iconTranslateAnchor: "map",
      iconEmissiveStrength: 0,
      iconColorBrightnessMin: 0,
      iconColorBrightnessMax: 1,
      iconColorContrast: 0,
      iconColorSaturation: 0,
      iconOcclusionOpacity: 1,
      textField: "",
      textFont: ["Open Sans Regular"],
      textSize: 12,
      textMaxWidth: 10,
      textLineHeight: 1.2,
      textLetterSpacing: 0,
      textJustify: "auto",
      textAnchor: "center",
      textOffset: [0, 1.2],
      textRadialOffset: 0,
      textVariableAnchor: [],
      textWritingMode: ["horizontal"],
      textPadding: 2,
      textKeepUpright: true,
      textAllowOverlap: false,
      textIgnorePlacement: false,
      textOptional: false,
      textRotate: 0,
      textPitchAlignment: "auto",
      textRotationAlignment: "auto",
      textTransform: "none",
      textColor: "#173f39",
      textOpacity: 1,
      textHaloColor: "#ffffff",
      textHaloWidth: 1,
      textHaloBlur: 0,
      textTranslate: [0, 0],
      textTranslateAnchor: "map",
      textEmissiveStrength: 0,
      textOcclusionOpacity: 1,
    },
    line: {
      lineColor: "#174f46",
      lineOpacity: 1,
      lineWidth: 1.4,
      lineBlur: 0,
      lineCap: "round",
      lineJoin: "round",
      lineMiterLimit: 2,
      lineRoundLimit: 1.05,
      lineOffset: 0,
      lineGapWidth: 0,
      lineDasharray: [1, 0],
      lineTranslate: [0, 0],
      lineTranslateAnchor: "map",
      lineEmissiveStrength: 0,
    },
    fill: {
      fillColor: "#2f7d62",
      fillOpacity: 0.72,
      fillOutlineColor: "#174f46",
      fillAntialias: true,
      fillSortKey: 0,
      fillTranslate: [0, 0],
      fillTranslateAnchor: "map",
      fillEmissiveStrength: 0,
    },
    ...overrides,
  };
}

describe("normalizeMapboxColorValue", () => {
  it("converts alpha hex colors recursively into Mapbox-compatible rgba colors", () => {
    expect(normalizeMapboxColorValue("#ffffff2e")).toBe(
      "rgba(255, 255, 255, 0.1804)",
    );
    expect(
      normalizeMapboxColorValue(["match", ["get", "kind"], "forest", "#0f08"]),
    ).toEqual(["match", ["get", "kind"], "forest", "rgba(0, 255, 0, 0.5333)"]);
  });
});

describe("buildVectorPaintProperties", () => {
  it("calculates circle opacity with layer opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0.5);
    expect(result.circleOpacity).toBeCloseTo(0.5);
  });

  it("clamps circle opacity to 0-1", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 2);
    expect(result.circleOpacity).toBe(1);
  });

  it("calculates circle stroke opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0.5);
    expect(result.circleStrokeOpacity).toBeCloseTo(0.5);
  });

  it("calculates symbol icon opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0.5);
    expect(result.symbolIconOpacity).toBeCloseTo(0.5);
  });

  it("calculates symbol text opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0.5);
    expect(result.symbolTextOpacity).toBeCloseTo(0.5);
  });

  it("calculates line opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0.5);
    expect(result.lineOpacity).toBeCloseTo(0.5);
  });

  it("calculates fill opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0.5);
    expect(result.fillOpacity).toBeCloseTo(0.36);
  });

  it("handles zero layer opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 0);
    expect(result.circleOpacity).toBe(0);
    expect(result.lineOpacity).toBe(0);
    expect(result.fillOpacity).toBe(0);
  });

  it("handles full layer opacity", () => {
    const style = makeStyle();
    const result = buildVectorPaintProperties(style, 1);
    expect(result.circleOpacity).toBe(1);
    expect(result.lineOpacity).toBe(1);
    expect(result.fillOpacity).toBeCloseTo(0.72);
  });

  it("respects individual opacity values", () => {
    const style = makeStyle({
      circle: { ...makeStyle().circle, circleOpacity: 0.5 },
      line: { ...makeStyle().line, lineOpacity: 0.3 },
      fill: { ...makeStyle().fill, fillOpacity: 0.8 },
    });
    const result = buildVectorPaintProperties(style, 1);
    expect(result.circleOpacity).toBeCloseTo(0.5);
    expect(result.lineOpacity).toBeCloseTo(0.3);
    expect(result.fillOpacity).toBeCloseTo(0.8);
  });
});

describe("Mapbox style cleanup helpers", () => {
  it("skips style layer removal after the Mapbox style has been destroyed", () => {
    const map = {
      style: undefined,
      getLayer: vi.fn(() => {
        throw new TypeError(
          "Cannot read properties of undefined (reading 'getOwnLayer')",
        );
      }),
      removeLayer: vi.fn(),
    } as unknown as MapboxMap;

    expect(() =>
      removeStyleLayer(map, "query-draw-preview-fill"),
    ).not.toThrow();
    expect(map.getLayer).not.toHaveBeenCalled();
    expect(map.removeLayer).not.toHaveBeenCalled();
  });

  it("skips layer group removal after the Mapbox style has been destroyed", () => {
    const map = {
      style: undefined,
      getLayer: vi.fn(() => {
        throw new TypeError(
          "Cannot read properties of undefined (reading 'getOwnLayer')",
        );
      }),
      getSource: vi.fn(),
      removeLayer: vi.fn(),
      removeSource: vi.fn(),
    } as unknown as MapboxMap;

    expect(() =>
      removeLayerGroup(
        map,
        "query-draw-preview",
        ["query-draw-preview-fill", "query-draw-preview-line"],
        { cleanInteraction: false },
      ),
    ).not.toThrow();
    expect(map.getLayer).not.toHaveBeenCalled();
    expect(map.getSource).not.toHaveBeenCalled();
  });
});
