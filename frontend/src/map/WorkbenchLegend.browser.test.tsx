import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";
import { cloneDefaultRasterSymbolization } from "../symbolization";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import type { LoadedRasterLayer } from "../types";
import WorkbenchLegend from "./WorkbenchLegend";

describe("live legend UI", () => {
  beforeEach(async () => {
    localStorage.removeItem("workbench-legend");
    await page.viewport(1440, 900);
  });

  it("automatically displays classes, follows a render update and can be collapsed", () => {
    const layer = {
      id: "land",
      name: "土地覆盖",
      layerType: "raster",
      sourceResource: createEmptyLayerGroup().sourceResource,
      tileUrl: "/tiles",
      visible: true,
      symbolization: {
        ...cloneDefaultRasterSymbolization(),
        mode: "unique",
        uniqueValues: [{ value: 1, label: "林地", color: "#228855" }],
      },
    } as LoadedRasterLayer;
    const view = render(
      <WorkbenchLegend layers={[layer]} english={false} mobileHidden={false} />,
    );
    expect(screen.getByText("林地")).toBeVisible();
    view.rerender(
      <WorkbenchLegend
        layers={[
          {
            ...layer,
            symbolization: {
              ...layer.symbolization,
              uniqueValues: [{ value: 2, label: "水体", color: "#1166cc" }],
            },
          },
        ]}
        english={false}
        mobileHidden={false}
      />,
    );
    expect(screen.queryByText("林地")).toBeNull();
    expect(screen.getByText("水体")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /图例/ }));
    expect(screen.queryByText("水体")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /图例/ }));
    expect(screen.getByText("水体")).toBeVisible();
  });
});
