import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import type { AgentWorkflow } from "../api/generated/types.gen";
import WorkflowResults from "./WorkflowResults";
import WorkflowDeliverables from "./WorkflowDeliverables";
import { liveComputeTask } from "./computeFlow.testFixtures";

vi.mock("./WorkflowReportFile", () => ({ default: () => null }));
vi.mock("./RunComputeTasks", () => ({ default: () => null }));

function workflow(): AgentWorkflow {
  return {
    id: "historical-workflow",
    projectId: 3,
    workflowType: "geology_correction",
    goal: "检查历史地图",
    model: "qwen",
    status: "failed",
    detail: "历史任务已结束",
    currentStep: "finalize",
    iteration: 1,
    operatorSteps: 1,
    maxIterations: 3,
    maxOperatorSteps: 3,
    executeOperators: true,
    resourceIds: [10],
    algorithmVersionId: null,
    parameters: {},
    resultIds: [],
    evidence: [],
    runtime: "worker",
    steps: [],
    createdAt: "",
    updatedAt: "",
    importResults: true,
    resultResourceIds: [31],
    planHash: "approved-history",
    plan: {
      inputs: { initial_map: 10 },
      stages: [
        {
          name: "edit",
          outputs: [
            { kind: "vector", resourceId: 31 },
            { kind: "raster", resourceId: 32 },
          ],
        },
      ],
      deletedResources: [
        {
          formerResourceId: 32,
          name: "旧修正结果",
          source: "compute-output:private-internal-key",
          status: "deleted",
          deletedAt: "2026-10-16T10:00:00Z",
        },
      ],
    },
  };
}

it("keeps named provenance and filters deleted IDs from historical comparison links", () => {
  render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={workflow()} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText("部分历史目录数据已删除")).toBeVisible();
  expect(screen.getByText("旧修正结果")).toBeVisible();
  expect(screen.queryByText(/private-internal-key/)).not.toBeInTheDocument();
  const href = screen
    .getByRole("link", { name: "在地理工作台对比成果图层" })
    .getAttribute("href");
  expect(href).toContain("resources=10,31");
  expect(href).not.toContain("32");
});

it("does not advertise an unavailable geology before-and-after pair", () => {
  const saved = workflow();
  saved.status = "succeeded";
  saved.workflowType = "geology_map_review";
  saved.plan.deletedResources = [
    {
      formerResourceId: 10,
      name: "待检查地质图",
      source: "平台计算",
      status: "deleted",
    },
  ];
  render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={saved} />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen.queryByRole("link", { name: "查看待检查地质图与修正后地质图" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "打开独立对比页" }),
  ).not.toBeInTheDocument();
});

it("shows deleted catalog status while retaining independent output downloads", () => {
  const task = liveComputeTask("succeeded");
  task.outputs[0] = {
    ...task.outputs[0]!,
    kind: "vector",
    importStatus: "deleted",
    resourceId: null,
    mapUrl: "",
    resourceLocation: "",
    importError: "已由用户确认删除目录数据。",
    downloadUrl: "/api/compute/outputs/30/file/",
  };
  render(
    <App>
      <MemoryRouter>
        <WorkflowDeliverables
          items={[{ task, autoImport: false }]}
          onImport={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByText("目录数据已删除")).toBeVisible();
  expect(screen.getByRole("button", { name: /下载/ })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "打开入库数据" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "将结果入库" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /在地理工作台查看/ }),
  ).not.toBeInTheDocument();
});

it("requires new inputs when a paused history contains a deletion receipt", () => {
  const saved = workflow();
  saved.status = "paused";
  render(
    <App>
      <MemoryRouter>
        <WorkflowResults workflow={saved} onResume={vi.fn()} />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen.queryByRole("button", { name: "继续任务" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/再次处理时请重新选择相应数据/)).toBeVisible();
});
