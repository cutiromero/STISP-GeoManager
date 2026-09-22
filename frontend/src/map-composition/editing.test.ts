import { describe, expect, it } from "vitest";
import { defaultCompositionLayout, normalizeCompositionLayout } from "./layout";
import { elementOrder, patchElement, translateElements } from "./editing";

describe("composition editing", () => {
  it("moves a selection as a unit and clamps it to the paper", () => {
    const original = defaultCompositionLayout("test", [80, 30, 90, 40]);
    const next = translateElements(original, ["title", "legend"], -1000, 5);
    expect(next.title.xMm).toBe(0);
    expect(next.legend.xMm - next.title.xMm).toBe(
      original.legend.xMm - original.title.xMm,
    );
    expect(next.title.yMm).toBe(original.title.yMm + 5);
  });
  it("preserves locked objects and normalizes old layouts and added text", () => {
    const original = defaultCompositionLayout("test", [80, 30, 90, 40]);
    original.editor.locked = ["title"];
    expect(translateElements(original, ["title"], 5, 5).title).toEqual(
      original.title,
    );
    const loaded = normalizeCompositionLayout(
      {
        title: { text: "saved" },
        extraTexts: [{ ...original.note, id: "text-1" }],
        editor: { order: ["text-1", "unknown", "mapFrame"], locked: [] },
      },
      "fallback",
      [80, 30, 90, 40],
    );
    expect(elementOrder(loaded)[0]).toBe("text-1");
    expect(elementOrder(loaded)).not.toContain("unknown");
    expect(
      patchElement(loaded, "text-1", { text: "new" }).extraTexts[0]?.text,
    ).toBe("new");
  });
});
