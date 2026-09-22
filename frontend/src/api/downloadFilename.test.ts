import { describe, expect, it } from "vitest";
import { filenameFromHeaders } from "./downloadFilename";

describe("download filenames", () => {
  it("decodes RFC 5987 UTF-8 filenames returned by Django", () => {
    const headers = new Headers({
      "Content-Type": "application/pdf",
      "Content-Disposition":
        "attachment; filename*=utf-8''text2%E4%B8%93%E9%A2%98%E5%9B%BE_V2.pdf",
    });

    expect(filenameFromHeaders(headers)).toBe("text2专题图_V2.pdf");
  });

  it("uses the response content type when no filename header is present", () => {
    expect(
      filenameFromHeaders(new Headers({ "Content-Type": "application/pdf" })),
    ).toBe("map-composition.pdf");
  });
});
