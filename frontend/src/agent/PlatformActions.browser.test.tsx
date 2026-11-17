import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { expect, it } from "vitest";
import PlatformActions, { platformActionUrl } from "./PlatformActions";
import type { AgentPlatformAction } from "../api/generated/types.gen";
it("opens a real private map through a safe project-bound button", () => {
  const action: AgentPlatformAction = {
    kind: "workspace",
    sceneId: 9,
    projectId: 3,
    title: "岩性分类地图",
    resourceIds: [12],
  };
  render(
    <App>
      <PlatformActions actions={[action]} projectId={3} />
    </App>,
  );
  const link = screen.getByRole("link", { name: /在地理工作台查看/ });
  const url = new URL(link.getAttribute("href")!, "http://localhost");
  expect(url.pathname).toBe("/map");
  expect(url.searchParams.get("sceneId")).toBe("9");
  expect(url.searchParams.get("projectTagId")).toBe("3");
  expect(link).toHaveAttribute("rel", "noopener");
  expect(screen.getByText(/原始资料未修改/)).toBeVisible();
});
it("does not trust model URLs or cross-project actions", () => {
  const injected = {
    kind: "page",
    page: "javascript:alert(1)",
    projectId: 3,
    title: "打开",
    resourceIds: [],
    url: "https://example.com",
  } as unknown as AgentPlatformAction;
  expect(platformActionUrl(injected, 3)).toBeNull();
  expect(
    platformActionUrl(
      {
        kind: "workspace",
        sceneId: 1,
        projectId: 4,
        title: "其他项目",
        resourceIds: [],
      },
      3,
    ),
  ).toBeNull();
});

it("offers only project-bound downloads reconstructed from a real job id", () => {
  const action: AgentPlatformAction = {
    kind: "export",
    jobId: "a".repeat(32),
    projectId: 3,
    title: "下载导出文件",
    resourceIds: [],
  };
  render(
    <App>
      <PlatformActions actions={[action]} projectId={3} />
    </App>,
  );
  const link = screen.getByRole("link", { name: /下载导出文件/ });
  expect(link).toHaveAttribute(
    "href",
    `/api/catalog/export/jobs/${"a".repeat(32)}/download/?projectTagId=3`,
  );
  expect(platformActionUrl({ ...action, projectId: 4 }, 3)).toBeNull();
  expect(platformActionUrl({ ...action, jobId: "../private" }, 3)).toBeNull();
});
