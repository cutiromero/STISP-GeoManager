import { describe, expect, it } from "vitest";
import { normalizeLocale } from "./index";

describe("locale normalization", () => {
  it.each([
    ["en", "en-US"],
    ["en-GB", "en-US"],
    ["en-US", "en-US"],
    ["zh-CN", "zh-CN"],
    ["zh-Hans", "zh-CN"],
    [undefined, "zh-CN"],
  ])("normalizes %s to %s", (input, expected) => {
    expect(normalizeLocale(input)).toBe(expected);
  });
});
