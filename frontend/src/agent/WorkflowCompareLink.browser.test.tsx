import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { reviewWorkflow } from "../map/geologyReview.testFixtures";
import WorkflowCard from "./WorkflowCard";

vi.mock("./WorkflowReportFile", () => ({ default: () => null }));

it("keeps exactly one comparison link through expand, collapse and reopen without unmounting details", async () => {
  const detail = { ...reviewWorkflow(true), status: "succeeded" as const };
  const load = vi.spyOn(agentApi, "workflow").mockResolvedValue(detail);
  try {
    const { container } = render(
      <App>
        <MemoryRouter>
          <WorkflowCard
            workflow={{ ...detail, view: "card", steps: [], evidence: [] }}
          />
        </MemoryRouter>
      </App>,
    );
    const check = () => {
      expect(
        screen.getByRole("link", { name: "打开独立对比页" }),
      ).toHaveAttribute(
        "href",
        `/map?geologyReview=${detail.id}&projectTagId=${detail.projectId}`,
      );
      expect(
        screen.getAllByRole("link", { name: "打开独立对比页" }),
      ).toHaveLength(1);
      expect(
        Array.from(container.querySelectorAll("a")).filter(
          (link) => link.textContent === "打开独立对比页",
        ),
      ).toHaveLength(1);
    };
    check();
    fireEvent.click(
      screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
    );
    await waitFor(() => expect(container.querySelector("[inert]")).toBeNull());
    await waitFor(() => expect(load).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(container.querySelectorAll(".agent-workflow-status")).toHaveLength(
        1,
      ),
    );
    check();
    const nested = container.querySelector(".agent-workflow-status")!;
    fireEvent.click(screen.getByRole("button", { name: "收起明细" }));
    expect(nested).toBeVisible();
    expect(nested.querySelector("[hidden][inert]")).not.toBeNull();
    check();
    fireEvent.click(
      screen.getByRole("button", { name: /查看过程、证据与模型交互/ }),
    );
    expect(nested).toBeVisible();
    expect(container.querySelector(".agent-workflow-status")).toBe(nested);
    check();
  } finally {
    load.mockRestore();
  }
});
