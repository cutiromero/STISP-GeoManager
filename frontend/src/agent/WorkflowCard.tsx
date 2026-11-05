import { Alert, Button, Space } from "antd";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import { Link } from "react-router-dom";
import { agentApi } from "../api/agent";
import type { AgentWorkflow } from "../api/generated/types.gen";
import WorkflowResults, { workflowMapResourceIds } from "./WorkflowResults";
import { isMultiElementFamily } from "./multiElementScenario";
import { workflowStatusLabels } from "./workflowFeedback";
import { deletedWorkflowResources } from "./deletedWorkflowResources";
import { record } from "../map/geologyReviewData";

function mergeDetail(
  previous: AgentWorkflow | undefined,
  value: AgentWorkflow,
): AgentWorkflow {
  if (!previous || previous.id !== value.id) return value;
  const sameProposal =
    previous.modificationReview?.proposalHash ===
    value.modificationReview?.proposalHash;
  return {
    ...value,
    steps: [
      ...new Map(
        [...previous.steps, ...value.steps].map((item) => [item.id, item]),
      ).values(),
    ],
    modificationReview: value.modificationReview && {
      ...value.modificationReview,
      suggestions: sameProposal
        ? [
            ...new Map(
              [
                ...(previous.modificationReview?.suggestions ?? []),
                ...value.modificationReview.suggestions,
              ].map((item) => [item.id, item]),
            ).values(),
          ]
        : value.modificationReview.suggestions,
    },
  };
}

export default function WorkflowCard(
  props: ComponentProps<typeof WorkflowResults>,
) {
  const { workflow } = props;
  const [expanded, setExpanded] = useState(workflow.view !== "card");
  const [detail, setDetail] = useState<AgentWorkflow>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const fetched = useRef("");
  const [paging, setPaging] = useState(false);
  const needsApprovalDetail =
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications";
  const needsDetail = expanded || needsApprovalDetail;
  useEffect(() => {
    setExpanded(workflow.view !== "card");
    setDetail(undefined);
  }, [workflow.id]);
  useEffect(() => {
    if (!needsDetail || workflow.view !== "card") return;
    const key = `${workflow.id}:${workflow.updatedAt}:${attempt}`;
    if (fetched.current === key) return;
    const controller = new AbortController();
    setError("");
    void agentApi
      .workflow(workflow.id, {
        signal: controller.signal,
        view: "inspection",
        part: needsApprovalDetail ? "suggestions" : "steps",
      })
      .then(
        (value) => {
          if (!controller.signal.aborted) {
            fetched.current = key;
            setDetail((previous) => mergeDetail(previous, value));
          }
        },
        (reason: unknown) => {
          if (!controller.signal.aborted)
            setError(
              reason instanceof Error ? reason.message : "无法读取工作流明细",
            );
        },
      );
    return () => controller.abort();
  }, [
    needsDetail,
    needsApprovalDetail,
    workflow.id,
    workflow.updatedAt,
    workflow.view,
    attempt,
  ]);
  useEffect(() => {
    if (workflow.view !== "card") {
      fetched.current = `${workflow.id}:${workflow.updatedAt}:${attempt}`;
      setDetail((previous) => mergeDetail(previous, workflow));
    }
  }, [workflow]);
  const loadPage = async (part: "suggestions" | "steps") => {
    if (!detail) return;
    setPaging(true);
    try {
      const value = await agentApi.workflow(workflow.id, {
        view: "inspection",
        part,
        offset:
          part === "suggestions"
            ? (detail.modificationReview?.suggestions.length ?? 0)
            : detail.steps.length,
      });
      if (value.planHash !== detail.planHash)
        throw new Error("方案已更新，请刷新后继续读取");
      setDetail({
        ...value,
        steps: [...detail.steps, ...value.steps],
        modificationReview: value.modificationReview && {
          ...value.modificationReview,
          suggestions: [
            ...(detail.modificationReview?.suggestions ?? []),
            ...value.modificationReview.suggestions,
          ],
        },
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取下一页");
    } finally {
      setPaging(false);
    }
  };
  const displayed =
    (workflow.view === "card" || workflow.view === "inspection") && detail
      ? {
          ...detail,
          status: workflow.status,
          detail: workflow.detail,
          pauseRequested: workflow.pauseRequested,
          planHash: workflow.planHash,
          plan: { ...detail.plan, phase: workflow.plan.phase },
        }
      : workflow;
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
                  ? `/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}`
                  : `/map?resources=${mapIds.join(",")}&projectTagId=${workflow.projectId}`
              }
            >
              {comparison ? "打开独立对比页" : "在地理工作台对比成果图层"}
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
      {workflow.view === "card" &&
        (expanded || needsApprovalDetail) &&
        !detail &&
        !error && <p role="status">正在读取工作流明细…</p>}
      {displayed.id === workflow.id && (
        <WorkflowResults
          key={workflow.id}
          {...props}
          workflow={displayed}
          showMapLink={false}
          detailsExpanded={expanded}
        />
      )}
      {detail?.view === "inspection" && (expanded || needsApprovalDetail) && (
        <Space wrap>
          {detail.modificationReview &&
            detail.modificationReview.suggestions.length <
              Number(
                record(detail.plan.reviewIndex).total ??
                  record(detail.plan.pagination).total ??
                  0,
              ) && (
              <Button
                loading={paging}
                onClick={() => void loadPage("suggestions")}
              >
                读取更多审批对象
              </Button>
            )}
          {expanded && detail.steps.length < (detail.stepCount ?? 0) && (
            <Button loading={paging} onClick={() => void loadPage("steps")}>
              读取更多过程与模型交互
            </Button>
          )}
        </Space>
      )}
    </section>
  );
}
