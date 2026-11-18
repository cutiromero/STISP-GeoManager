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
import { requestJson } from "../api/client";
import type { OfficialMonitoringProduct } from "../api/generated/types.gen";
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
    <output data-testid="official-map-handoff">
      {JSON.stringify([
        props.product?.id,
        props.readOnly,
        props.preparedDisplay?.styleHash,
      ])}
    </output>
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

it("轮播切换真实区域指标和已登记图层，不查询来源或执行任务", async () => {
  vi.mocked(requestJson).mockResolvedValue({
    scene: "landcover",
    items: [item(9, "环江一号区", 1832), item(8, "环江二号区", 410)],
  });
  render(
    <App>
      <MemoryRouter>
        <OfficialMonitoringDashboard
          scene="landcover"
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
  const region = screen.getByRole("complementary", { name: "区域观测指标" });
  await within(region).findByRole("heading", { name: "环江一号区" });
  await waitFor(() => expect(within(region).getByText("1,832")).toBeVisible());
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[9,true,"style-9"]',
  );
  fireEvent.click(screen.getByRole("button", { name: "下一区域" }));
  await waitFor(() =>
    expect(
      within(region).getByRole("heading", { name: "环江二号区" }),
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
