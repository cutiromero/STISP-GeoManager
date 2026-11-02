import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { agentApi } from "../api/agent";
import { computeApi } from "../api/compute";
import DemoWorkflowForm from "./DemoWorkflowForm";
import WorkflowPanel from "./WorkflowPanel";
import { geologyRequiredFields } from "./geologyWorkflowInputs";
import "./agent.css";

beforeEach(() => vi.restoreAllMocks());

it.each([360, 720])(
  "keeps long resource names inside workflow fields at %s px",
  (width) => {
    const roles = ["initial_map", "coverage", "rules"];
    const candidates = roles.map((role, index) => ({
      id: 201 + index,
      name: `研究区地质解译资料${"完整资源名称".repeat(20)}_${role}`,
      kind: role === "rules" ? "table" : "vector",
      projectTagId: 1,
      fields: geologyRequiredFields[role]!,
      bands: 0,
      crs: "EPSG:32646",
      geometryTypes: role === "rules" ? [] : ["Polygon"],
      sizeBytes: 100,
    }));
    const { container } = render(
      <App>
        <div className="agent-workflow-content" style={{ width }}>
          <DemoWorkflowForm
            type="geology_map_review"
            candidates={candidates}
            resources={candidates.map((item) => ({
              id: item.id,
              name: item.name,
              dataType: item.kind,
              description: "本次资料",
            }))}
            inputs={{ initial_map: 201, coverage: 202, rules: 203 }}
            parameters={{}}
            disabled={false}
            onInputsChange={vi.fn()}
            onParametersChange={vi.fn()}
          />
        </div>
      </App>,
    );
    const form = container.querySelector<HTMLElement>(".agent-demo-form")!;
    const labels = Array.from(
      container.querySelectorAll<HTMLElement>(".agent-demo-fields > label"),
    );
    expect(form.scrollWidth).toBeLessThanOrEqual(form.clientWidth);
    for (const label of labels) {
      const select = label.querySelector<HTMLElement>(".ant-select")!;
      expect(select.getBoundingClientRect().right).toBeLessThanOrEqual(
        label.getBoundingClientRect().right + 1,
      );
    }
    if (width === 360) {
      expect(labels[1]!.getBoundingClientRect().top).toBeGreaterThan(
        labels[0]!.getBoundingClientRect().bottom,
      );
    } else {
      expect(labels[1]!.getBoundingClientRect().top).toBe(
        labels[0]!.getBoundingClientRect().top,
      );
    }
  },
);

it("shows the database resource name in the selector and the selected source explanation", async () => {
  const onInputs = vi.fn();
  render(
    <App>
      <DemoWorkflowForm
        type="geology_map_review"
        candidates={[
          {
            id: 101,
            kind: "vector",
            name: "旧候选别名",
            projectTagId: 3,
            fields: geologyRequiredFields.initial_map!,
            bands: 0,
            crs: "EPSG:32645",
            geometryTypes: ["Polygon"],
            sizeBytes: 100,
          },
        ]}
        resources={[
          {
            id: 101,
            name: "数据库中的待检查图",
            dataType: "vector",
            description: "来源说明",
          },
        ]}
        inputs={{ initial_map: 101 }}
        parameters={{}}
        disabled={false}
        onInputsChange={onInputs}
        onParametersChange={vi.fn()}
      />
    </App>,
  );
  expect(screen.queryByText("旧候选别名")).not.toBeInTheDocument();
  expect(screen.getByText("待检查地质图 / 数据库中的待检查图")).toBeVisible();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "待检查地质图" }));
  await screen.findByText("数据库中的待检查图", {
    selector: ".ant-select-item-option-content",
  });
  expect(onInputs).not.toHaveBeenCalled();
});

it("uses the current conversation model without a separate workflow model selector", async () => {
  vi.spyOn(agentApi, "bootstrap").mockResolvedValue({
    knowledgeDomains: [],
  } as never);
  vi.spyOn(agentApi, "researchDemos").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "resources").mockResolvedValue({ items: [] });
  vi.spyOn(agentApi, "workflows").mockResolvedValue({ items: [] });
  vi.spyOn(computeApi, "algorithms").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(computeApi, "inputs").mockResolvedValue({ items: [], total: 0 });
  const preview = vi
    .spyOn(agentApi, "createWorkflow")
    .mockRejectedValue(new Error("预览验证结束"));
  render(
    <App>
      <MemoryRouter>
        <WorkflowPanel
          model="configured-conversation-model"
          resourceIds={[]}
          embedded
        />
      </MemoryRouter>
    </App>,
  );
  expect(
    screen.queryByRole("combobox", { name: "工作流分析模型" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "工作流目标" }), {
    target: { value: "统计项目数据" },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "生成执行计划" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "生成执行计划" }));
  await waitFor(() =>
    expect(preview).toHaveBeenCalledWith(
      expect.objectContaining({
        model: "configured-conversation-model",
        goal: "统计项目数据",
        executeOperators: false,
      }),
    ),
  );
  await screen.findByText("预览验证结束");
});
