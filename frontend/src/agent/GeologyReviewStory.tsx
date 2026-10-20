import { Button, Checkbox, Input, Popconfirm, Tag } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { AgentWorkflow } from "../api/generated/types.gen";
import WorkflowKnowledgeReferences from "./WorkflowKnowledgeReferences";
import { deletedWorkflowResources } from "./deletedWorkflowResources";
import "./geology-review-story.css";

type ReviewAction = (
  decision: "approve" | "reject",
  feedback: string,
  selectedSuggestionIds?: string[],
) => void;
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

function previewPaths(geometry: unknown) {
  const shape = record(geometry);
  const polygons =
    shape.type === "Polygon"
      ? [shape.coordinates]
      : shape.type === "MultiPolygon" && Array.isArray(shape.coordinates)
        ? shape.coordinates
        : [];
  const rings = polygons
    .flatMap((polygon) => (Array.isArray(polygon) ? polygon : []))
    .flatMap((ring) => {
      if (!Array.isArray(ring)) return [];
      const points = ring.filter(
        (point): point is [number, number] =>
          Array.isArray(point) &&
          point.length >= 2 &&
          Number.isFinite(point[0]) &&
          Number.isFinite(point[1]),
      );
      return points.length >= 3 ? [points] : [];
    });
  const points = rings.flat();
  if (!points.length) return "";
  const west = Math.min(...points.map((point) => point[0]));
  const south = Math.min(...points.map((point) => point[1]));
  const east = Math.max(...points.map((point) => point[0]));
  const north = Math.max(...points.map((point) => point[1]));
  const scale = Math.min(
    208 / Math.max(east - west, 1e-9),
    118 / Math.max(north - south, 1e-9),
  );
  return rings
    .map(
      (ring) =>
        ring
          .map(
            ([x, y], index) =>
              `${index ? "L" : "M"}${120 + (x - (east + west) / 2) * scale},${75 - (y - (north + south) / 2) * scale}`,
          )
          .join(" ") + " Z",
    )
    .join(" ");
}

function storyEvents(workflow: AgentWorkflow) {
  const steps = workflow.steps;
  const review = workflow.modificationReview;
  const decisions = steps.flatMap((step) =>
    step.decision ? [step.decision] : [],
  );
  const knowledge = steps.find(
    (step) =>
      step.kind === "search_expert_knowledge" && step.status === "succeeded",
  );
  const check = decisions.find(
    (decision) => decision.nextAction === "geology-map-check",
  );
  const plan = [...decisions]
    .reverse()
    .find((decision) => decision.nextAction === "geology-map-correct");
  const findings = plan?.findings ?? [];
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages.map(record)
    : [];
  const editStage = stages.find((stage) => stage.name === "edit");
  const edit = editStage?.taskId
    ? steps.find((step) => step.computeTaskId === editStage.taskId)
    : undefined;
  const final = [...decisions]
    .reverse()
    .find((decision) => decision.nextAction === "finish");
  const events: { key: string; title: string; description: string }[] = [];
  if (check)
    events.push({
      key: "checking",
      title: "正在检查地图",
      description: check.algorithmReason || check.problem,
    });
  if (findings.length)
    events.push({
      key: "findings",
      title: review?.suggestions.length === 1 ? "发现一处疑点" : "发现的问题",
      description: findings[0]!,
    });
  if (knowledge)
    events.push({
      key: "knowledge",
      title: "查到相关专家知识",
      description: knowledge.message,
    });
  if (review?.suggestions.length)
    events.push({
      key: "proposal",
      title: "形成修正建议",
      description:
        plan?.judgement ||
        `本次形成 ${review.suggestions.length} 条建议，位置、依据和范围见下方。`,
    });
  if (
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications"
  )
    events.push({
      key: "approval",
      title: "等待用户批准",
      description: "选择允许修改的建议，确认后才执行相应操作。",
    });
  if (review?.approvedSuggestionIds.length && edit)
    events.push({
      key: "editing",
      title: edit.status === "succeeded" ? "已修正地图" : "正在修正地图",
      description: plan?.algorithmReason || edit.message,
    });
  if (workflow.status === "succeeded" && final)
    events.push({
      key: "done",
      title: "复核完成",
      description: final.resultSummary || final.judgement,
    });
  return events;
}

export default function GeologyReviewStory({
  workflow,
  busy = false,
  onReview,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onReview?: ReviewAction;
}) {
  const review = workflow.modificationReview;
  const [selection, setSelection] = useState<{ hash: string; ids: string[] }>({
    hash: review?.proposalHash ?? "",
    ids: review?.approvedSuggestionIds ?? [],
  });
  const [feedback, setFeedback] = useState("");
  const editable =
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications" &&
    Boolean(onReview);
  const suggestions = review?.suggestions ?? [];
  const selected =
    selection.hash === review?.proposalHash
      ? selection.ids.filter((id) =>
          suggestions.some((suggestion) => suggestion.id === id),
        )
      : [];
  const approved = review?.approvedSuggestionIds ?? [];
  const events = storyEvents(workflow);
  const mapId = Number(record(workflow.plan.inputs).initial_map);
  const deletedIds = new Set(
    deletedWorkflowResources(workflow).map((item) => item.id),
  );
  const select = (ids: string[]) =>
    setSelection({ hash: review?.proposalHash ?? "", ids });
  return (
    <section className="geology-review-story" aria-label="地质成果检查与修正">
      <div className="geology-story-heading">
        <strong>地质成果智能检查与修正</strong>
        <Tag color="blue">演示案例</Tag>
      </div>
      {events.length > 0 && (
        <div className="geology-story-current">
          <strong>{events[events.length - 1]!.title}</strong>
          <p>{events[events.length - 1]!.description}</p>
        </div>
      )}
      {events.length > 1 && (
        <details className="geology-story-history">
          <summary>查看检查经过 / {events.length - 1} 个阶段</summary>
          <ol className="geology-story-events">
            {events.slice(0, -1).map((event) => (
              <li key={event.key}>
                <strong>{event.title}</strong>
                <p>{event.description}</p>
              </li>
            ))}
          </ol>
        </details>
      )}
      {suggestions.length > 0 && (
        <section className="geology-suggestions" aria-label="建议修改">
          <div className="geology-suggestions-heading">
            <h3>建议修改 / {suggestions.length} 条</h3>
            {editable && (
              <Checkbox
                disabled={busy}
                checked={selected.length === suggestions.length}
                indeterminate={
                  selected.length > 0 && selected.length < suggestions.length
                }
                onChange={(event) =>
                  select(
                    event.target.checked
                      ? suggestions.map((suggestion) => suggestion.id)
                      : [],
                  )
                }
              >
                选择全部建议
              </Checkbox>
            )}
          </div>
          {suggestions.map((suggestion) => {
            const evidence = workflow.evidence.filter((entry) =>
              suggestion.knowledgeRefs.some(
                (ref) =>
                  String(entry.id) === String(ref.id) &&
                  Number(entry.revision) === ref.revision,
              ),
            );
            const path = previewPaths(suggestion.preview);
            return (
              <article key={suggestion.id} className="geology-suggestion">
                <div className="geology-suggestion-content">
                  <div className="geology-suggestion-title">
                    {editable ? (
                      <Checkbox
                        checked={selected.includes(suggestion.id)}
                        disabled={busy}
                        onChange={(event) =>
                          select(
                            event.target.checked
                              ? [...selected, suggestion.id]
                              : selected.filter((id) => id !== suggestion.id),
                          )
                        }
                      >
                        {suggestion.title}
                      </Checkbox>
                    ) : (
                      <strong>{suggestion.title}</strong>
                    )}
                    {!editable && approved.length > 0 && (
                      <Tag
                        color={
                          approved.includes(suggestion.id) ? "blue" : "default"
                        }
                      >
                        {approved.includes(suggestion.id) ? "已批准" : "未批准"}
                      </Tag>
                    )}
                  </div>
                  <dl className="geology-suggestion-states">
                    <div>
                      <dt>当前状态</dt>
                      <dd>{suggestion.currentState}</dd>
                    </div>
                    <div>
                      <dt>建议状态</dt>
                      <dd>{suggestion.suggestedState}</dd>
                    </div>
                  </dl>
                  <p className="geology-suggestion-reason">
                    <strong>修改依据</strong>
                    {suggestion.reason}
                  </p>
                  <small className="geology-suggestion-scope">
                    修改范围：
                    {suggestion.kind === "fill_gap"
                      ? "内部未分类空白"
                      : "地层时代属性"}{" "}
                    /{" "}
                    {suggestion.areaM2.toLocaleString("zh-CN", {
                      maximumFractionDigits: 2,
                    })}{" "}
                    平方米
                  </small>
                  <details className="geology-suggestion-evidence">
                    <summary>
                      专家知识 /{" "}
                      {suggestion.knowledgeRefs
                        .map((entry) => entry.title)
                        .join("、")}
                    </summary>
                    {evidence.length ? (
                      <WorkflowKnowledgeReferences items={evidence} />
                    ) : (
                      <p>本次知识引用已记录；来源详见专家知识库。</p>
                    )}
                  </details>
                </div>
                <div className="geology-suggestion-preview">
                  {path ? (
                    <svg
                      viewBox="0 0 240 150"
                      role="img"
                      aria-label={`${suggestion.title}的修改范围`}
                    >
                      <path d={path} fillRule="evenodd" />
                    </svg>
                  ) : (
                    <span>暂无范围预览</span>
                  )}
                  <small>修改范围示意</small>
                  {mapId > 0 && !deletedIds.has(mapId) && (
                    <Link
                      to={`/map?resourceId=${mapId}&projectTagId=${workflow.projectId}&geologyReview=${encodeURIComponent(workflow.id)}&suggestion=${encodeURIComponent(suggestion.id)}`}
                    >
                      在地图上查看位置
                    </Link>
                  )}
                </div>
              </article>
            );
          })}
          {editable && (
            <div className="geology-review-controls" aria-label="修改建议审核">
              <Input.TextArea
                aria-label="修改建议审核意见"
                placeholder="可补充审核意见或需要继续核实的内容"
                value={feedback}
                maxLength={4000}
                autoSize={{ minRows: 2, maxRows: 4 }}
                disabled={busy}
                onChange={(event) => setFeedback(event.target.value)}
              />
              <p>
                已选择 {selected.length}{" "}
                条建议。仅修改您批准的范围，待检查地质图保持可查看。
              </p>
              <div className="geology-review-buttons">
                <Popconfirm
                  title="批准选中的建议并修正？"
                  description={`将保存批准记录，执行您选中的 ${selected.length} 条建议。`}
                  okText="批准并修正"
                  cancelText="返回核对"
                  onConfirm={() =>
                    onReview?.("approve", feedback.trim(), selected)
                  }
                >
                  <Button
                    type="primary"
                    loading={busy}
                    disabled={!selected.length}
                  >
                    批准选中的建议并修正
                  </Button>
                </Popconfirm>
                <Popconfirm
                  title="拒绝本次修改建议？"
                  description="保留检查记录和建议，停止修改地图。"
                  okText="确认拒绝"
                  cancelText="返回核对"
                  onConfirm={() =>
                    onReview?.("reject", feedback.trim() || "拒绝本次修改建议")
                  }
                >
                  <Button disabled={busy}>拒绝建议</Button>
                </Popconfirm>
              </div>
            </div>
          )}
        </section>
      )}
      {workflow.status === "succeeded" && !deletedIds.size && (
        <Link
          className="geology-review-map-link"
          to={`/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}`}
        >
          查看待检查地质图与修正后地质图
        </Link>
      )}
    </section>
  );
}
