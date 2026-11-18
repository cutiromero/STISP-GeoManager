import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { requestJson } from "../api/client";
import TaskResultCatalogue from "./TaskResultCatalogue";
import { setActiveProject } from "../projects/session";

vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  requestJson: vi.fn(),
}));

it("按任务展示图表，明确确认后登记主成果", async () => {
  const groupId = "f6c850b0-0915-4d02-aaf6-174f33c62ebc";
  setActiveProject("2");
  let registered = false;
  vi.mocked(requestJson).mockImplementation(async (url) => {
    if (url.includes("registration")) {
      registered = true;
      return { id: 33, scene: "landcover" } as never;
    }
    return {
      hasMore: false,
      items: [
        {
          id: groupId,
          workflowId: groupId,
          name: "环江一次解译任务",
          createdAt: "2026-11-18T14:00:00Z",
          total: 2,
          items: [
            {
              id: 500,
              taskName: "固定分类",
              name: "区域分类图",
              kind: "raster",
              resourceId: 77,
              canRegister: true,
              registered,
            },
            {
              id: 501,
              taskName: "固定分类",
              name: "面积统计表",
              kind: "table",
              resourceId: 78,
              canRegister: false,
              registered: false,
            },
          ],
        },
      ],
    } as never;
  });
  render(
    <App>
      <MemoryRouter>
        <TaskResultCatalogue projectId="2" groupId={groupId} />
      </MemoryRouter>
    </App>,
  );
  const button = await screen.findByRole("button", { name: "登记为正式成果" });
  expect(screen.getByText("环江一次解译任务")).toBeVisible();
  expect(screen.getByText("面积统计表")).toBeVisible();
  fireEvent.click(button);
  const dialog = await screen.findByRole("dialog", {
    name: "确认登记为正式成果",
  });
  expect(registered).toBe(false);
  fireEvent.click(within(dialog).getByRole("button", { name: "正式登记" }));
  await waitFor(() =>
    expect(screen.getByText("正式成果", { exact: true })).toBeVisible(),
  );
  expect(requestJson).toHaveBeenCalledWith(
    "/api/ecology/monitoring/registration/",
    { method: "POST", body: { outputId: 500 } },
  );
});
