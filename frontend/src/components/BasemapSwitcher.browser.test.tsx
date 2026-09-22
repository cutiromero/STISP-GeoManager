import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { describe, expect, it, vi } from "vitest";
import { createBasemapCatalog, type BasemapId } from "../map/basemapCatalog";
import { appTheme } from "../theme";
import BasemapSwitcher from "./BasemapSwitcher";

const availableCatalog = createBasemapCatalog({
  mapboxAccessToken: "mapbox-test-token",
  tiandituKey: "tianditu-test-key",
});

function switcherView({
  basemaps = availableCatalog,
  activeId = "mapbox-satellite",
  switching = false,
  disabled = false,
  disabledReason,
  onSelect = vi.fn(),
}: {
  basemaps?: ReturnType<typeof createBasemapCatalog>;
  activeId?: BasemapId;
  switching?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onSelect?: (id: BasemapId) => void;
} = {}) {
  return (
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <BasemapSwitcher
          basemaps={basemaps}
          activeId={activeId}
          switching={switching}
          disabled={disabled}
          disabledReason={disabledReason}
          onSelect={onSelect}
        />
      </AntApp>
    </ConfigProvider>
  );
}

async function openSwitcher() {
  fireEvent.click(
    screen.getByRole("button", {
      name: /切换底图，当前为Mapbox 卫星实景图/,
    }),
  );
  return screen.findByRole("dialog", { name: "选择底图" });
}

describe("BasemapSwitcher", () => {
  it("shows only the four selectable local previews and marks the active item", async () => {
    render(switcherView());

    const dialog = await openSwitcher();
    const options = within(dialog).getAllByRole("button");
    expect(options).toHaveLength(4);
    expect(
      within(dialog).getByRole("button", {
        name: /Mapbox 卫星实景图，当前使用/,
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(within(dialog).getByText("Mapbox 街道图")).toBeInTheDocument();
    expect(within(dialog).getByText("天地图矢量注记图")).toBeInTheDocument();
    expect(within(dialog).getByText("天地图卫星影像图")).toBeInTheDocument();
    expect(within(dialog).queryByText(/OpenStreetMap/)).not.toBeInTheDocument();
    expect(dialog.querySelector("img")).toBeNull();
    expect(dialog.innerHTML).not.toMatch(/https?:\/\//i);
  });

  it("selects an available alternative without reselecting the active item", async () => {
    const onSelect = vi.fn();
    render(switcherView({ onSelect }));
    const dialog = await openSwitcher();

    fireEvent.click(
      within(dialog).getByRole("button", {
        name: /Mapbox 卫星实景图，当前使用/,
      }),
    );
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("button", {
        name: /Mapbox 街道图，可用/,
      }),
    );
    expect(onSelect).toHaveBeenCalledOnce();
    expect(onSelect).toHaveBeenCalledWith("mapbox-streets");
  });

  it("keeps an unavailable choice visible, disabled, and explains why", async () => {
    const onSelect = vi.fn();
    const catalog = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
    });
    render(switcherView({ basemaps: catalog, onSelect }));
    const dialog = await openSwitcher();
    const unavailable = within(dialog).getByRole("button", {
      name: /天地图矢量注记图，未配置天地图 Key/,
    });

    expect(unavailable).toBeDisabled();
    expect(unavailable).toHaveTextContent("未配置天地图 Key");
    fireEvent.click(unavailable);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("disables repeated selection and shows progress while switching", async () => {
    const onSelect = vi.fn();
    const result = render(switcherView({ onSelect }));
    await openSwitcher();

    result.rerender(switcherView({ switching: true, onSelect }));

    expect(screen.getByRole("button", { name: /正在切换底图/ })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /正在切换底图/ }),
    ).toHaveAttribute("aria-busy", "true");
    const dialog = await screen.findByRole("dialog", { name: "选择底图" });
    expect(within(dialog).getByRole("status")).toHaveTextContent("正在切换");
    for (const option of within(dialog).getAllByRole("button")) {
      expect(option).toBeDisabled();
    }
  });

  it("exposes a component-level disabled reason", async () => {
    render(
      switcherView({
        disabled: true,
        disabledReason: "地图尚未初始化",
      }),
    );

    const trigger = screen.getByRole("button", {
      name: /地图尚未初始化/,
    });
    expect(trigger).toBeDisabled();
    await waitFor(() => {
      expect(trigger.closest(".basemap-switcher")).toHaveAttribute(
        "title",
        "地图尚未初始化",
      );
    });
  });
});
