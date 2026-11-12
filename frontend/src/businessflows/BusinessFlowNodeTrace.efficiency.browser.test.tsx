import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { afterEach, expect, it, vi } from "vitest";
import type { BusinessFlowNodeTrace as NodeTrace } from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import BusinessFlowMonitor from "./BusinessFlowMonitor";
import BusinessFlowNodeTrace from "./BusinessFlowNodeTrace";
import { businessFlowRun } from "./businessFlow.testFixtures";

afterEach(() => vi.restoreAllMocks());

function trace(nodeId = "analyse"): NodeTrace {
  return {
    nodeId,
    title: "实际节点",
    historical: false,
    nextOffset: null,
    requests: [
      {
        id: "request-" + nodeId,
        role: "executor",
        attempt: 1,
        status: "complete",
        model: "Qwen",
        thinkingEnabled: true,
        reasoningEffort: "medium",
        thinkingText: "核对实际输入后先预检，再提交计算。",
        thinkingChars: 18,
        thinkingTruncated: false,
        response: {
          content: `实际响应-${nodeId}`,
          sizeBytes: 30,
          truncated: false,
        },
        startedAt: "2026-11-12T05:00:00Z",
        finishedAt: "2026-11-12T05:00:20Z",
      },
    ],
    actions: [
      {
        step: 1,
        action: "preflight_operator",
        summary: "预检通过，尚未计算",
        parameterSummary: '{"working_epsg":32646}',
      },
    ],
  };
}

it("reads only a clicked node and exposes actual thinking, response and action", async () => {
  const read = vi
    .spyOn(businessFlowsApi, "nodeTrace")
    .mockResolvedValue(trace());
  const flow = businessFlowRun();
  render(
    <App>
      <BusinessFlowMonitor flow={flow} onLocate={vi.fn()} />
    </App>,
  );
  expect(read).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /分析项目资料，/ }));
  await screen.findByText("核对实际输入后先预检，再提交计算。");
  expect(read).toHaveBeenCalledWith(
    flow.id,
    "analyse",
    expect.objectContaining({ offset: 0 }),
  );
  fireEvent.click(screen.getByText("实际响应", { exact: true }));
  expect(screen.getByText("实际响应-analyse")).toBeVisible();
  expect(screen.getByText("预检通过，尚未计算")).toBeVisible();
});

it("aborts an old node read and does not display its late response after switching", async () => {
  let finish!: (value: NodeTrace) => void;
  let firstSignal: AbortSignal | undefined;
  vi.spyOn(businessFlowsApi, "nodeTrace")
    .mockImplementationOnce((_flow, _node, options) => {
      firstSignal = options?.signal;
      return new Promise((resolve) => {
        finish = resolve;
      });
    })
    .mockResolvedValueOnce(trace("finish"));
  const view = render(
    <App>
      <BusinessFlowNodeTrace flowId="flow" nodeId="analyse" />
    </App>,
  );
  await waitFor(() => expect(firstSignal).toBeDefined());
  view.rerender(
    <App>
      <BusinessFlowNodeTrace flowId="flow" nodeId="finish" />
    </App>,
  );
  await screen.findByText("核对实际输入后先预检，再提交计算。");
  expect(firstSignal?.aborted).toBe(true);
  await act(async () => finish(trace("analyse")));
  fireEvent.click(screen.getByText("实际响应", { exact: true }));
  expect(screen.getByText("实际响应-finish")).toBeVisible();
  expect(screen.queryByText("实际响应-analyse")).not.toBeInTheDocument();
});

it("clears saved trace content when current permission is revoked", async () => {
  vi.spyOn(businessFlowsApi, "nodeTrace")
    .mockResolvedValueOnce(trace())
    .mockRejectedValueOnce(new ApiError("资料已撤权", 403));
  render(
    <App>
      <BusinessFlowNodeTrace flowId="flow" nodeId="analyse" />
    </App>,
  );
  await screen.findByText("核对实际输入后先预检，再提交计算。");
  fireEvent.click(screen.getByRole("button", { name: "读取最新节点记录" }));
  await screen.findByText("资料已撤权");
  expect(
    screen.queryByText("核对实际输入后先预检，再提交计算。"),
  ).not.toBeInTheDocument();
});
