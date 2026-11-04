import { Alert, Button, Space } from "antd";
import { useEffect, useState, type ComponentProps } from "react";
import { Link } from "react-router-dom";
import { agentApi } from "../api/agent";
import type { AgentWorkflow } from "../api/generated/types.gen";
import WorkflowResults, { workflowMapResourceIds } from "./WorkflowResults";
import { isMultiElementFamily } from "./multiElementScenario";
import { workflowStatusLabels } from "./workflowFeedback";
import { deletedWorkflowResources } from "./deletedWorkflowResources";

export default function WorkflowCard(
  props: ComponentProps<typeof WorkflowResults>,
) {
  const { workflow } = props;
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<AgentWorkflow>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setExpanded(false);
    setDetail(undefined);
  }, [workflow.id]);
  useEffect(() => {
    if (!expanded || workflow.view !== "card") return;
    const controller = new AbortController();
    setDetail(undefined);
    setError("");
    void agentApi.workflow(workflow.id, { signal: controller.signal }).then(
      (value) => {
        if (!controller.signal.aborted) setDetail(value);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "无法读取工作流明细",
          );
      },
    );
    return () => controller.abort();
  }, [expanded, workflow.id, workflow.updatedAt, workflow.view, attempt]);
  if (workflow.view !== "card") return <WorkflowResults {...props} />;
  const deleted = new Set(
    deletedWorkflowResources(workflow).map((item) => item.id),
  );
  const results = workflow.resultResourceIds.filter((id) => !deleted.has(id));
  const mapIds = workflowMapResourceIds(workflow);
  const comparison =
    isMultiElementFamily(workflow.workflowType) ||
    workflow.workflowType === "geology_map_review";
  return (
    <section className="agent-workflow-results" aria-label="工作流进度卡片">
      <p>
        <strong>{workflowStatusLabels[workflow.status]}</strong> ·{" "}
        {workflow.detail}
      </p>
      {Boolean(results.length) && (
        <p>
          已保存 {results.length} 项成果。{" "}
          {!deleted.size && mapIds.length > 0 && (
            <Link
              target="_blank"
              rel="noopener"
              to={
                comparison
                  ? `/map?geologyCompare=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}`
                  : `/map?resources=${mapIds.join(",")}&projectTagId=${workflow.projectId}`
              }
            >
              在地理工作台对比成果图层
            </Link>
          )}
        </p>
      )}
      <Space wrap>
        <Button onClick={() => setExpanded((value) => !value)}>
          {expanded
            ? "收起明细"
            : `查看过程、证据与模型交互 / ${workflow.stepCount ?? 0} 步`}
        </Button>
        {error && (
          <Button onClick={() => setAttempt((value) => value + 1)}>
            重试读取明细
          </Button>
        )}
      </Space>
      {error && <Alert type="error" title={error} />}
      {expanded && !detail && !error && (
        <p role="status">正在读取工作流明细…</p>
      )}
      {expanded && detail && detail.id === workflow.id && (
        <WorkflowResults {...props} workflow={detail} />
      )}
    </section>
  );
}
