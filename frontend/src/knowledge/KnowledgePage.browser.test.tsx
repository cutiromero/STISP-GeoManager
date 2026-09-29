import { App as AntApp } from "antd";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "vitest/browser";
import type { KnowledgeEntry } from "../api/generated/types.gen";

const api = vi.hoisted(() => ({
  entries: vi.fn(),
  save: vi.fn(),
  check: vi.fn(),
}));
vi.mock("../api/knowledge", () => ({ knowledgeApi: api }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 1 } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({ current: "2" }),
}));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <div>平台导航</div>,
}));
import KnowledgePage from "./KnowledgePage";

const publicEntry: KnowledgeEntry = {
  id: 1,
  projectTagId: 1,
  revision: 2,
  updatedAt: "2026-09-29T08:00:00Z",
  title: "矿物组合的条件核查",
  category: "矿物学",
  subject: "石英",
  predicate: "条件互斥",
  object: "霞石",
  statement: "矿物关系须结合适用体系与形成阶段解释。",
  explanation: "保留原始观测并复核平衡条件。",
  conditions: ["同阶段平衡体系"],
  exceptions: ["继承矿物需另行判断"],
  aliases: ["矿物共生"],
  sources: [
    {
      title: "核查资料",
      url: "https://example.org/evidence",
      locator: "第 2 章",
      excerpt: "来源证据",
    },
  ],
  status: "published",
  ruleKind: "mineral_equilibrium",
  ruleConfig: { minerals: ["石英", "霞石"], system: "SiO2" },
};
const privateEntry: KnowledgeEntry = {
  ...publicEntry,
  id: 2,
  projectTagId: 2,
  title: "植被指数的数值范围",
  category: "遥感",
  subject: "NDVI",
  predicate: "有效范围",
  object: "归一化指数",
  ruleKind: "numeric_range",
  ruleConfig: { field: "ndvi", minimum: -1, maximum: 1 },
};
function show() {
  return render(
    <AntApp>
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.entries.mockResolvedValue({
    items: [publicEntry, privateEntry],
    total: 2,
    categories: ["矿物学", "遥感"],
    canEdit: false,
  });
});
afterEach(cleanup);

describe("knowledge network and records", () => {
  it("filters records by pointer and keyboard and resets the network", async () => {
    show();
    const node = await screen.findByRole("button", { name: "筛选节点：石英" });
    fireEvent.click(screen.getByRole("button", { name: /暂停浮动/ }));
    await userEvent.click(node);
    expect(
      screen.getByRole("button", { name: publicEntry.title, exact: true }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: privateEntry.title, exact: true }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重置知识网络" }));
    expect(
      screen.getByRole("button", { name: privateEntry.title, exact: true }),
    ).toBeVisible();
    fireEvent.keyDown(node, { key: "Enter" });
    expect(screen.queryByRole("button", { name: privateEntry.title, exact: true })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "新建知识" }),
    ).not.toBeInTheDocument();
  });

  it("sends explicit search words to the server", async () => {
    show();
    await screen.findByRole("button", { name: publicEntry.title, exact: true });
    const search = screen.getByRole("searchbox", { name: "检索知识" });
    fireEvent.change(search, { target: { value: "石英" } });
    fireEvent.keyDown(search, { key: "Enter", code: "Enter", keyCode: 13 });
    await waitFor(() =>
      expect(api.entries).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "石英", offset: 0 }),
      ),
    );
  });

  it("offers editing only for current-project records", async () => {
    api.entries.mockResolvedValue({
      items: [publicEntry, privateEntry],
      total: 2,
      categories: ["矿物学", "遥感"],
      canEdit: true,
    });
    show();
    fireEvent.click(
      await screen.findByRole("button", {
        name: publicEntry.title,
        exact: true,
      }),
    );
    expect(
      screen.queryByRole("button", { name: /维护条目/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: privateEntry.title, exact: true }),
    );
    expect(
      await screen.findByRole("button", { name: /维护条目/ }),
    ).toBeVisible();
  });

  it("shows a recoverable error and retries instead of retaining stale data", async () => {
    api.entries.mockRejectedValueOnce(new Error("项目访问权限已撤回"));
    show();
    expect(await screen.findByText("项目访问权限已撤回")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: publicEntry.title, exact: true }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(
      await screen.findByRole("button", {
        name: publicEntry.title,
        exact: true,
      }),
    ).toBeVisible();
  });

  it("checks only the facts explicitly entered by the user", async () => {
    api.check.mockResolvedValue({
      checked: 1,
      findings: [
        {
          entryId: 1,
          title: publicEntry.title,
          status: "needs_context",
          detail: "需补充平衡条件",
          revision: 2,
          sources: publicEntry.sources,
        },
      ],
    });
    show();
    fireEvent.click(
      await screen.findByRole("button", {
        name: publicEntry.title,
        exact: true,
      }),
    );
    const facts = screen.getByRole("textbox", { name: "核查事实 JSON" });
    expect(facts).toHaveValue("{}");
    fireEvent.change(facts, { target: { value: '{"minerals":["石英"]}' } });
    fireEvent.click(screen.getByRole("button", { name: "核查条件" }));
    await waitFor(() =>
      expect(api.check).toHaveBeenCalledWith({
        facts: { minerals: ["石英"] },
        entryIds: [1],
      }),
    );
    expect(await screen.findByText("需补充平衡条件")).toBeVisible();
  });
});
