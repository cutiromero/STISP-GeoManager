import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CardCover from "./CardCover";

describe("CardCover", () => {
  it("预留比例、加载占位并默认懒加载", () => {
    const html = renderToStaticMarkup(
      <CardCover thumbnailUrl="/small.webp" alt="封面" />,
    );
    expect(html).toContain('src="/small.webp"');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('width="640"');
    expect(html).toContain('height="360"');
    expect(html).toContain("aspect-ratio:16 / 9");
    expect(html).toContain('data-state="placeholder"');
  });

  it("没有缩略图时不请求图片", () => {
    const html = renderToStaticMarkup(<CardCover alt="封面" />);
    expect(html).not.toContain("<img");
    expect(html).toContain('aria-label="封面"');
  });

  it("首屏可以显式优先加载", () => {
    expect(
      renderToStaticMarkup(
        <CardCover thumbnailUrl="/small.webp" alt="封面" priority />,
      ),
    ).toContain('loading="eager"');
  });
});
