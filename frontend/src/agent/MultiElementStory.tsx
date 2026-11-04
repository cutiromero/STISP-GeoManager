import { Button, Checkbox, Input, Popconfirm, Select, Tag } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import type {
  AgentModificationSuggestion,
  AgentWorkflow,
} from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";
import { genericRoles } from "./GenericWorkflowUploads";
import {
  genericGeologyType,
  multiElementSegments,
} from "./multiElementScenario";
import "./geology-review-story.css";
import { formatArea } from "../utils/area";

const elements: Record<string, string> = {
  lithology: "岩性",
  structure: "构造",
  alteration: "蚀变",
};
const actions: Record<string, string> = {
  fix_symbol: "校正名称代号",
  set_symbol: "校正名称代号",
  set_code: "校正地质代号",
  reclassify: "重分类",
  merge: "融合图斑",
  remove: "剔除",
  exclude: "本次暂不参与",
  delete: "剔除",
  downweight: "降权",
  retain: "保留",
  keep: "保留",
  review: "待裁定",
};
// Rules whose finding is a fact check: these could run without review once the
// rule is published; while rules are trial drafts every action still needs approval.
const deterministicRules = new Set(["L-03", "L-05", "A-05"]);

/** Which disposal tier a suggestion belongs to. */
export function suggestionTier(item: { status?: string; ruleId?: string }) {
  if (item.status === "exception") return "规则例外候选";
  if (item.status === "review") return "需地质判断，暂保留";
  if (deterministicRules.has(item.ruleId ?? ""))
    return "确定性问题（规则发布后可自动处理）";
  return "建议处置，批准后执行";
}

const observationLabels: Record<string, string> = {
  area_km2: "面积（平方公里）",
  area_m2: "面积（平方米）",
  length_m: "长度（米）",
  boundary_ratio: "沿界比例",
  dominant_ratio: "主体岩性占比",
  conf: "模拟分类置信度",
  confidence: "模拟分类置信度",
  shared_ratio: "共享边界比例",
  distance_m: "距离（米）",
  fault_distance_m: "距构造（米）",
  sinuosity: "弯曲度",
  reversal_count: "折返次数",
  name: "图例名称",
  observed_code: "当前代号",
  expected_code: "图例对应代号",
  shared_boundary_ratio: "同一围岩共享边界比例",
  host_code: "围岩代号",
  simulation_confidence: "模拟分类置信度",
  classification_confidence_kind: "置信度性质",
  host_feature_ids: "实测相邻对象",
  age_ma: "当前单元近似时代（百万年）",
  host_age_ma: "围岩近似时代（百万年）",
  cover_ratio: "松散覆盖层内长度占比",
  endpoints_in_cover: "两端是否在覆盖层内",
  neighbour_count: "邻近构造数量",
  turn_count: "急折返次数",
  dominant_code: "主要重叠地质单元",
  group_areas_m2: "各类岩石重叠面积",
  group_ratios: "各类岩石重叠占比",
  mineral: "识别矿物",
  unit_areas_m2: "各地质单元重叠面积",
};
const observationValues: Record<string, string> = {
  carbonate: "碳酸盐岩",
  carbonate_interbed: "含碳酸盐夹层",
  red_clastic: "红色碎屑岩",
  loose: "松散覆盖层",
  intrusive: "侵入岩",
  volcanic: "火山岩",
  clastic: "碎屑岩",
  metamorphic: "变质岩",
  unknown: "未分类岩性",
  simulated: "模拟分类信息",
};

export function formatMultiElementObservation(
  value: unknown,
  key = "",
  withUnit = false,
): string {
  if (value === null || value === undefined) return "未提供";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") {
    if (key.includes("ratio") || key.includes("confidence") || key === "conf")
      return `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
    if (withUnit && key.endsWith("_m2")) return formatArea(value);
    const unit = !withUnit ? "" : key.endsWith("_m") ? " 米" : "";
    return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 3 })}${unit}`;
  }
  if (typeof value === "string") {
    if (value.startsWith("{") || value.startsWith("[")) {
      try {
        return formatMultiElementObservation(JSON.parse(value), key, withUnit);
      } catch {
        /* retain non-JSON source text */
      }
    }
    return observationValues[value] ?? value;
  }
  if (Array.isArray(value))
    return value
      .map((item) => formatMultiElementObservation(item, key))
      .join("、");
  return Object.entries(record(value))
    .map(
      ([name, item]) =>
        `${observationLabels[name] ?? observationValues[name] ?? name}：${formatMultiElementObservation(item, key.endsWith("_m2") || key === "group_ratios" ? key : name, true)}`,
    )
    .join("；");
}

export function MultiElementEvidence({
  suggestion,
}: {
  suggestion: AgentModificationSuggestion;
}) {
  return (
    <div className="multi-element-evidence">
      <strong>实际观测和测量值</strong>
      <dl>
        {Object.entries(suggestion.observations ?? {}).map(([key, value]) => (
          <div key={key}>
            <dt>{observationLabels[key] ?? key}</dt>
            <dd>{formatMultiElementObservation(value, key)}</dd>
          </div>
        ))}
      </dl>
      <strong>命中的知识与规则</strong>
      {(suggestion.ruleRefs ?? []).map((ref) => (
        <div className="multi-element-rule" key={`${ref.id}:${ref.version}`}>
          <Tag color="blue">本案例试用</Tag>
          <b>
            {ref.id} / {ref.title}
          </b>
          <small>
            规则版本 {ref.version} / 知识修订 {ref.revision}
          </small>
          <p>{ref.source}</p>
        </div>
      ))}
      {!!suggestion.ruleConditions?.length && (
        <>
          <strong>适用条件</strong>
          <ul>
            {suggestion.ruleConditions.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </>
      )}
      {!!suggestion.exceptions?.length && (
        <>
          <strong>例外与待核实资料</strong>
          <ul>
            {suggestion.exceptions.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </>
      )}
      <strong>为什么这样建议</strong>
      <p>{suggestion.reason}</p>
    </div>
  );
}

export default function MultiElementStory({
  workflow,
  busy = false,
  onReview,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onReview?: (
    decision: "approve" | "reject",
    feedback: string,
    selectedSuggestionIds?: string[],
  ) => void;
}) {
  const review = workflow.modificationReview;
  const [selection, setSelection] = useState<{ hash: string; ids: string[] }>({
    hash: review?.proposalHash ?? "",
    ids: review?.approvedSuggestionIds ?? [],
  });
  const [filter, setFilter] = useState("all");
  const [feedback, setFeedback] = useState("");
  const suggestions = review?.suggestions ?? [];
  const ids =
    selection.hash === review?.proposalHash
      ? selection.ids.filter((id) => suggestions.some((item) => item.id === id))
      : [];
  const approved = review?.approvedSuggestionIds ?? [];
  const editable =
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications" &&
    Boolean(onReview);
  const selectable = suggestions.filter(
    (item) =>
      !["exception", "review", "retained", "pending"].includes(
        item.status ?? "",
      ),
  );
  const visible = suggestions.filter(
    (item) => filter === "all" || item.element === filter,
  );
  const update = (values: string[]) =>
    setSelection({ hash: review?.proposalHash ?? "", ids: values });
  const decisions = workflow.steps.flatMap((step) =>
    step.decision ? [step.decision] : [],
  );
  const latest = decisions[decisions.length - 1];
  const stages = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
  ).map(record);
  const algorithms = record(workflow.plan.algorithms);
  const editValidation = record(
    stages.find((stage) => stage.name === "apply")?.editValidation,
  );
  const discardedReasons = Array.isArray(editValidation.errors)
    ? [
        ...new Set(
          editValidation.errors.map((item) => String(record(item).reason)),
        ),
      ].join("；")
    : "";
  const segment = String(workflow.parameters.segment ?? "all");
  const inputNames = record(workflow.plan.inputNames);
  const upstream = Object.entries(record(workflow.plan.upstreamVersions));
  const generic = workflow.workflowType === genericGeologyType;
  const missing = (
    Array.isArray(workflow.plan.missingRoles) ? workflow.plan.missingRoles : []
  ).map(
    (role) =>
      genericRoles.find((item) => item.key === role)?.label ?? String(role),
  );
  const title = generic ? "地质综合推理" : "海德乌拉地质综合推理";
  const latestText =
    latest && (latest.resultSummary || latest.judgement || latest.problem);
  return (
    <section
      className="geology-review-story multi-element-story"
      aria-label={generic ? title : "海德乌拉综合推理"}
    >
      <div className="geology-story-heading">
        <strong>{title}</strong>
        <Tag color="blue">{generic ? "本次资料" : "演示案例"}</Tag>
        <Tag>
          {multiElementSegments.find((item) => item.value === segment)?.label}
        </Tag>
      </div>
      <p className="agent-demo-hint">
        {generic
          ? `资料由您为本次任务提供，字段含义已经您确认。${
              missing.length
                ? `未提供：${missing.join("、")}，按计划中的说明处理。`
                : ""
            }A/B表示优先核查证据组合等级。`
          : "岩性与构造为模拟识别输入（演示）；矿物为遥感矿物识别结果（演示案例）。模拟置信度用于演示证据分级。A/B表示优先核查证据组合等级。"}
      </p>
      <div className="geology-story-current">
        <strong>{workflow.detail}</strong>
        {latestText && latestText !== workflow.detail && <p>{latestText}</p>}
      </div>
      <details className="geology-story-history">
        <summary>本次上游版本、试用知识与真实工具</summary>
        <div className="multi-element-evidence">
          <strong>实际采用的上游资料</strong>
          <ul>
            {upstream.map(([role, value]) => (
              <li key={role}>
                {String(inputNames[role] ?? role)} / 版本{" "}
                {String(record(value).revision ?? "已冻结")}
              </li>
            ))}
          </ul>
          <strong>{generic ? "试用知识" : "本案例试用知识"}</strong>
          <ul>
            {workflow.plan.trialRuleBindings?.map((rule) => (
              <li key={`${rule.id}:${rule.revision}`}>
                {rule.ruleId} / {rule.title} / 版本 {rule.ruleVersion} / 修订{" "}
                {rule.revision}
              </li>
            ))}
          </ul>
          <strong>本次真实算法</strong>
          <ul>
            {stages.map((stage) => {
              const algorithm = record(algorithms[String(stage.identifier)]);
              const version = record(algorithm.manifest).version;
              return (
                <li key={String(stage.name)}>
                  {String(algorithm.name ?? stage.identifier)}{" "}
                  {String(version ?? "")} /{" "}
                  {stage.taskId
                    ? stage.status === "succeeded" ||
                      stage.status === "completed"
                      ? "已实际执行"
                      : "已提交计算"
                    : stage.status === "skipped"
                      ? "本轮无需执行"
                      : "尚未执行"}
                </li>
              );
            })}
          </ul>
        </div>
      </details>
      {suggestions.length > 0 && (
        <section className="geology-suggestions" aria-label="多要素检查建议">
          {Number(editValidation.discardedCount) > 0 && (
            <p role="status">
              模型另提出 {Number(editValidation.discardedCount)} 项建议因
              {discardedReasons}未采用；其余建议仍需逐项人工确认。
            </p>
          )}
          <div className="geology-suggestions-heading">
            <h3>发现的问题与建议 / {suggestions.length} 项</h3>
            <Select
              aria-label="按要素筛选建议"
              size="small"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "全部要素" },
                ...Object.entries(elements).map(([value, label]) => ({
                  value,
                  label,
                })),
              ]}
            />
          </div>
          {editable && (
            <Checkbox
              checked={ids.length > 0 && ids.length === selectable.length}
              indeterminate={ids.length > 0 && ids.length < selectable.length}
              disabled={busy}
              onChange={(event) =>
                update(
                  event.target.checked ? selectable.map((item) => item.id) : [],
                )
              }
            >
              选择全部可执行建议（待裁定和例外保留）
            </Checkbox>
          )}
          <div className="multi-element-suggestion-list">
            {visible.map((item) => (
              <details className="multi-element-suggestion" key={item.id}>
                <summary>
                  <span>
                    {elements[item.element ?? ""] ?? "检查"} / {item.title}
                  </span>
                  <Tag color={approved.includes(item.id) ? "blue" : undefined}>
                    {approved.includes(item.id)
                      ? "已批准"
                      : item.status === "review"
                        ? "待裁定"
                        : item.status === "exception"
                          ? "例外候选"
                          : (actions[item.action ?? ""] ?? item.suggestedState)}
                  </Tag>
                </summary>
                <div className="multi-element-suggestion-body">
                  <p className="multi-element-suggestion-tier">
                    处置分级：{suggestionTier(item)}
                  </p>
                  {editable &&
                    selectable.some((value) => value.id === item.id) && (
                      <Checkbox
                        disabled={busy}
                        checked={ids.includes(item.id)}
                        onChange={(event) =>
                          update(
                            event.target.checked
                              ? [...ids, item.id]
                              : ids.filter((id) => id !== item.id),
                          )
                        }
                      >
                        批准此对象的「
                        {actions[item.action ?? ""] ?? item.suggestedState}
                        」操作
                      </Checkbox>
                    )}
                  <dl className="geology-suggestion-states">
                    <div>
                      <dt>当前状态</dt>
                      <dd>{item.currentState}</dd>
                    </div>
                    <div>
                      <dt>建议状态</dt>
                      <dd>
                        {actions[item.action ?? ""] ?? item.suggestedState}
                      </dd>
                    </div>
                  </dl>
                  <p>
                    {item.element === "structure" && item.lengthM !== undefined
                      ? `涉及长度 ${item.lengthM.toLocaleString("zh-CN")} 米`
                      : `涉及面积 ${formatArea(item.areaM2)}`}
                  </p>
                  <MultiElementEvidence suggestion={item} />
                  <Link
                    target="_blank"
                    rel="noopener"
                    to={`/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}&suggestion=${encodeURIComponent(item.id)}`}
                  >
                    在地图上定位此对象
                  </Link>
                </div>
              </details>
            ))}
          </div>
          {editable && (
            <div className="geology-review-controls">
              <Input.TextArea
                aria-label="综合推理审核意见"
                placeholder="可补充核对意见；未选对象保持不变"
                value={feedback}
                onChange={(event) => setFeedback(event.target.value)}
                disabled={busy}
                maxLength={4000}
                autoSize={{ minRows: 2, maxRows: 4 }}
              />
              <p>
                已选择 {ids.length}{" "}
                项。后端将重验输入版本、建议和获批范围；降权不删除原始识别层。
              </p>
              <div className="geology-review-buttons">
                <Popconfirm
                  title={`批准选中的 ${ids.length} 项操作？`}
                  description="仅执行当前方案所选对象与动作，保存新成果版本。"
                  okText="批准并继续"
                  cancelText="返回核对"
                  onConfirm={() => onReview?.("approve", feedback.trim(), ids)}
                >
                  <Button type="primary" loading={busy} disabled={!ids.length}>
                    批准所选操作并继续
                  </Button>
                </Popconfirm>
                <Popconfirm
                  title="保持全部数据不变并继续分析？"
                  description="本轮不执行修改，仍可继续关系分析和远景圈定。"
                  okText="保留并继续"
                  cancelText="返回"
                  onConfirm={() =>
                    onReview?.(
                      "approve",
                      feedback.trim() || "本轮保留全部数据",
                      [],
                    )
                  }
                >
                  <Button disabled={busy}>本轮不修改并继续</Button>
                </Popconfirm>
                <Popconfirm
                  title="拒绝本轮修改？"
                  description="保留输入、检查与建议，停止后续修改。"
                  okText="拒绝修改"
                  cancelText="返回"
                  onConfirm={() =>
                    onReview?.("reject", feedback.trim() || "拒绝本轮修改")
                  }
                >
                  <Button disabled={busy}>拒绝本轮修改</Button>
                </Popconfirm>
              </div>
            </div>
          )}
        </section>
      )}
      {editable && !suggestions.length && (
        <Button
          type="primary"
          loading={busy}
          onClick={() =>
            onReview?.("approve", "本轮未形成修改建议，保留数据继续分析", [])
          }
        >
          本轮无修改，继续分析
        </Button>
      )}
      <Link
        target="_blank"
        rel="noopener"
        className="geology-review-map-link"
        to={`/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}`}
      >
        查看本次检查与前后地图
      </Link>
    </section>
  );
}
