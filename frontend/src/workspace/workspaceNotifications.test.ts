import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GeoJsonValidationWarning } from "../types";
import {
  showGeojsonWarnings,
  type AppNotification,
} from "./workspaceNotifications";

const notification = { warning: vi.fn() };
const service = notification as unknown as AppNotification;
const uncertainty: GeoJsonValidationWarning = {
  code: "coordinate_uncertainty",
  minMeters: 0,
  maxMeters: 0,
  ratio: 588.8,
  message: "坐标不确定性差距超过200倍：最小约0.000000米，最大约0.000000米。",
};

beforeEach(() => notification.warning.mockClear());

describe("map coordinate warnings", () => {
  it("loads without a popup for empty or decimal-precision-only warnings", () => {
    showGeojsonWarnings(service);
    showGeojsonWarnings(service, []);
    showGeojsonWarnings(service, [uncertainty]);
    expect(notification.warning).not.toHaveBeenCalled();
  });

  it("keeps missing geometries and out-of-range coordinates visible in a mixed response", () => {
    const qualityWarnings = [
      {
        code: "missing_geometry",
        count: 1,
        message: "已忽略1条不含地理坐标的数据。",
      },
      {
        code: "invalid_longitude",
        count: 2,
        message: "已忽略2条经度越界的数据。",
      },
      {
        code: "invalid_latitude",
        count: 1,
        message: "已忽略1条纬度越界的数据。",
      },
    ];
    const original = [uncertainty, ...qualityWarnings];
    showGeojsonWarnings(service, original);
    expect(notification.warning).toHaveBeenCalledTimes(1);
    const options = notification.warning.mock.calls[0]?.[0];
    const content = renderToStaticMarkup(options.description);
    expect(options.message).toBe("地理坐标数据警告");
    for (const warning of qualityWarnings)
      expect(content).toContain(warning.message);
    expect(content).not.toContain(uncertainty.message);
    expect(options.key).not.toContain("coordinate_uncertainty");
    expect(original).toEqual([uncertainty, ...qualityWarnings]);
  });

  it("preserves other quality warning codes", () => {
    showGeojsonWarnings(service, [
      { code: "invalid_coordinate_format", message: "坐标格式无法识别。" },
    ]);
    const options = notification.warning.mock.calls[0]?.[0];
    expect(renderToStaticMarkup(options.description)).toContain(
      "坐标格式无法识别。",
    );
  });

  it("does not label display simplification or payload notes as coordinate errors", () => {
    showGeojsonWarnings(service, [
      { code: "display_geometry_simplified", message: "线预览已简化" },
      { code: "display_geometry_budget_exceeded", message: "显示体积超过目标" },
    ]);
    expect(notification.warning).not.toHaveBeenCalled();
  });
});
