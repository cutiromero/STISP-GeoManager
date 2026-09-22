import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveProject } from "../projects/session";
const { request } = vi.hoisted(() => ({
  request: vi.fn().mockResolvedValue({}),
}));
vi.mock("./client", () => ({ requestJson: request }));
import { platformApi } from "./platform";

afterEach(() => {
  request.mockClear();
  setActiveProject("1");
});
describe("platform-wide knowledge and news", () => {
  it.each(["2", "3", "all"])(
    "keeps editorial content public while selected project is %s",
    async (selected) => {
      setActiveProject(selected);
      await platformApi.articles({ kind: "knowledge" });
      expect(request).toHaveBeenLastCalledWith(
        expect.stringContaining("kind=knowledge"),
        { projectTagId: "1" },
      );
      await platformApi.article(7);
      expect(request).toHaveBeenLastCalledWith("/api/content/articles/7/", {
        projectTagId: "1",
      });
      await platformApi.saveArticle(null, {
        kind: "knowledge",
        title: "公共知识",
        category: "遥感基础",
        body: "正文",
        status: "draft",
      });
      expect(request.mock.lastCall?.[1].projectTagId).toBe("1");
      await platformApi.articles({ kind: "news" });
      expect(request.mock.lastCall?.[1].projectTagId).toBe("1");
      await platformApi.saveArticle(null, {
        kind: "news",
        title: "团队动态",
        category: "学术会议",
        body: "正文",
        status: "draft",
      });
      expect(request.mock.lastCall?.[1].projectTagId).toBe("1");
    },
  );
});
