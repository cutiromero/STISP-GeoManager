import { App as AntApp } from "antd";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({
  documents: vi.fn(),
  wiki: vi.fn(),
  searchDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  retryDocument: vi.fn(),
}));
vi.mock("../api/knowledge", () => ({ knowledgeApi: api }));
import KnowledgeLibrary from "./KnowledgeLibrary";
function show(mode: "library" | "wiki" = "library") {
  return render(
    <AntApp>
      <MemoryRouter>
        <KnowledgeLibrary mode={mode} />
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.documents.mockResolvedValue({
    items: [
      {
        id: 7,
        title: "光谱方法",
        filename: "method.pdf",
        visibility: "project",
        projectTagId: 1,
        status: "completed",
        canManage: false,
        detail: "索引已完成",
        sourceUrl: "https://doi.org/10.3133/sim3190",
      },
    ],
    enabled: true,
    canUpload: false,
    detail: "",
  });
  api.wiki.mockResolvedValue({
    items: [],
    pendingTasks: 0,
    active: false,
    available: true,
    detail: "",
  });
});
afterEach(cleanup);
it("shows semantic evidence and its source, with upload gated by capability", async () => {
  api.searchDocuments.mockResolvedValue({
    available: true,
    detail: "",
    items: [
      {
        documentId: 7,
        title: "蚀变资料",
        content: "第 3 页：光谱识别需要结合地面验证。",
        score: 0.8,
        matchType: "vector",
        chunkId: "c1",
        sourceUrl: "https://doi.org/10.3133/sim3190",
      },
    ],
  });
  show();
  await screen.findByText("method.pdf · 公共资料 · 项目成员可见");
  expect(screen.queryByRole("button", { name: /添加资料/ })).toBeNull();
  fireEvent.change(screen.getByRole("searchbox", { name: "检索资料原文" }), {
    target: { value: "寻找蚀变区域" },
  });
  fireEvent.click(screen.getByRole("button", { name: "检索原文" }));
  await screen.findByText("第 3 页：光谱识别需要结合地面验证。");
  expect(api.searchDocuments).toHaveBeenCalledWith("寻找蚀变区域");
  expect(screen.getByText("语义匹配")).toBeVisible();
  expect(screen.getByRole("link", { name: /查看原始来源/ })).toHaveAttribute(
    "href",
    "https://doi.org/10.3133/sim3190",
  );
});
it("opens Wiki through the relation graph and renders generated text safely", async () => {
  api.wiki.mockResolvedValue({
    available: true,
    active: false,
    pendingTasks: 0,
    detail: "",
    items: [
      {
        id: "1:alteration",
        title: "蚀变识别",
        summary: "遥感与地面资料",
        content: "## 识别方法\n<script>window.leaked=true</script>",
        version: 1,
        status: "published",
        sources: [
          {
            documentId: 7,
            title: "原始文献",
            sourceUrl: "https://example.org/paper",
          },
        ],
        links: [],
        projectTagId: 1,
      },
    ],
  });
  show("wiki");
  fireEvent.click(
    await screen.findByRole("button", { name: "阅读主题：蚀变识别" }),
  );
  expect(
    await screen.findByRole("heading", { name: "识别方法" }),
  ).toBeVisible();
  expect(screen.getByText("<script>window.leaked=true</script>")).toBeVisible();
  expect(document.querySelector(".knowledge-wiki-content script")).toBeNull();
  expect(screen.getByRole("link", { name: /原始文献/ })).toHaveAttribute(
    "href",
    "https://example.org/paper",
  );
});
it("retries a failed document and shows the updated state", async () => {
  api.documents.mockResolvedValueOnce({
    enabled: true,
    canUpload: true,
    detail: "",
    items: [
      {
        id: 7,
        title: "光谱方法",
        filename: "method.pdf",
        projectTagId: 1,
        visibility: "owner_only",
        status: "failed",
        canManage: true,
        detail: "知识服务连接失败",
        sourceUrl: "",
      },
    ],
  });
  api.retryDocument.mockResolvedValue({ id: 7, status: "processing" });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "重试处理" }));
  await waitFor(() => expect(api.retryDocument).toHaveBeenCalledWith(7));
  expect(await screen.findByText("可检索")).toBeVisible();
});
