import { expect, it } from "vitest";
import { builtinEnglish } from "./ui";
it("translates built-in display text while preserving custom names and option values", () => {
  expect(builtinEnglish("栅格矢量化")).toBe("Raster polygonization");
  expect(builtinEnglish("附加影像3")).toBe("Additional image 3");
  expect(builtinEnglish("输入影像")).toBe("Input image");
  expect(builtinEnglish("中")).toBe("Medium");
  expect(
    builtinEnglish("栅格矢量化；按任务生成独立结果，保留输入数据。"),
  ).not.toMatch(/[\u3400-\u9fff]/);
  expect(builtinEnglish("实验组自定义数据")).toBe("实验组自定义数据");
});
