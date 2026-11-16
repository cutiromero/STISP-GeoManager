import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import BusinessFlowLaunch from "./BusinessFlowLaunch";
import BusinessFlowFailureDiagnostic from "./BusinessFlowFailureDiagnostic";
import { businessFlowsApi } from "../api/businessFlows";
import { requestJson } from "../api/client";
import { setActiveProject } from "../projects/session";
import {
  sourceCatalog,
  sourceTimes,
} from "../monitor/monitoringWorkspace.testFixtures";
import {
  businessFlowRun,
  directInputPlan,
  geologyDetail,
  researchSpec,
} from "./businessFlow.testFixtures";
import type { ResourceListItem } from "../api/generated/types.gen";

vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  requestJson: vi.fn(),
}));
vi.mock("../agent/useAgentBootstrap", () => ({
  useAgentBootstrapState: () => ({
    bootstrap: {
      canAgent: true,
      workerOnline: true,
      thinkingEnabled: false,
      models: [
        { alias: "mock", name: "Mock", status: "online", allowAgent: true },
      ],
    },
  }),
}));

const resource = {
  id: 9000,
  name: "原生野火观测",
  updatedAt: "2026-11-15",
} as ResourceListItem;
const definition = {
  ...researchSpec,
  inputRequirements: [
    {
      key: "cube",
      label: "原始立方体",
      description: "原始观测",
      dataTypes: ["raster" as const],
      required: true,
      requiredFields: [],
    },
  ],
};
const version = { ...geologyDetail.version!, definition };
const detail = {
  ...geologyDetail,
  flow: { ...geologyDetail.flow, code: "wildfire-history-observation" },
  version,
  versions: [version],
};
const launch = {
  definitionId: detail.flow.id,
  versionId: version.id,
  title: "野火业务流",
  goal: "生成所选原生野火观测",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.mocked(requestJson).mockReset();
  setActiveProject("13");
  vi.spyOn(businessFlowsApi, "detail").mockResolvedValue(detail);
  vi.spyOn(businessFlowsApi, "prepareInputs").mockImplementation(
    async (_id, body) => directInputPlan(body),
  );
});

it("shows deterministic missing-parameter guidance without claiming an AI diagnosis", () => {
  render(
    <BusinessFlowFailureDiagnostic
      value={{
        code: "NODE_PARAMETERS_MISSING",
        location: "观测处理",
        facts: ["缺少时间索引"],
        attempts: [],
        references: [],
        resumeAt: "确认后继续",
        analysisStatus: "unavailable",
        analysis: "尚未提交计算，重复读取配置不能补齐用户选择。",
        suggestions: ["请选择真实观测产品和日期。"],
      }}
    />,
  );
  expect(screen.getByText("参数检查")).toBeVisible();
  expect(screen.getByText("请选择真实观测产品和日期。")).toBeVisible();
});

it("waits for real observation dates and freezes the selected index instead of starting without required parameters", async () => {
  let resolveTimes!: (value: unknown) => void;
  vi.mocked(requestJson).mockImplementation(async (url) =>
    url.includes("source-times")
      ? await new Promise((resolve) => {
          resolveTimes = resolve;
        })
      : (sourceCatalog("wildfire", [resource]) as never),
  );
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun());
  render(
    <App>
      <BusinessFlowLaunch
        launch={launch}
        model="mock"
        initialInputs={{ cube: 9000 }}
        onStarted={vi.fn()}
        onCancel={vi.fn()}
      />
    </App>,
  );
  const button = await screen.findByRole("button", { name: "开始业务流" });
  await waitFor(() => expect(resolveTimes).toBeTypeOf("function"));
  expect(button).toBeDisabled();
  expect(start).not.toHaveBeenCalled();
  await act(async () => {
    resolveTimes({ ...sourceTimes, resourceId: 9000 });
  });
  await waitFor(() => expect(button).toBeEnabled());
  expect(
    screen.getByRole("combobox", { name: "任务观测时期" }),
  ).toBeInTheDocument();
  fireEvent.click(button);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]![1]).toMatchObject({
    inputs: { cube: 9000 },
    parameters: {
      nodeParameters: {
        interpret: { product: "gwis_ba", time_index: 2000, history: 1 },
      },
    },
  });
  expect(start.mock.calls[0]![1].goal).toContain("2026-12-27");
});

it("preserves the explicit dashboard observation selection without another catalog read", async () => {
  const start = vi
    .spyOn(businessFlowsApi, "start")
    .mockResolvedValue(businessFlowRun());
  render(
    <App>
      <BusinessFlowLaunch
        launch={launch}
        model="mock"
        initialInputs={{ cube: 9000 }}
        parameters={{
          nodeParameters: {
            interpret: { product: "fcci_ba", time_index: 0, history: 1 },
          },
        }}
        onStarted={vi.fn()}
        onCancel={vi.fn()}
      />
    </App>,
  );
  const button = await screen.findByRole("button", { name: "开始业务流" });
  await waitFor(() => expect(button).toBeEnabled());
  expect(
    screen.queryByRole("region", { name: "野火观测选择" }),
  ).not.toBeInTheDocument();
  fireEvent.click(button);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]![1].parameters).toEqual({
    nodeParameters: {
      interpret: { product: "fcci_ba", time_index: 0, history: 1 },
    },
  });
  expect(requestJson).not.toHaveBeenCalled();
});
