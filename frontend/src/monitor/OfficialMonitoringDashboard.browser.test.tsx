import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { requestJson } from "../api/client";
import type { OfficialMonitoringProduct } from "../api/generated/types.gen";
import monitorStyles from "../pages/ecology-monitor.css?inline";
import OfficialMonitoringDashboard from "./OfficialMonitoringDashboard";

vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  requestJson: vi.fn(),
}));
vi.mock("./ProductMap", () => ({
  default: (props: {
    product?: OfficialMonitoringProduct;
    readOnly: boolean;
    preparedDisplay?: { styleHash: string };
  }) => (
    <>
      <output data-testid="official-map-handoff">
        {JSON.stringify([
          props.product?.id,
          props.readOnly,
          props.preparedDisplay?.styleHash,
        ])}
      </output>
      <div className="monitor-map-controls" role="group" aria-label="地图视角">
        <button className="ant-btn">全球</button>
        <button className="ant-btn">区域</button>
        <button className="ant-btn">完整范围</button>
      </div>
    </>
  ),
}));

function item(id: number, label: string, area: number) {
  return {
    id,
    name: label,
    regionLabel: label,
    registeredAt: "2026-11-18T11:00:00Z",
    observedStart: "2025-09-01",
    observedEnd: "2025-09-01",
    resource: { id, dataType: "raster" },
    display: { styleHash: `style-${id}` },
    metrics: [
      {
        key: "valid_area_km2",
        label: "有效统计面积",
        value: area,
        unit: "km²",
      },
    ],
    interpretation: "原始投影面积统计",
  };
}

function show(scene: "landcover" | "wildfire") {
  return render(
    <App>
      <style>{monitorStyles}</style>
      <MemoryRouter>
        <OfficialMonitoringDashboard
          scene={scene}
          navigation={null}
          config={{
            title: "监测",
            source: "remote_sensing_products",
            initialView: { center: [107, 24], zoom: 1, regionZoom: 9 },
          }}
        />
      </MemoryRouter>
    </App>,
  );
}

it("轮播切换真实区域指标和已登记图层，不查询来源或执行任务", async () => {
  vi.mocked(requestJson).mockResolvedValue({
    scene: "landcover",
    items: [item(9, "环江一号区", 1832), item(8, "环江二号区", 410)],
  });
  show("landcover");
  const map = screen.getByRole("region", { name: "正式成果地图" });
  const region = screen.getByRole("complementary", { name: "区域观测指标" });
  await within(map).findByRole("heading", { name: "环江一号区" });
  await waitFor(() => expect(within(region).getByText("1,832")).toBeVisible());
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[9,true,"style-9"]',
  );
  fireEvent.click(screen.getByRole("button", { name: "下一区域" }));
  await waitFor(() =>
    expect(
      within(map).getByRole("heading", { name: "环江二号区" }),
    ).toBeVisible(),
  );
  await waitFor(() => expect(within(region).getByText("410")).toBeVisible());
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[8,true,"style-8"]',
  );
  expect(screen.queryByText(/框选|历史成果|开始业务流/)).toBeNull();
  expect(vi.mocked(requestJson).mock.calls.map(([path]) => path)).toEqual([
    "/api/ecology/monitoring/official/?scene=landcover",
  ]);
});

it.each([
  [1600, 900],
  [1280, 680],
  [390, 844],
])(
  "%ipx 恢复旧地图版式、顶端控件和透明统计卡，不裁大数字",
  async (width, height) => {
    await page.viewport(width, height);
    const metric = item(42, "全球火烧面积与遥感观测区域名称", 4025291.382);
    metric.metrics[0]!.unit = "ha";
    vi.mocked(requestJson).mockResolvedValue({
      scene: "wildfire",
      items: [metric],
    });
    show("wildfire");

    const number = await screen.findByText("4,025,291.382", { exact: true });
    await waitFor(() => expect(number).toBeVisible());
    const map = screen.getByRole("region", { name: "正式成果地图" });
    const aside = screen.getByRole("complementary", { name: "区域观测指标" });
    const mapBounds = map.getBoundingClientRect();
    const asideBounds = aside.getBoundingClientRect();
    expect(getComputedStyle(map).borderTopWidth).toBe("0px");
    if (width > 1100) {
      expect(mapBounds.width / asideBounds.width).toBeCloseTo(1.5, 1);
      expect(mapBounds.top).toBe(asideBounds.top);
    } else {
      expect(asideBounds.top).toBeGreaterThan(mapBounds.bottom);
    }
    const caption = screen
      .getByText("地理空间观测")
      .parentElement!.getBoundingClientRect();
    const controls = screen
      .getByRole("group", { name: "地图视角" })
      .getBoundingClientRect();
    expect(caption.top - mapBounds.top).toBeLessThanOrEqual(14);
    expect(caption.height).toBeLessThan(80);
    expect(controls.top).toBe(caption.top);
    expect(caption.right).toBeLessThan(controls.left);
    const card = number.closest(".monitor-panel")!;
    const metricRow = number.closest(".official-hero-stat")!;
    expect(getComputedStyle(card).backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(number.getBoundingClientRect().width).toBeLessThanOrEqual(
      metricRow.getBoundingClientRect().width,
    );
    expect(within(card as HTMLElement).getByText("ha")).toBeVisible();
  },
);
