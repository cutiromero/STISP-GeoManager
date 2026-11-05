import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import type { AgentWorkflow } from "../api/generated/types.gen";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import WorkflowCard from "./WorkflowCard";
import "./agent.css";

vi.mock("./WorkflowReportFile", () => ({ default: () => null }));
afterEach(() => vi.restoreAllMocks());

function card(phase = "review_plan"): AgentWorkflow {
  const workflow = reviewWorkflow();
  return {
    ...workflow,
    status: "waiting_approval",
    view: "card",
    steps: [],
    evidence: [],
    modificationReview: undefined,
    plan: { phase, stages: [] },
    resultResourceIds: [],
    stepCount: 0,
  };
}

it("恢复的新对话无需展开即可确认执行、暂停或停止", async () => {
  const confirm = vi.fn();
  const pause = vi.fn();
  const cancel = vi.fn();
  const load = vi.spyOn(agentApi, "workflow");
  render(
    <App>
      <MemoryRouter>
        <WorkflowCard
          workflow={card()}
          onConfirm={confirm}
          onPause={pause}
          onCancel={cancel}
        />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  ).toBeVisible();
  for (const name of ["确认执行", "暂停任务", "停止此工作流"])
    expect(screen.getByRole("button", { name })).toBeVisible();
  expect(load).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
  expect(confirm).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "暂停任务" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认暂停" }));
  await waitFor(() => expect(pause).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "停止此工作流" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认停止" }));
  await waitFor(() => expect(cancel).toHaveBeenCalledOnce());
});

it("确认结果与审核意见始终在折叠区外", () => {
  render(
    <App>
      <MemoryRouter>
        <WorkflowCard workflow={card("review_results")} onReview={vi.fn()} />
      </MemoryRouter>
    </App>,
  );
  expect(screen.getByRole("button", { name: "审核通过并继续" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "审核意见" })).toBeVisible();
});

it("有候选建议时，批准主按钮在过程收起状态也始终可见", async () => {
  const detail = reviewWorkflow();
  detail.view = "inspection";
  const load = vi.spyOn(agentApi, "workflow").mockResolvedValue(detail);
  render(
    <App>
      <MemoryRouter>
        <WorkflowCard
          workflow={card("review_modifications")}
          onReview={vi.fn()}
        />
      </MemoryRouter>
    </App>,
  );
  expect(
    await screen.findByRole("button", { name: "批准选中的建议并修正" }),
  ).toBeVisible();
  expect(load).toHaveBeenCalledExactlyOnceWith(detail.id, {
    signal: expect.any(AbortSignal),
    view: "inspection",
    part: "suggestions",
  });
  expect(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  ).toBeVisible();
});

it("待批准自动读取建议，批准和继续分析不依赖展开过程", async () => {
  const detail = reviewWorkflow();
  detail.view = "inspection";
  detail.workflowType = "geology_multi_element_reasoning";
  detail.modificationReview!.suggestions = [];
  const load = vi.spyOn(agentApi, "workflow").mockResolvedValue(detail);
  const review = vi.fn();
  render(
    <App>
      <MemoryRouter>
        <WorkflowCard
          workflow={{
            ...card("review_modifications"),
            workflowType: detail.workflowType,
          }}
          onReview={review}
        />
      </MemoryRouter>
    </App>,
  );
  const proceed = await screen.findByRole("button", {
    name: "本轮无修改，继续分析",
  });
  expect(proceed).toBeVisible();
  expect(load).toHaveBeenCalledExactlyOnceWith(detail.id, {
    signal: expect.any(AbortSignal),
    view: "inspection",
    part: "suggestions",
  });
  expect(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  ).toBeVisible();
  fireEvent.click(proceed);
  expect(review).toHaveBeenCalledWith(
    "approve",
    "本轮未形成修改建议，保留数据继续分析",
    [],
  );
});

it("展开再收起仍保留确认按钮，轮询改变状态后不显示过期操作", async () => {
  const summary = card();
  const detail = { ...summary, view: "inspection" as const };
  vi.spyOn(agentApi, "workflow").mockResolvedValue(detail);
  const content = (workflow: AgentWorkflow) => (
    <App>
      <MemoryRouter>
        <WorkflowCard workflow={workflow} onConfirm={vi.fn()} />
      </MemoryRouter>
    </App>
  );
  const view = render(content(summary));
  fireEvent.click(
    screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
  );
  await waitFor(() => expect(agentApi.workflow).toHaveBeenCalledOnce());
  expect(agentApi.workflow).toHaveBeenCalledWith(summary.id, {
    signal: expect.any(AbortSignal),
    view: "inspection",
    part: "steps",
  });
  fireEvent.click(screen.getByRole("button", { name: "收起明细" }));
  expect(screen.getByRole("button", { name: "确认执行" })).toBeVisible();
  view.rerender(
    content({ ...summary, status: "running", updatedAt: "new-poll" }),
  );
  expect(
    screen.queryByRole("button", { name: "确认执行" }),
  ).not.toBeInTheDocument();
});
