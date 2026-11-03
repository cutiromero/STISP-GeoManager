import { describe, expect, it } from "vitest";
import {
  parseShareCheck,
  parseShareInvitation,
  parseShareList,
  parseShareOpen,
  parseSharedPreview,
} from "./shareResponses";
import {
  shareCheck,
  shareInvitation,
  shareList,
  sharedOutput,
  shareTarget,
} from "./sharingTestFixtures";

describe("sharing response boundaries", () => {
  it("accepts the generated contract for a list and one accepted result", () => {
    const list = shareList([shareInvitation()]);
    expect(parseShareList(list)).toBe(list);
    expect(parseShareInvitation(list.items[0])).toBe(list.items[0]);
    expect(parseShareCheck(shareCheck()).eligible).toBe(true);
    expect(
      parseShareOpen({ target: shareTarget(), output: sharedOutput() }).output
        ?.id,
    ).toBe(71);
  });

  it.each([
    null,
    {},
    { canChat: true, canAgent: true },
    { ...shareList(), items: null },
    { ...shareList(), items: [null] },
    { ...shareList(), items: [{ id: 23 }] },
    { ...shareList(), total: "1" },
    { ...shareList(), items: [shareInvitation({ status: "other" as never })] },
    { ...shareList(), items: [{ ...shareInvitation(), target: {} }] },
  ])(
    "rejects an invalid list without passing it into rendering: %j",
    (value) => {
      expect(() => parseShareList(value)).toThrow("分享服务返回内容不完整");
    },
  );

  it("allows an ineligible response without leaking recipient or target", () => {
    expect(
      parseShareCheck({ eligible: false, detail: "暂时无法分享" }).eligible,
    ).toBe(false);
    expect(() => parseShareCheck({ eligible: true, detail: "ok" })).toThrow();
  });

  it("rejects invalid open payloads before metadata or table rendering", () => {
    expect(() =>
      parseShareOpen({ target: {}, output: sharedOutput() }),
    ).toThrow();
    expect(() =>
      parseShareOpen({ target: shareTarget(), output: { id: 71 } }),
    ).toThrow();
    expect(() =>
      parseShareInvitation({ ...shareInvitation(), id: -1 }),
    ).toThrow();
  });

  it("validates table previews before rendering rows", () => {
    const preview = {
      kind: "table",
      metadata: {},
      columns: ["面积"],
      rows: [[2]],
    };
    expect(parseSharedPreview(preview)).toBe(preview);
    expect(() => parseSharedPreview({ kind: "table", rows: null })).toThrow();
    expect(() => parseSharedPreview({ ...preview, rows: [null] })).toThrow();
  });
});
