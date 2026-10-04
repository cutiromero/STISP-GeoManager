import { App as AntApp } from "antd";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { KnowledgeWikiPage } from "../api/generated/types.gen";
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
function wikiPage(
  id: string,
  title: string,
  content: string,
  links: string[] = [],
): KnowledgeWikiPage {
  return {
    id,
    title,
    content,
    links,
    summary: "",
    status: "published",
    version: 1,
    sources: [],
    projectTagId: 1,
  };
}
async function openWiki(pages: KnowledgeWikiPage[]) {
  api.wiki.mockResolvedValue({
    available: true,
    active: false,
    pendingTasks: 0,
    detail: "",
    items: pages,
  });
  show("wiki");
  fireEvent.click(
    await screen.findByRole("button", { name: `阅读主题：${pages[0]?.title}` }),
  );
  await screen.findByRole("heading", { name: pages[0]?.title, level: 2 });
  const content = document.querySelector<HTMLElement>(
    ".knowledge-wiki-content",
  );
  if (!content) throw new Error("Wiki content did not open");
  return content;
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
it("opens a visible inline Wiki target in the same library", async () => {
  const content = await openWiki([
    wikiPage("1:overview", "识别概览", "参考 **[[method|查看方法]]**。", [
      "1:method",
      "2:method",
    ]),
    wikiPage("1:method", "本库方法", "## 地面验证步骤\n与野外样本核对。"),
    wikiPage("2:method", "其他库方法", "## 其他知识空间的内容"),
  ]);
  const link = within(content).getByRole("button", { name: "查看方法" });
  expect(link.closest("strong")).not.toBeNull();
  fireEvent.click(link);
  expect(
    await screen.findByRole("heading", { name: "本库方法", level: 2 }),
  ).toBeVisible();
  expect(screen.getByRole("heading", { name: "地面验证步骤" })).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: "其他知识空间的内容" }),
  ).toBeNull();
});
it("keeps missing, unlinked, external and other-library Wiki targets as plain text", async () => {
  const labels = [
    "未知主题",
    "未关联主题",
    "不可见主题",
    "站外地址",
    "脚本地址",
    "其他库主题",
  ];
  const content = await openWiki([
    wikiPage(
      "1:overview",
      "链接边界",
      [
        "[[unknown|未知主题]]",
        "[[unlinked|未关联主题]]",
        "[[hidden|不可见主题]]",
        "[[https://example.org|站外地址]]",
        "[[javascript:alert(1)|脚本地址]]",
        "[[2:other|其他库主题]]",
      ].join("\n"),
      ["1:hidden", "2:other"],
    ),
    wikiPage("1:unlinked", "未建立关联的页面", "没有声明关联。"),
    wikiPage("2:other", "其他知识库的页面", "来自另一知识空间。"),
  ]);
  for (const label of labels) {
    expect(within(content).getByText(label)).toBeVisible();
  }
  expect(within(content).queryAllByRole("button")).toHaveLength(0);
  expect(within(content).queryAllByRole("link")).toHaveLength(0);
});
it("preserves table columns when Wiki links contain label separators", async () => {
  const content = await openWiki([
    wikiPage(
      "1:overview",
      "方法对照",
      [
        "| [[method|判断方法]] | 说明 |",
        "| --- | --- |",
        "| [[method|光谱判别]] | [[unknown|待补主题]] |",
      ].join("\n"),
      ["1:method"],
    ),
    wikiPage("1:method", "光谱识别方法", "## 光谱与样本核对"),
  ]);
  const table = within(content).getByRole("table");
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
  const cells = within(table).getAllByRole("cell");
  expect(cells).toHaveLength(2);
  expect(cells[0]).toHaveTextContent("光谱判别");
  expect(cells[1]).toHaveTextContent("待补主题");
  expect(within(table).getByRole("button", { name: "判断方法" })).toBeVisible();
  fireEvent.click(within(table).getByRole("button", { name: "光谱判别" }));
  expect(
    await screen.findByRole("heading", { name: "光谱与样本核对" }),
  ).toBeVisible();
});
it("renders asterisk lists as lists and keeps HTML and code as inert text", async () => {
  const html = '<img src="missing" onerror="window.wikiUnsafe=true">';
  const script = "<script>window.wikiUnsafe=true</script>";
  const content = await openWiki([
    wikiPage(
      "1:overview",
      "安全格式",
      [
        "* 第一项",
        "* **第二项**",
        "- 第三项",
        "",
        html,
        script,
        "[[unknown|<iframe src=about:blank></iframe>]]",
        "```text",
        "[[method|代码中的链接]]",
        "```",
      ].join("\n"),
      ["1:method"],
    ),
    wikiPage("1:method", "关联方法", "方法内容。"),
  ]);
  const list = within(content).getByRole("list");
  expect(list.tagName).toBe("UL");
  expect(
    within(list)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual(["第一项", "第二项", "第三项"]);
  expect(within(content).getByText(html)).toBeVisible();
  expect(within(content).getByText(script)).toBeVisible();
  expect(
    within(content).getByText("<iframe src=about:blank></iframe>"),
  ).toBeVisible();
  expect(content.querySelector("script, img, iframe")).toBeNull();
  expect(content.querySelector("pre code")).toHaveTextContent(
    "[[method|代码中的链接]]",
  );
  expect(within(content).queryAllByRole("button")).toHaveLength(0);
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
