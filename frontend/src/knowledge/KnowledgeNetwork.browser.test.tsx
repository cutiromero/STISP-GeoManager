import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import type {
  KnowledgeDomain,
  KnowledgeEntry,
} from "../api/generated/types.gen";
import KnowledgeNetwork from "./KnowledgeNetwork";
import "./knowledge.css";

const groups: {
  domain: KnowledgeDomain;
  subject: string;
  objects: string[];
}[] = [
  {
    domain: "remote_sensing",
    subject: "遥感影像",
    objects: [
      "光谱分辨率",
      "空间分辨率",
      "大气校正",
      "几何校正",
      "反射率",
      "影像配准",
    ],
  },
  {
    domain: "pipelines",
    subject: "管道走廊",
    objects: [
      "地表形变",
      "滑坡迹象",
      "地质灾害",
      "走廊巡查",
      "风险复核",
      "地面调查",
    ],
  },
  {
    domain: "geology",
    subject: "地质填图",
    objects: [
      "岩性组合",
      "构造线索",
      "光谱解译",
      "矿物关系",
      "地层接触",
      "野外验证",
    ],
  },
  {
    domain: "arid_ecology",
    subject: "NDVI",
    objects: [
      "植被变化",
      "季节差异",
      "水分条件",
      "土壤背景",
      "生态监测",
      "覆盖度核查",
    ],
  },
];
const entries: KnowledgeEntry[] = groups.flatMap((group, groupIndex) =>
  group.objects.map((object, index) => ({
    id: groupIndex * 10 + index + 1,
    projectTagId: 1,
    revision: 1,
    updatedAt: "2026-10-10T00:00:00Z",
    title: `${group.subject}：${object}`,
    category: "测试夹具",
    domain: group.domain,
    subject: group.subject,
    object,
    predicate: "关联",
    statement: "用于验证布局与交互的测试关系",
    explanation: "",
    conditions: [],
    exceptions: [],
    aliases: [],
    sources: [],
    status: "published",
    ruleKind: "none",
    ruleConfig: {},
  })),
);

function show() {
  const open = vi.fn(),
    domain = vi.fn();
  function Harness() {
    const [selected, setSelected] = useState<string | null>(null);
    return (
      <AntApp>
        <main
          style={{
            maxWidth: 1200,
            width: "calc(100% - 32px)",
            margin: "24px auto",
          }}
        >
          <KnowledgeNetwork
            entries={entries}
            selected={selected}
            onSelect={setSelected}
            onOpen={open}
            onDomainSelect={domain}
          />
        </main>
      </AntApp>
    );
  }
  return { ...render(<Harness />), open, domain };
}
afterEach(async () => {
  vi.restoreAllMocks();
  await page.viewport(1600, 900);
});

it("keeps a restrained overview, reveals labels on focus and opens real relation evidence", async () => {
  const { container, open, domain } = show();
  await screen.findByRole("button", { name: "筛选节点：NDVI" });
  await waitFor(() =>
    expect(
      container.querySelectorAll(".knowledge-network-region"),
    ).toHaveLength(4),
  );
  const labels = [
    ...container.querySelectorAll<SVGTextElement>(
      ".knowledge-network-node text",
    ),
  ];
  expect(
    labels.filter((label) => getComputedStyle(label).opacity === "1").length,
  ).toBeLessThanOrEqual(8);
  const minor = screen.getByRole("button", { name: "筛选节点：水分条件" });
  fireEvent.focus(minor);
  expect(getComputedStyle(minor.querySelector("text")!).opacity).toBe("1");
  fireEvent.keyDown(minor, { key: "Enter" });
  expect(minor).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(/正在查看/)).toHaveTextContent("水分条件");
  fireEvent.click(
    screen.getByRole("button", { name: "查看关系：NDVI：水分条件" }),
  );
  expect(open).toHaveBeenCalledWith(
    entries.find((entry) => entry.object === "水分条件"),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "聚焦知识分区：遥感基础" }),
  );
  expect(domain).toHaveBeenCalledWith("remote_sensing");
  fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
  expect(screen.queryByText(/正在查看/)).not.toBeInTheDocument();
  fireEvent.blur(minor);
  await page.screenshot({
    path: "../../test-results/knowledge-atlas-desktop.png",
  });
});

it("zooms around the wheel pointer, pans blank space without selecting and resets to fit", async () => {
  vi.spyOn(Element.prototype, "setPointerCapture").mockImplementation(() => {});
  const { container } = show();
  const svg = container.querySelector<SVGSVGElement>(".knowledge-network-svg")!;
  const viewport = container.querySelector<SVGGElement>(
    ".knowledge-network-viewport",
  )!;
  const canvas = container.querySelector(".knowledge-network-canvas")!;
  await waitFor(() => expect(svg.viewBox.baseVal.width).toBeGreaterThan(1000));
  const before = viewport.getScreenCTM()!;
  const position = new DOMPoint(360, 260).matrixTransform(before);
  fireEvent.wheel(svg, {
    clientX: position.x,
    clientY: position.y,
    deltaY: -100,
  });
  expect(screen.getByLabelText("知识网络缩放比例")).toHaveTextContent("122%");
  const after = new DOMPoint(360, 260).matrixTransform(
    viewport.getScreenCTM()!,
  );
  expect(Math.abs(after.x - position.x)).toBeLessThan(0.5);
  expect(Math.abs(after.y - position.y)).toBeLessThan(0.5);
  const original = viewport.getAttribute("transform");
  fireEvent.pointerDown(canvas, {
    pointerId: 1,
    button: 0,
    clientX: position.x,
    clientY: position.y,
  });
  fireEvent.pointerMove(svg, {
    pointerId: 1,
    clientX: position.x + 80,
    clientY: position.y + 40,
  });
  fireEvent.pointerUp(svg, {
    pointerId: 1,
    clientX: position.x + 80,
    clientY: position.y + 40,
  });
  expect(viewport.getAttribute("transform")).not.toBe(original);
  const panned = new DOMPoint(360, 260).matrixTransform(
    viewport.getScreenCTM()!,
  );
  expect(panned.x - after.x).toBeCloseTo(80, 1);
  expect(panned.y - after.y).toBeCloseTo(40, 1);
  expect(container.querySelector(".knowledge-network-feedback")).toBeNull();
  expect(
    container.querySelector(".knowledge-network-node.is-selected"),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重置知识网络" }));
  expect(screen.getByLabelText("知识网络缩放比例")).toHaveTextContent("100%");
  expect(viewport).toHaveAttribute("transform", "translate(0 0) scale(1)");
  for (let index = 0; index < 5; index += 1)
    fireEvent.click(screen.getByRole("button", { name: "缩小知识网络" }));
  const unfocused = container.querySelector(
    ".knowledge-network-node:not(.is-selected)",
  )!;
  expect(getComputedStyle(unfocused.querySelector("text")!).opacity).toBe("0");
});

it("adapts the graph and controls to 390 pixels and keeps node positions stable", async () => {
  await page.viewport(390, 844);
  const { container } = show();
  const node = screen.getByRole("button", { name: "筛选节点：NDVI" });
  const svg = container.querySelector<SVGSVGElement>(".knowledge-network-svg")!;
  await waitFor(() => expect(svg.viewBox.baseVal.width).toBeLessThan(390));
  const start = node.getAttribute("transform");
  await new Promise((resolve) => window.setTimeout(resolve, 180));
  expect(node).toHaveAttribute("transform", start!);
  expect(container.scrollWidth).toBeLessThanOrEqual(390);
  const bounds = svg.getBoundingClientRect();
  for (const region of container.querySelectorAll(
    ".knowledge-network-region-boundary",
  )) {
    const box = region.getBoundingClientRect();
    expect(box.left).toBeGreaterThanOrEqual(bounds.left);
    expect(box.right).toBeLessThanOrEqual(bounds.right + 0.1);
  }
  await page.screenshot({
    path: "../../test-results/knowledge-atlas-mobile.png",
  });
});
