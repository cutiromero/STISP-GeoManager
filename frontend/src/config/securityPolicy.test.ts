import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("frontend content security policy", () => {
  it("allows Tianditu tiles in both image and connection directives", () => {
    const indexHtml = readFileSync(
      new URL("../../index.html", import.meta.url),
      "utf8",
    );
    const policy = indexHtml.match(
      /http-equiv="Content-Security-Policy"\s+content="([^"]+)"/,
    )?.[1];

    expect(policy).toContain(
      "img-src 'self' data: blob: https://api.mapbox.com " +
        "https://tiles.openfreemap.org https://*.tile.openstreetmap.org " +
        "https://*.tianditu.gov.cn",
    );
    expect(policy).toContain(
      "connect-src 'self' https://api.mapbox.com " +
        "https://tiles.openfreemap.org https://*.tile.openstreetmap.org " +
        "https://*.tianditu.gov.cn",
    );
  });
});
