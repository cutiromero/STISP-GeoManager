import { expect, it } from "vitest";
import { formatArea } from "./area";

it("picks one unit per magnitude and drops sub-metre decimals", () => {
  expect(formatArea(812.6)).toBe("813 平方米");
  expect(formatArea(36_160)).toBe("3.62 公顷");
  expect(formatArea(6_934_367.1)).toBe("6.93 km²");
  expect(formatArea(0)).toBe("0 平方米");
});
