import { describe, expect, it } from "vitest";
import {
  rasterColorToHex8,
  replaceRasterUniqueValueColor,
} from "./SymbolizationEditor";

describe("replaceRasterUniqueValueColor", () => {
  it("updates the selected class by stable array index and preserves alpha", () => {
    const items = [
      { value: 1, label: "裸地/草地", color: "#8aa66b" },
      { value: 8, label: "道路", color: "#5b5b5b" },
    ];

    const result = replaceRasterUniqueValueColor(items, 1, "#f2202080");

    expect(result).toEqual([
      items[0],
      { value: 8, label: "道路", color: "#f2202080" },
    ]);
    expect(items[1]?.color).toBe("#5b5b5b");
  });

  it("serializes the picker alpha channel for backend RGBA rendering", () => {
    expect(rasterColorToHex8({ r: 242, g: 32, b: 32, a: 0.5 })).toBe(
      "#f2202080",
    );
    expect(rasterColorToHex8({ r: 47, g: 125, b: 98, a: 1 })).toBe("#2f7d62ff");
  });
});
