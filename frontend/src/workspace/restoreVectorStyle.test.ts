import { expect, it } from "vitest";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import { restoreVectorStyle } from "./restoreVectorStyle";
it("fills concise agent styles without losing required renderer sections", () => {
  const base = cloneDefaultVectorSymbolization();
  const style = restoreVectorStyle(base, {
    fill: { ...base.fill, fillColor: "#abcdef" },
    renderer: { type: "single", updatedByUser: true },
  });
  expect(style.circle.circleRadius).toBe(base.circle.circleRadius);
  expect(style.fill.fillColor).toBe("#abcdef");
  expect(style.symbol).toEqual(base.symbol);
});
it("preserves ordinary complete user snapshots", () => {
  const saved = cloneDefaultVectorSymbolization();
  saved.line.lineWidth = 7;
  saved.opacity = 42;
  expect(restoreVectorStyle(cloneDefaultVectorSymbolization(), saved)).toEqual(
    saved,
  );
});
