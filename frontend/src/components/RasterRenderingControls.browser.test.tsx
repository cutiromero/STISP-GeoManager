import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LayerContext, type LayerContextValue } from "../hooks/LayerContext";
import { cloneDefaultRasterSymbolization } from "../symbolization";
import type { LoadedRasterLayer } from "../types";
import { setLocale } from "../i18n";
import RasterRenderingControls from "./RasterRenderingControls";

const apply = vi.fn();
const renderRaster = vi.fn();
const bands = [
  { band: 1, label: "波段1" },
  { band: 2, label: "波段2" },
  { band: 3, label: "波段3" },
];
function show(canEdit = true, loaded = true, bandOptions = bands) {
  const value = cloneDefaultRasterSymbolization();
  const layer = {
    id: "raster-1",
    layerType: "raster",
    symbolization: value,
    renderStatus: "ready",
  } as LoadedRasterLayer;
  const context = {
    groups: [{ id: "group-1", children: [layer] }],
    canUseCustomSymbolization: canEdit,
    setLayerSymbolization: apply,
    startRasterRender: renderRaster,
  } as unknown as LayerContextValue;
  return render(
    <LayerContext.Provider value={context}>
      <RasterRenderingControls
        layer={loaded ? layer : null}
        value={value}
        bands={bandOptions}
      />
    </LayerContext.Provider>,
  );
}
beforeEach(async () => {
  vi.clearAllMocks();
  await setLocale("zh-CN");
});
describe("raster rendering controls", () => {
  it("applies a palette and NoData selection through the backend rendering callback", async () => {
    show();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "渲染方案" }));
    fireEvent.click(await screen.findByText("单波段伪彩色"));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "配色" }));
    fireEvent.click(await screen.findByText("热力"));
    fireEvent.click(screen.getByRole("switch", { name: "NoData透明" }));
    expect(renderRaster).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "应用渲染方案" }));
    expect(apply).toHaveBeenCalledWith(
      "group-1",
      "raster-1",
      expect.objectContaining({
        mode: "pseudocolor",
        palette: "thermal",
        bands: [1],
      }),
    );
    expect(renderRaster).toHaveBeenCalledWith(
      "group-1",
      "raster-1",
      apply.mock.calls[0][2],
      expect.objectContaining({ id: "raster-1" }),
      "custom",
    );
    expect(apply.mock.calls[0][2].nodata.enabled).toBe(
      !cloneDefaultRasterSymbolization().nodata.enabled,
    );
  });
  it("uses three valid bands when switching to RGB", async () => {
    show();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "渲染方案" }));
    fireEvent.click(await screen.findByText("RGB多波段合成"));
    expect(screen.getByRole("combobox", { name: "R 波段" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "应用渲染方案" }));
    expect(apply.mock.calls[0][2].bands).toEqual([1, 2, 3]);
  });
  it("does not allow an account without styling permission to apply", () => {
    show(false);
    expect(screen.getByRole("button", { name: "应用渲染方案" })).toBeDisabled();
    expect(screen.getByText("当前账号没有自定义渲染权限。")).toBeVisible();
    expect(renderRaster).not.toHaveBeenCalled();
  });
  it("explains how to enable controls for an unloaded raster", () => {
    show(true, false);
    expect(screen.getByRole("button", { name: "应用渲染方案" })).toBeDisabled();
    expect(
      screen.getByText("将资源加载到地图后，可在此调整配色与显示参数。"),
    ).toBeVisible();
  });
});
