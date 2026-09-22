import { App as AntApp } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ContentArticle } from "../api/platform";
import { setActiveProject } from "../projects/session";
import { setLocale } from "../i18n";

const api = vi.hoisted(() => ({
  articles: vi.fn(),
  article: vi.fn(),
  saveArticle: vi.fn(),
  uploadAsset: vi.fn(),
  discardAsset: vi.fn(),
}));
vi.mock("../api/platform", () => ({ platformApi: api }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 1 } }),
}));
vi.mock("../components/WorkspaceHeader", () => ({
  default: () => <div>导航</div>,
}));
import EditorialPage from "./EditorialPage";

const article: ContentArticle = {
  id: 1,
  projectTagId: 1,
  kind: "news",
  title: "学术会议",
  summary: "报告资料",
  category: "学术会议",
  body: "原有正文",
  status: "draft",
  source: "会议海报",
  links: [],
  eventDate: "2026-09-11",
  publishedAt: "",
  coverUrl: "",
  pinned: false,
  revision: 3,
  assets: [
    {
      id: 10,
      name: "封面.png",
      url: "/test-cover.png",
      mimeType: "image/png",
      caption: "原图说明",
      pending: false,
    },
  ],
};
function show() {
  return render(
    <AntApp>
      <MemoryRouter initialEntries={["/news/1"]}>
        <Routes>
          <Route
            path="/news/:articleId"
            element={<EditorialPage kind="news" />}
          />
        </Routes>
      </MemoryRouter>
    </AntApp>,
  );
}
beforeEach(async () => {
  await setLocale("zh-CN");
  vi.clearAllMocks();
  setActiveProject("1");
  api.articles.mockResolvedValue({ items: [article], total: 1, canEdit: true });
  api.article.mockResolvedValue(article);
  api.saveArticle.mockResolvedValue({ ...article, revision: 4 });
  api.discardAsset.mockResolvedValue({ detail: "已撤销" });
});
describe("editorial content management", () => {
  it("preserves unsaved text, caption and revision while uploading an attachment", async () => {
    const view = show();
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "编辑内容" },
        { timeout: 5000 },
      ),
    );
    fireEvent.change(screen.getByLabelText("标题"), {
      target: { value: "更新的会议标题" },
    });
    fireEvent.change(screen.getByLabelText("图片或附件说明: 封面.png"), {
      target: { value: "修改的图注" },
    });
    api.uploadAsset.mockResolvedValue({
      id: 11,
      name: "资料.pdf",
      url: "/test.pdf",
      mimeType: "application/pdf",
      caption: "",
      pending: true,
    });
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: {
        files: [
          new File(["%PDF-test"], "资料.pdf", { type: "application/pdf" }),
        ],
      },
    });
    await screen.findByLabelText("图片或附件说明: 资料.pdf");
    expect(screen.getByLabelText("标题")).toHaveValue("更新的会议标题");
    expect(screen.getByLabelText("图片或附件说明: 封面.png")).toHaveValue(
      "修改的图注",
    );
    fireEvent.click(screen.getByRole("button", { name: "设为封面" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /保\s*存/,
      }),
    );
    await waitFor(() =>
      expect(api.saveArticle).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          title: "更新的会议标题",
          revision: 3,
          commitAssetIds: [11],
          coverAssetId: 10,
          assetCaptions: [
            { id: 10, caption: "修改的图注" },
            { id: 11, caption: "" },
          ],
        }),
      ),
    );
    view.unmount();
  });
  it("does not let a delayed category response overwrite the current filter", async () => {
    let resolveOld!: (result: unknown) => void;
    api.articles.mockImplementation((query) =>
      query.category === "学术交流"
        ? new Promise((resolve) => {
            resolveOld = resolve;
          })
        : Promise.resolve({
            items: [{ ...article, title: query.category || "初始条目" }],
            total: 1,
            canEdit: false,
          }),
    );
    render(
      <AntApp>
        <MemoryRouter initialEntries={["/news"]}>
          <Routes>
            <Route path="/news" element={<EditorialPage kind="news" />} />
          </Routes>
        </MemoryRouter>
      </AntApp>,
    );
    await screen.findByText("初始条目");
    fireEvent.click(
      screen.getByRole("button", { name: "学术交流", exact: true }),
    );
    await waitFor(() => expect(resolveOld).toBeDefined());
    fireEvent.click(
      screen.getByRole("button", { name: "科研进展", exact: true }),
    );
    await waitFor(() =>
      expect(document.querySelector(".editorial-card h3")?.textContent).toBe(
        "科研进展",
      ),
    );
    resolveOld({
      items: [{ ...article, title: "迟到旧条目" }],
      total: 1,
      canEdit: false,
    });
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(screen.queryByText("迟到旧条目")).not.toBeInTheDocument();
    expect(document.querySelector(".editorial-card h3")?.textContent).toBe(
      "科研进展",
    );
  });
  it("discards a staged upload when editing is cancelled", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "编辑内容" }));
    api.uploadAsset.mockResolvedValue({
      id: 99,
      name: "staged.pdf",
      url: "/pending",
      mimeType: "application/pdf",
      caption: "",
      pending: true,
    });
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: {
        files: [
          new File(["%PDF-test"], "staged.pdf", { type: "application/pdf" }),
        ],
      },
    });
    await screen.findByLabelText("图片或附件说明: staged.pdf");
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /取\s*消/,
      }),
    );
    await waitFor(() => expect(api.discardAsset).toHaveBeenCalledWith(99));
    expect(api.saveArticle).not.toHaveBeenCalled();
  });
  it("translates controls while retaining the original article body", async () => {
    await setLocale("en-US");
    show();
    expect(
      await screen.findByRole("button", { name: "Edit content" }),
    ).toBeEnabled();
    expect(screen.getByText("原有正文")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit content" }));
    expect(screen.getByLabelText("Title")).toHaveValue("学术会议");
    expect(
      screen.getByRole("button", { name: "Upload image or PDF" }),
    ).toBeEnabled();
  });
  it("stages removal until save and keeps news editable in a private project", async () => {
    const view = show();
    fireEvent.click(await screen.findByRole("button", { name: "编辑内容" }));
    fireEvent.click(screen.getByRole("button", { name: "移除附件" }));
    expect(api.saveArticle).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /保\s*存/,
      }),
    );
    await waitFor(() =>
      expect(api.saveArticle).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          removeAssetIds: [10],
          assetCaptions: [],
          coverAssetId: null,
        }),
      ),
    );
    view.unmount();
    setActiveProject("2");
    show();
    expect(
      await screen.findByRole("button", { name: "编辑内容" }),
    ).toBeEnabled();
  });
});
