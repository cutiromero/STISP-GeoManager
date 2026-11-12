import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import BusinessFlowGraph from "./BusinessFlowGraph";
import BusinessFlowMonitor from "./BusinessFlowMonitor";
import {
  businessFlowProgress,
  businessFlowReturn,
} from "./businessFlowPresentation";
import { businessFlowRun, geologySpec } from "./businessFlow.testFixtures";

function returnedFlow(): BusinessFlowRun {
  const flow = businessFlowRun({ status: "queued" });
  flow.nodes[0] = {
    ...flow.nodes[0]!,
    status: "pending",
    executor: { status: "pending" },
    reviewer: { status: "pending" },
    human: { required: true, status: "pending", reason: "请补充依据。" },
  };
  flow.events.push({
    id: 3,
    nodeId: "analyse",
    actor: "human",
    kind: "request_changes",
    status: "queued",
    message: "请补充构造线与蚀变分布的对应依据。",
    createdAt: "2026-11-10T00:02:00Z",
  });
  return flow;
}

function graph(flow: BusinessFlowRun) {
  return (
    <App>
      <BusinessFlowGraph
        nodes={flow.definitionSnapshot.nodes}
        states={flow.nodes}
        events={flow.events}
        currentNode={flow.currentNode}
        flowStatus={flow.status}
      />
    </App>
  );
}

it("fits all nodes and unique terminals on entry, offsets review junctions and supports zoom then fit", async () => {
  render(
    <App>
      <div style={{ width: 860 }}>
        <BusinessFlowGraph nodes={geologySpec.nodes} />
      </div>
    </App>,
  );
  const scroller = screen.getByRole("region", { name: "业务流程图，可缩放" });
  await waitFor(() =>
    expect(scroller.scrollWidth).toBeLessThanOrEqual(scroller.clientWidth + 1),
  );
  expect(
    screen.getAllByRole("button", { name: "开始", exact: true }),
  ).toHaveLength(1);
  expect(
    screen.getAllByRole("button", { name: "输出", exact: true }),
  ).toHaveLength(1);
  await waitFor(() =>
    expect(
      document.querySelector('[data-flow-review="apply:ai"]'),
    ).toBeTruthy(),
  );
  const x = (role: string) =>
    Number(
      document
        .querySelector(`[data-flow-review-junction="apply:${role}"]`)!
        .getAttribute("cx"),
    );
  expect(Math.abs(x("ai") - x("human"))).toBeGreaterThanOrEqual(30);
  const aiLink = document.querySelector<SVGPathElement>(
    '[data-flow-review="apply:ai"]',
  )!;
  const humanLink = document.querySelector<SVGPathElement>(
    '[data-flow-review="apply:human"]',
  )!;
  expect(aiLink.getAttribute("marker-end")).toBeNull();
  expect(humanLink.getAttribute("marker-end")).toBeNull();
  expect(getComputedStyle(aiLink).stroke).not.toBe(
    getComputedStyle(humanLink).stroke,
  );
  expect(getComputedStyle(aiLink).strokeDasharray).not.toBe("none");
  expect(getComputedStyle(humanLink).strokeDasharray).not.toBe("none");
  const plus = screen.getByRole("button", { name: "放大流程图" });
  fireEvent.click(plus);
  fireEvent.click(plus);
  fireEvent.click(plus);
  await waitFor(() =>
    expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth),
  );
  fireEvent.click(screen.getByRole("button", { name: /适应窗口/ }));
  await waitFor(() =>
    expect(scroller.scrollWidth).toBeLessThanOrEqual(scroller.clientWidth + 1),
  );
});

it("places distinct review gates off the task line and draws the real human return", async () => {
  const flow = returnedFlow();
  render(graph(flow));
  await waitFor(() =>
    expect(document.querySelectorAll(".flow-return-links path")).toHaveLength(
      1,
    ),
  );
  const ai = screen.getByRole("button", {
    name: "AI 审核：分析项目资料，待进入",
  });
  const human = screen.getByRole("button", {
    name: "人工审批：分析项目资料，已退回",
  });
  const main = document.querySelector<HTMLElement>(
    '[data-flow-anchor="analyse"]',
  )!;
  const next = document.querySelector<HTMLElement>(
    '[data-flow-anchor="finish"]',
  )!;
  expect(ai.getBoundingClientRect().bottom).toBeLessThan(
    main.getBoundingClientRect().top,
  );
  expect(human.getBoundingClientRect().top).toBeGreaterThan(
    main.getBoundingClientRect().bottom,
  );
  expect(main.getBoundingClientRect().top).toBe(
    next.getBoundingClientRect().top,
  );
  expect(
    document.querySelectorAll(".business-flow-graph-links > path"),
  ).toHaveLength(3);
  expect(
    document.querySelector(
      '.business-flow-graph-links > path[data-flow-edge="analyse:finish"].is-complete',
    ),
  ).toBeNull();
  expect(
    document.querySelector(".flow-return-links path.is-returned"),
  ).toBeTruthy();
  expect(screen.getByText("退回此节点")).toBeVisible();
});

it("uses one shared human hub and one AI hub with separate links and node-specific review details", async () => {
  const select = vi.fn();
  render(
    <App>
      <BusinessFlowGraph nodes={geologySpec.nodes} onSelectNode={select} />
    </App>,
  );
  expect(document.querySelectorAll('[data-flow-gate="human"]')).toHaveLength(1);
  expect(document.querySelectorAll('[data-flow-gate="ai"]')).toHaveLength(1);
  const humanNodes = geologySpec.nodes.filter(
    (node) => node.review.human || node.kind === "human",
  );
  await waitFor(() =>
    expect(
      document.querySelectorAll(
        '.flow-gate-links [data-flow-review$=":human"]',
      ),
    ).toHaveLength(humanNodes.length),
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(`人工审批：${humanNodes.length} 个节点`),
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByText(`人工审批 · ${humanNodes.length} 个节点`),
    ).toBeVisible(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "审核与处置建议，由您确认" }),
  );
  expect(select).toHaveBeenCalledExactlyOnceWith(
    geologySpec.nodes.find((node) => node.id === "apply"),
  );
});

it("keeps the return while executing again and requires a new human approval after re-review", async () => {
  const flow = returnedFlow();
  const view = render(graph(flow));
  const revised = structuredClone(flow);
  revised.status = "running";
  revised.nodes[0]!.status = "executing";
  revised.nodes[0]!.attempt = 2;
  view.rerender(graph(revised));
  expect(screen.getByText("执行中 · 第 2 次处理")).toBeVisible();
  expect(businessFlowReturn(revised.events, revised.nodes[0])?.resolved).toBe(
    false,
  );
  revised.nodes[0]!.status = "waiting_human";
  revised.nodes[0]!.executor.status = "succeeded";
  revised.nodes[0]!.reviewer = { status: "passed", decision: "accept" };
  revised.status = "waiting_approval";
  revised.events.push({
    ...revised.events[1]!,
    id: 4,
    kind: "review_accepted",
  });
  view.rerender(graph(revised));
  expect(
    screen.getByRole("button", { name: "AI 审核：分析项目资料，已通过" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "人工审批：分析项目资料，待您确认" }),
  ).toBeVisible();
  expect(
    document.querySelector(
      '.business-flow-graph-links > path[data-flow-edge="analyse:finish"].is-complete',
    ),
  ).toBeNull();
  expect(businessFlowProgress(revised).completedNodes).toBe(0);
  revised.nodes[0]!.status = "succeeded";
  revised.nodes[0]!.human.status = "approved";
  revised.events.push({
    ...revised.events[2]!,
    id: 5,
    kind: "approve",
    message: "修改后通过",
  });
  view.rerender(graph(revised));
  await waitFor(() =>
    expect(document.querySelectorAll(".flow-return-links path")).toHaveLength(
      0,
    ),
  );
  expect(screen.getByText("返工后通过")).toBeVisible();
  expect(businessFlowProgress(revised).completedNodes).toBe(1);
});

it("does not invent a return from an attempt number and distinguishes AI review from human approval", async () => {
  const flow = businessFlowRun();
  flow.nodes[0]!.attempt = 2;
  render(graph(flow));
  expect(document.querySelectorAll(".flow-return-links path")).toHaveLength(0);
  expect(screen.queryByText("退回此节点")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "AI 审核：分析项目资料，已通过" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "人工审批：分析项目资料，待您确认" }),
  ).toBeVisible();
});

it.each(["paused", "cancelled", "failed"])(
  "does not present an approval gate as live while %s",
  (status) => {
    render(graph(businessFlowRun({ status })));
    expect(
      screen.queryByRole("button", { name: /待您确认/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "人工审批：分析项目资料，未通过" }),
    ).toBeVisible();
  },
);

it("updates the monitor from shared state without reading APIs and hides feedback after access is revoked", async () => {
  const read = vi.spyOn(businessFlowsApi, "run");
  try {
    const flow = returnedFlow();
    const locate = vi.fn();
    const view = render(
      <App>
        <BusinessFlowMonitor flow={flow} onLocate={locate} />
      </App>,
    );
    const panel = screen.getByRole("complementary", { name: "业务流实时进度" });
    expect(
      within(panel).getByText("请补充构造线与蚀变分布的对应依据。"),
    ).toBeVisible();
    fireEvent.click(
      within(panel).getByRole("button", { name: "查看节点内容" }),
    );
    expect(locate).toHaveBeenCalledExactlyOnceWith("analyse");
    const next = structuredClone(flow);
    next.nodes[0]!.status = "executing";
    next.nodes[0]!.attempt = 2;
    next.status = "running";
    view.rerender(
      <App>
        <BusinessFlowMonitor flow={next} onLocate={locate} />
      </App>,
    );
    expect(within(panel).getByText("执行中 · 第 2 次")).toBeVisible();
    expect(read).not.toHaveBeenCalled();
    view.rerender(
      <App>
        <BusinessFlowMonitor flow={next} onLocate={locate} accessBlocked />
      </App>,
    );
    expect(
      within(panel).queryByText("请补充构造线与蚀变分布的对应依据。"),
    ).not.toBeInTheDocument();
    expect(
      within(panel).queryByRole("button", { name: "查看节点内容" }),
    ).not.toBeInTheDocument();
  } finally {
    read.mockRestore();
  }
});

it("keeps parallel nodes in a shared dependency level in the right monitor", () => {
  const flow = structuredClone(businessFlowRun());
  flow.definitionSnapshot.nodes.splice(1, 0, {
    ...flow.definitionSnapshot.nodes[0]!,
    id: "parallel",
    title: "并行核查",
  });
  flow.definitionSnapshot.nodes[2]!.dependsOn.push("parallel");
  render(
    <App>
      <BusinessFlowMonitor flow={flow} onLocate={vi.fn()} />
    </App>,
  );
  const level = document.querySelector(".flow-monitor-level.is-parallel")!;
  expect(level.querySelectorAll("button")).toHaveLength(2);
  expect(screen.getByText("并行节点")).toBeVisible();
});

it("contains a long diagram on small screens and exposes the progress toggle to keyboard users", async () => {
  await page.viewport(390, 844);
  try {
    render(
      <App>
        <div style={{ position: "relative", height: 760 }}>
          <BusinessFlowMonitor flow={returnedFlow()} onLocate={vi.fn()} />
        </div>
      </App>,
    );
    const toggle = screen.getByRole("button", { name: "展开流程进度" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "展开流程全图" }));
    const dialog = await screen.findByRole("dialog");
    await act(
      async () => new Promise((resolve) => requestAnimationFrame(resolve)),
    );
    const scroller = dialog.querySelector<HTMLElement>(
      ".business-flow-graph-scroller",
    )!;
    expect(scroller.clientWidth).toBeLessThan(390);
    expect(scroller.scrollWidth).toBeLessThanOrEqual(scroller.clientWidth + 1);
    expect(
      within(dialog).getAllByRole("button", { name: "开始", exact: true }),
    ).toHaveLength(1);
    expect(
      within(dialog).getAllByRole("button", { name: "输出", exact: true }),
    ).toHaveLength(1);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);
  } finally {
    await page.viewport(1600, 900);
  }
});
