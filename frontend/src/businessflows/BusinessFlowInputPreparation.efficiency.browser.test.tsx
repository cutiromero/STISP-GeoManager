import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import type { BusinessFlowInputScriptDetail } from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import { businessFlowRun } from "./businessFlow.testFixtures";
import BusinessFlowInputPreparation from "./BusinessFlowInputPreparation";

const code = "def run(context):\n    pass\n";
const detail: BusinessFlowInputScriptDetail = {
  role: "source",
  attempt: 1,
  language: "python",
  code,
  sha256: "a".repeat(64),
  status: "ready",
  summary: "按实际字段生成工作副本",
  diagnostics: [],
  sourceIds: [81],
  targetType: "table",
};
function flow() {
  return businessFlowRun({
    inputPreparation: {
      ready: false,
      items: [
        {
          role: "source",
          sourceId: 81,
          sourceName: "区域观测资料",
          sourceType: "gene",
          sourceRevision: "2026-11-10T00:00:00Z",
          targetTypes: ["table"],
          targetSemantics: "",
          status: "waiting_compute",
          script: {
            attempt: 1,
            status: "running",
            sha256: "a".repeat(64),
            summary: detail.summary,
            available: true,
          },
        },
      ],
    },
  });
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(businessFlowsApi, "inputScript").mockResolvedValue(detail);
});
it("does not fetch or transmit source code until the user opens the viewer", async () => {
  const value = flow();
  const blocked = vi.fn();
  const view = render(
    <App>
      <BusinessFlowInputPreparation
        flow={value}
        onChanged={vi.fn()}
        onAccessBlocked={blocked}
      />
    </App>,
  );
  expect(businessFlowsApi.inputScript).not.toHaveBeenCalled();
  expect(screen.queryByText(code)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看适配脚本" }));
  await waitFor(() =>
    expect(screen.getByRole("dialog").querySelector("pre")?.textContent).toBe(
      code,
    ),
  );
  expect(businessFlowsApi.inputScript).toHaveBeenCalledOnce();
  view.rerender(
    <App>
      <BusinessFlowInputPreparation
        flow={{ ...value, revision: value.revision + 1 }}
        onChanged={vi.fn()}
        onAccessBlocked={blocked}
      />
    </App>,
  );
  expect(businessFlowsApi.inputScript).toHaveBeenCalledOnce();
});
it("clears a late script when a different run is shown", async () => {
  let resolve!: (value: BusinessFlowInputScriptDetail) => void;
  vi.mocked(businessFlowsApi.inputScript).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const value = flow(),
    blocked = vi.fn();
  const view = render(
    <App>
      <BusinessFlowInputPreparation
        flow={value}
        onChanged={vi.fn()}
        onAccessBlocked={blocked}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "查看适配脚本" }));
  await waitFor(() =>
    expect(businessFlowsApi.inputScript).toHaveBeenCalledOnce(),
  );
  view.rerender(
    <App>
      <BusinessFlowInputPreparation
        flow={{ ...value, id: "another-run" }}
        onChanged={vi.fn()}
        onAccessBlocked={blocked}
      />
    </App>,
  );
  resolve(detail);
  await waitFor(() => expect(screen.queryByText(code)).not.toBeInTheDocument());
});
it("hides code and notifies the parent on explicit access revocation", async () => {
  vi.mocked(businessFlowsApi.inputScript).mockRejectedValue(
    new ApiError("资料已撤权", 403),
  );
  const blocked = vi.fn();
  render(
    <App>
      <BusinessFlowInputPreparation
        flow={flow()}
        onChanged={vi.fn()}
        onAccessBlocked={blocked}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "查看适配脚本" }));
  await waitFor(() => expect(blocked).toHaveBeenCalledOnce());
  expect(screen.queryByText(code)).not.toBeInTheDocument();
});
