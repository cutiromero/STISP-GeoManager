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

function show(scene: "landcover" | "wildfire" | "glacier") {
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
  const stats = () => screen.getByRole("region", { name: "有效统计面积" });
  await within(map).findByRole("heading", { name: "环江一号区" });
  await waitFor(() => expect(within(stats()).getByText("1,832")).toBeVisible());
  const overview = screen.getByRole("region", { name: "区域成果一览" });
  const first = within(overview).getByRole("button", { name: /环江一号区/ });
  const second = within(overview).getByRole("button", { name: /环江二号区/ });
  expect(first).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[9,true,"style-9"]',
  );
  fireEvent.click(screen.getByRole("button", { name: "下一区域" }));
  await waitFor(() =>
    expect(
      within(map).getByRole("heading", { name: "环江二号区" }),
    ).toBeVisible(),
  );
  await waitFor(() => expect(within(stats()).getByText("410")).toBeVisible());
  expect(second).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[8,true,"style-8"]',
  );
  fireEvent.click(first);
  expect(first).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[9,true,"style-9"]',
  );
  expect(screen.getByRole("button", { name: "播放区域轮播" })).toBeVisible();
  expect(screen.queryByText(/框选|历史成果|开始业务流/)).toBeNull();
  expect(vi.mocked(requestJson).mock.calls.map(([path]) => path)).toEqual([
    "/api/ecology/monitoring/official/?scene=landcover",
  ]);
});

it("把四项正式成果铺到右下，仍使用透明卡片；翻组联动地图", async () => {
  await page.viewport(1600, 900);
  const items = Array.from({ length: 6 }, (_, index) =>
    item(index + 1, `环江 ${index + 1} 区`, 123 + index),
  );
  vi.mocked(requestJson).mockResolvedValue({ scene: "landcover", items });
  show("landcover");

  const aside = screen.getByRole("complementary", { name: "区域观测指标" });
  const overview = await within(aside).findByRole("region", {
    name: "区域成果一览",
  });
  const list = within(overview).getByRole("list");
  expect(within(list).getAllByRole("listitem")).toHaveLength(4);
  const last = within(list).getByRole("button", { name: /环江 4 区/ });
  expect(last).toHaveTextContent("2025-09-01");
  expect(last).toHaveTextContent("126");
  expect(getComputedStyle(overview).backgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(
    aside.getBoundingClientRect().bottom -
      overview.getBoundingClientRect().bottom,
  ).toBeLessThan(2);
  expect(
    overview.getBoundingClientRect().bottom -
      last.getBoundingClientRect().bottom,
  ).toBeLessThan(30);

  fireEvent.click(within(overview).getByRole("button", { name: "下一组成果" }));
  expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  expect(
    within(list).getByRole("button", { name: /环江 5 区/ }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[5,true,"style-5"]',
  );
  expect(
    within(overview).getByRole("button", { name: "下一组成果" }),
  ).toBeDisabled();
});

it("在窄屏保留每项野火成果的观测量与单位，不将缺测显示为零", async () => {
  await page.viewport(390, 844);
  vi.mocked(requestJson).mockResolvedValue({
    scene: "wildfire",
    items: [
      {
        ...item(4, "烧毁面积监测区", 1234.567),
        metrics: [
          {
            key: "burned_area_ha",
            label: "观测烧毁面积",
            value: 1234.567,
            unit: "ha",
          },
        ],
      },
      {
        ...item(5, "辐射功率监测区", 0.52),
        observation: { product: "cams_frpfire", unit: "W m-2" },
        metrics: [
          {
            key: "frp_w_m2",
            label: "观测火辐射功率密度",
            value: 0.52,
            unit: "W m-2",
          },
        ],
      },
      {
        ...item(6, "缺测监测区", 0),
        observedStart: null,
        observedEnd: null,
        metrics: [
          {
            key: "burned_area_ha",
            label: "观测烧毁面积",
            value: null,
            unit: "ha",
          },
        ],
      },
    ],
  });
  show("wildfire");

  const overview = await screen.findByRole("region", { name: "区域成果一览" });
  const burned = within(overview).getByRole("button", {
    name: /烧毁面积监测区/,
  });
  const power = within(overview).getByRole("button", {
    name: /辐射功率监测区/,
  });
  const missing = within(overview).getByRole("button", { name: /缺测监测区/ });
  expect(burned).toHaveTextContent("观测烧毁面积");
  expect(within(burned).getByText("ha")).toBeVisible();
  expect(power).toHaveTextContent("观测火辐射功率密度");
  expect(within(power).getByText("W m-2")).toBeVisible();
  expect(missing).toHaveTextContent("观测期未登记");
  expect(missing).toHaveTextContent("统计未登记");
  expect(within(missing).getByText("—")).toBeVisible();
  expect(power.getBoundingClientRect().right).toBeLessThanOrEqual(390);
  fireEvent.click(power);
  const selected = screen.getByRole("region", { name: "观测火辐射功率密度" });
  await waitFor(() => expect(within(selected).getByText("0.52")).toBeVisible());
});

it("只有一项时呈现实际登记档案，而不是空的区域列表", async () => {
  vi.mocked(requestJson).mockResolvedValue({
    scene: "landcover",
    items: [
      {
        ...item(9, "环江一号区", 1832),
        model: { name: "地表覆盖 UNet", version: "2.1.0" },
        quality: "passed",
        sourceLabel: "环江高分辨率正射影像",
        statisticsMethod: "仅统计有效像元，按原投影面积汇总。",
      },
    ],
  });
  show("landcover");

  const archive = await screen.findByRole("region", { name: "成果档案" });
  expect(within(archive).getByText("环江高分辨率正射影像")).toBeVisible();
  expect(within(archive).getByText("地表覆盖 UNet · 2.1.0")).toBeVisible();
  expect(within(archive).getByText("已核验")).toBeVisible();
  expect(
    within(archive).getByText("仅统计有效像元，按原投影面积汇总。"),
  ).toBeVisible();
  expect(archive.querySelector("time")).toHaveAttribute(
    "datetime",
    "2026-11-18T11:00:00Z",
  );
  expect(screen.queryByRole("region", { name: "区域成果一览" })).toBeNull();
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

it("冰川成果切换同区原始影像，不显示参考资料和成果说明", async () => {
  vi.mocked(requestJson).mockClear();
  vi.mocked(requestJson).mockResolvedValue({
    scene: "glacier",
    items: [
      {
        ...item(81, "冰川样区 · T42-1", 0),
        scene: "glacier",
        observedStart: null,
        observedEnd: null,
        registrationDate: "2026-11-22",
        comparison: {
          resource: { id: 80, name: "原始影像" },
          display: { styleHash: "raw-80" },
        },
        references: [{ id: 91, name: "冰川图集", projectTagId: 8 }],
      },
    ],
  });
  show("glacier");
  const original = await screen.findByRole("button", { name: "原始影像" });
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[81,true,"style-81"]',
  );
  fireEvent.click(original);
  expect(original).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("第 1 波段灰度")).toBeVisible();
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[81,true,"raw-80"]',
  );
  fireEvent.click(screen.getByRole("button", { name: "分类结果" }));
  expect(screen.getByTestId("official-map-handoff")).toHaveTextContent(
    '[81,true,"style-81"]',
  );
  expect(screen.queryByRole("region", { name: "参考资料" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "成果说明" })).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("region", { name: "正式成果地图" })).getByText(
      "登记期：2026-11-22",
    ),
  ).toBeVisible();
  expect(vi.mocked(requestJson)).toHaveBeenCalledTimes(1);
});

it("冰川固定右栏，用不同文字颜色区分变化指标与正负面积差", async () => {
  const before = [...Array(9)].map((_, i) => item(90 + i, `样区-${i + 1}`, i));
  vi.mocked(requestJson).mockResolvedValue({
    scene: "glacier",
    items: [
      {
        ...item(100, "冰川样区 · T43-10", 14.89),
        scene: "glacier",
        kind: "model",
        registrationDate: "2026-11-23",
        metrics: [{key:"ice_area_km2", label:"本期冰川分类面积", unit:"km²", value:14.89}],
        glacierChange: {
          baselineProductId:81, baselineDate:"2026-11-22", basis:"registered_codes",
          commonAreaKm2:19.942, changedPercent:15.25, netClass1Km2:0.2, netClass2Km2:-0.3,
          netIceAreaKm2:null,
        },
        references: Array.from({length:9}, (_, i)=>({id: 910+i, name:`参考图件 ${i+1}`,projectTagId:8})),
      },
      ...before.map((p)=>({...p,scene:"glacier",registrationDate:"2026-11-22"})),
    ],
  });
  show("glacier");
  const changes = await screen.findByRole("region", {name:"登记期变化"});
  expect(screen.getByText("登记期不是影像拍摄日期")).toBeVisible();
  expect(screen.queryByText("以登记的实际观测期与统计口径为准")).not.toBeInTheDocument();
  await waitFor(() => expect(within(changes).getByText("2026-11-22 → 2026-11-23")).toBeVisible());
  expect(within(changes).getByText("编码变化占比")).toBeVisible();
  expect(within(changes).queryByText("冰川分类面积净变化")).not.toBeInTheDocument();
  const column = screen.getByRole("complementary", {name:"区域观测指标"});
  const overview = within(column).getByRole("region", {name:"区域成果一览"});
  expect(getComputedStyle(column).overflowY).toBe("hidden");
  expect(getComputedStyle(within(overview).getByRole("list")).overflowY).toBe("auto");
  expect(within(overview).getAllByRole("listitem")).toHaveLength(10);
  const current = within(column).getByText("14.89", { selector: ".official-hero-stat strong" });
  const entries = within(changes);
  expect(getComputedStyle(current).color).toBe("rgb(139, 214, 242)");
  expect(getComputedStyle(entries.getByText("共同有效面积")).color).toBe("rgb(121, 226, 203)");
  expect(getComputedStyle(entries.getByText("19.942", { selector: "dd" })).color).toBe("rgb(121, 226, 203)");
  expect(getComputedStyle(entries.getByText("15.25", { selector: "dd" })).color).toBe("rgb(255, 200, 122)");
  expect(getComputedStyle(entries.getByText("+0.2")).color).toBe("rgb(167, 235, 155)");
  expect(getComputedStyle(entries.getByText("-0.3")).color).toBe("rgb(255, 163, 182)");
});
