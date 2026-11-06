import { Alert, Button, Checkbox, Input, Popconfirm, Select, Tag } from "antd";
import { useState } from "react";
import type { AlterationActions } from "./approvalSelection";
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
import {
  heldModificationGroups,
  modificationAction,
  presentationGroups,
  selectableModification,
} from "./modificationPresentation";

const elements: Record<string, string> = {
  lithology: "岩性",
  structure: "构造",
  alteration: "蚀变",
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
  pixel_count: "像元数",
  component_count: "连通区数",
  group_id: "稳定组标识",
  unit_code: "岩性单元",
  rock_group: "岩性分组",
  boundary: "边界混合像元",
  bbox: "组范围",
  representatives: "代表连通区（最多3个）",
  raster_protocol: "栅格协议",
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
  reviewError,
  focus = "all",
}: {
  focus?: "all" | "review" | "retained";
  workflow: AgentWorkflow;
  busy?: boolean;
  reviewError?: string;
  onReview?: (
    decision: "approve" | "reject",
    feedback: string,
    selectedSuggestionIds?: string[],
    alterationActions?: AlterationActions,
  ) => void;
}) {
  const review = workflow.modificationReview;
  const reviewIndex = record(workflow.plan.reviewIndex);
  const indexGroups = Array.isArray(reviewIndex.groups)
    ? reviewIndex.groups.map(record)
    : [];
  const suggestedIds = Array.isArray(reviewIndex.suggestedIds)
    ? reviewIndex.suggestedIds.map(String)
    : (review?.suggestions ?? [])
        .filter(
          (item) => item.status === "suggested" && selectableModification(item),
        )
        .map((item) => item.id);
  const candidateIds = Array.isArray(reviewIndex.candidateIds)
    ? reviewIndex.candidateIds.map(String)
    : (review?.suggestions ?? [])
        .filter((item) => item.candidateAction)
        .map((item) => item.id);
  const initialIds = review?.approvedSuggestionIds.length
    ? review.approvedSuggestionIds
    : suggestedIds;
  const [selection, setSelection] = useState<{ hash: string; ids: string[] }>({
    hash: review?.proposalHash ?? "",
    ids: initialIds,
  });
  const [filter, setFilter] = useState("all");
  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);
  const [groupPages, setGroupPages] = useState<Record<string, number>>({});
  const [groupSearch, setGroupSearch] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");
  const [actionSelection, setActionSelection] = useState<{
    hash: string;
    actions: AlterationActions;
  }>({ hash: review?.proposalHash ?? "", actions: {} });
  const alterationActions =
    actionSelection.hash === review?.proposalHash
      ? actionSelection.actions
      : {};
  const setAlterationActions = (
    updateActions: (current: AlterationActions) => AlterationActions,
  ) =>
    setActionSelection({
      hash: review?.proposalHash ?? "",
      actions: updateActions(alterationActions),
    });
  const suggestions = review?.suggestions ?? [];
  const ids =
    selection.hash === review?.proposalHash ? selection.ids : initialIds;
  const selectedIds = new Set(ids);
  const modelIds = new Set(suggestedIds);
  const userIds = new Set(candidateIds);
  const approved = review?.approvedSuggestionIds ?? [];
  const editable =
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications" &&
    Boolean(onReview);
  const selectable = suggestions.filter(selectableModification);
  const visible = selectable.filter(
    (item) => filter === "all" || item.element === filter,
  );
  const selectableIds = new Set(selectable.map((item) => item.id));
  const held = suggestions.filter((item) => !selectableModification(item));
  const update = (values: string[]) =>
    setSelection({ hash: review?.proposalHash ?? "", ids: values });
  const groups = presentationGroups(visible);
  const decisions = workflow.steps.flatMap((step) =>
    step.decision ? [step.decision] : [],
  );
  const latest = decisions[decisions.length - 1];
  const stages = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
  ).map(record);
  const algorithms = record(workflow.plan.algorithms);
  const retainedGroups = indexGroups.length
    ? indexGroups
        .filter(
          (group) =>
            group.held && (filter === "all" || group.element === filter),
        )
        .map((group) => ({
          element: String(group.element),
          ruleId: String(group.ruleId),
          count: Number(group.count),
          reasons: new Set<string>(),
          reasonCounts: record(group.reasons),
          candidateIds: Array.isArray(group.ids) ? group.ids.map(String) : [],
        }))
    : heldModificationGroups(suggestions, stages, filter).map((group) => {
        const members = suggestions.filter(
          (item) =>
            item.element === group.element &&
            item.ruleId === group.ruleId &&
            !selectableModification(item),
        );
        const reasonCounts: Record<string, number> = {};
        for (const item of members) {
          const tier = suggestionTier(item);
          reasonCounts[tier] = (reasonCounts[tier] ?? 0) + 1;
        }
        return {
          ...group,
          reasonCounts,
          candidateIds: members
            .filter((item) => item.candidateAction)
            .map((item) => item.id),
        };
      });
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
      {focus === "all" && (
        <>
          <div className="geology-story-heading">
            <strong>{title}</strong>
            <Tag color="blue">{generic ? "本次资料" : "演示案例"}</Tag>
            <Tag>
              {
                multiElementSegments.find((item) => item.value === segment)
                  ?.label
              }
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
            {latestText && latestText !== workflow.detail && (
              <p>{latestText}</p>
            )}
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
                    {rule.ruleId} / {rule.title} / 版本 {rule.ruleVersion} /
                    修订 {rule.revision}
                  </li>
                ))}
              </ul>
              <strong>本次真实算法</strong>
              <ul>
                {stages.map((stage) => {
                  const algorithm = record(
                    algorithms[String(stage.identifier)],
                  );
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
        </>
      )}
      {(suggestions.length > 0 || retainedGroups.length > 0) && (
        <section className="geology-suggestions" aria-label="多要素检查建议">
          {Number(editValidation.discardedCount) > 0 && (
            <p role="status">
              模型另提出 {Number(editValidation.discardedCount)} 项建议因
              {discardedReasons}未采用；其余建议仍需逐项人工确认。
            </p>
          )}
          <div className="geology-suggestions-heading">
            <h3>
              {focus === "retained"
                ? "待裁定与例外"
                : `发现的问题与建议 / ${focus === "all" ? suggestions.length : Number(reviewIndex.total ?? suggestions.length)} 项`}
            </h3>
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
              checked={
                candidateIds.length > 0 &&
                candidateIds.every((id) => selectedIds.has(id))
              }
              indeterminate={
                candidateIds.some((id) => selectedIds.has(id)) &&
                !candidateIds.every((id) => selectedIds.has(id))
              }
              disabled={busy}
              onChange={(event) =>
                update(
                  event.target.checked
                    ? [...new Set([...ids, ...candidateIds])]
                    : ids.filter((id) => !userIds.has(id)),
                )
              }
            >
              全部待裁定与例外按候选处置
            </Checkbox>
          )}
          <div className="multi-element-suggestion-list">
            {focus !== "retained" &&
              [...groups].map(([groupId, members]) => {
                const first = members[0]!;
                const eligible = members.filter((item) =>
                  selectableIds.has(item.id),
                );
                const indexed = indexGroups.find(
                  (group) =>
                    !group.held &&
                    group.element === first.element &&
                    group.ruleId === first.ruleId &&
                    group.action === first.action,
                );
                const eligibleIds = new Set(
                  indexed && Array.isArray(indexed.ids)
                    ? indexed.ids.map(String)
                    : eligible.map((item) => item.id),
                );
                const chosenCount = [...eligibleIds].filter((id) =>
                  selectedIds.has(id),
                ).length;
                const matches = members.filter((item) =>
                  item.featureId
                    .toLowerCase()
                    .includes(
                      (groupSearch[groupId] ?? "").trim().toLowerCase(),
                    ),
                );
                return (
                  <div key={groupId}>
                    <p>{first.reason}</p>
                    {editable && eligible.length > 0 && (
                      <Checkbox
                        disabled={busy}
                        checked={chosenCount === eligibleIds.size}
                        indeterminate={
                          chosenCount > 0 && chosenCount < eligibleIds.size
                        }
                        onChange={(event) =>
                          update(
                            event.target.checked
                              ? [...new Set([...ids, ...eligibleIds])]
                              : ids.filter((id) => !eligibleIds.has(id)),
                          )
                        }
                      >
                        整组批准（{eligibleIds.size} 个对象）
                      </Checkbox>
                    )}
                    <details
                      open={expandedGroups.includes(groupId)}
                      onToggle={(event) => {
                        const open = event.currentTarget.open;
                        setExpandedGroups((current) =>
                          open
                            ? [...new Set([...current, groupId])]
                            : current.filter((key) => key !== groupId),
                        );
                      }}
                    >
                      <summary>
                        {elements[first.element ?? ""]} / {first.ruleId} /{" "}
                        {members.length === 1
                          ? modificationAction(first)
                          : modificationAction({
                              ...first,
                              suggestedState: first.action ?? "",
                            })}{" "}
                        · {Number(indexed?.count ?? members.length)} 个对象
                      </summary>
                      <p>{first.reason}</p>
                      <p>
                        {[
                          ...members.reduce((counts, item) => {
                            const label = modificationAction(item);
                            counts.set(label, (counts.get(label) ?? 0) + 1);
                            return counts;
                          }, new Map<string, number>()),
                        ]
                          .map(([label, count]) => `${label}：${count} 个对象`)
                          .join("；")}
                      </p>
                      {expandedGroups.includes(groupId) && (
                        <Input
                          aria-label={`搜索对象编号 ${first.ruleId}`}
                          placeholder="搜索组内对象编号"
                          value={groupSearch[groupId] ?? ""}
                          onChange={(event) => {
                            setGroupSearch((current) => ({
                              ...current,
                              [groupId]: event.target.value,
                            }));
                            setGroupPages((current) => ({
                              ...current,
                              [groupId]: 50,
                            }));
                          }}
                        />
                      )}
                      {expandedGroups.includes(groupId) &&
                        matches
                          .slice(0, groupPages[groupId] ?? 50)
                          .map((item) => (
                            <details
                              className="multi-element-suggestion"
                              key={item.id}
                            >
                              <summary>
                                <span>
                                  {elements[item.element ?? ""] ?? "检查"} /{" "}
                                  {item.title}
                                </span>
                                <small>对象：{item.featureId}</small>
                                <Tag
                                  color={
                                    approved.includes(item.id)
                                      ? "blue"
                                      : undefined
                                  }
                                >
                                  {approved.includes(item.id)
                                    ? "已批准"
                                    : item.status === "review"
                                      ? "待裁定"
                                      : item.status === "exception"
                                        ? "例外候选"
                                        : modificationAction(item)}
                                </Tag>
                              </summary>
                              <div className="multi-element-suggestion-body">
                                {editable &&
                                  item.featureId?.startsWith("AG-") && (
                                    <Select
                                      aria-label={`蚀变组动作 ${item.featureId}`}
                                      value={
                                        alterationActions[item.featureId] ??
                                        (item.action === "exclude"
                                          ? "exclude"
                                          : item.action === "downweight"
                                            ? "downweight"
                                            : "keep")
                                      }
                                      disabled={busy}
                                      options={[
                                        { value: "exclude", label: "剔除" },
                                        {
                                          value: "downweight",
                                          label: "降权（0.5）",
                                        },
                                        { value: "keep", label: "保留" },
                                      ]}
                                      onChange={(
                                        action:
                                          | "exclude"
                                          | "downweight"
                                          | "keep",
                                      ) => {
                                        setAlterationActions((current) => ({
                                          ...current,
                                          [item.featureId!]: action,
                                        }));
                                        update([...new Set([...ids, item.id])]);
                                      }}
                                    />
                                  )}
                                <p className="multi-element-suggestion-tier">
                                  处置分级：{suggestionTier(item)}
                                </p>
                                {editable && selectableIds.has(item.id) && (
                                  <Checkbox
                                    disabled={busy}
                                    checked={selectedIds.has(item.id)}
                                    onChange={(event) =>
                                      update(
                                        event.target.checked
                                          ? [...ids, item.id]
                                          : ids.filter((id) => id !== item.id),
                                      )
                                    }
                                  >
                                    批准此对象的「
                                    {modificationAction(item)}
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
                                    <dd>{modificationAction(item)}</dd>
                                  </div>
                                </dl>
                                <p>
                                  {item.element === "structure" &&
                                  item.lengthM !== undefined
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
                      {expandedGroups.includes(groupId) &&
                        matches.length === 0 && <p>没有匹配的对象编号</p>}
                      {expandedGroups.includes(groupId) &&
                        matches.length > (groupPages[groupId] ?? 50) && (
                          <Button
                            size="small"
                            onClick={() =>
                              setGroupPages((current) => ({
                                ...current,
                                [groupId]: (current[groupId] ?? 50) + 50,
                              }))
                            }
                          >
                            查看更多对象（已显示 {groupPages[groupId] ?? 50} /{" "}
                            {matches.length}）
                          </Button>
                        )}
                    </details>
                  </div>
                );
              })}
            {focus !== "retained" &&
              indexGroups
                .filter(
                  (group) =>
                    !group.held &&
                    !visible.some(
                      (item) =>
                        item.element === group.element &&
                        item.ruleId === group.ruleId &&
                        item.action === group.action,
                    ),
                )
                .map((group) => {
                  const groupIds = Array.isArray(group.ids)
                    ? group.ids.map(String)
                    : [];
                  return (
                    <div
                      key={JSON.stringify([
                        group.element,
                        group.ruleId,
                        group.action,
                      ])}
                    >
                      <p>
                        {elements[String(group.element)]} /{" "}
                        {String(group.ruleId)} / {String(group.action)} ·{" "}
                        {Number(group.count)} 个对象
                      </p>
                      <Checkbox
                        disabled={!editable || busy}
                        checked={groupIds.every((id) => selectedIds.has(id))}
                        indeterminate={
                          groupIds.some((id) => selectedIds.has(id)) &&
                          !groupIds.every((id) => selectedIds.has(id))
                        }
                        onChange={(event) =>
                          update(
                            event.target.checked
                              ? [...new Set([...ids, ...groupIds])]
                              : ids.filter((id) => !groupIds.includes(id)),
                          )
                        }
                      >
                        整组批准（{groupIds.length} 个对象）
                      </Checkbox>
                      <p>对象原因按页读取，可在卡片末尾读取更多审批对象。</p>
                    </div>
                  );
                })}
            {retainedGroups.length > 0 && (
              <details
                className="multi-element-held-groups"
                open={focus === "retained" ? true : undefined}
              >
                <summary>
                  {focus === "retained" ? "初检待裁定与例外" : "待裁定与例外"}
                  （共 {retainedGroups.length} 组 /{" "}
                  {retainedGroups.reduce(
                    (count, group) => count + group.count,
                    0,
                  )}{" "}
                  个对象）
                </summary>
                {retainedGroups.map((group) => {
                  const members = held.filter(
                    (item) =>
                      item.element === group.element &&
                      item.ruleId === group.ruleId,
                  );
                  const candidateIds = new Set(group.candidateIds);
                  const groupKey = JSON.stringify([
                    group.element,
                    group.ruleId,
                  ]);
                  const candidateLabel = [
                    ...new Set(members.map(modificationAction)),
                  ].join(" / ");
                  return (
                    <details
                      key={groupKey}
                      open={expandedGroups.includes(groupKey)}
                    >
                      <summary
                        onClick={(event) => {
                          event.preventDefault();
                          setExpandedGroups((current) =>
                            current.includes(groupKey)
                              ? current.filter((key) => key !== groupKey)
                              : [...current, groupKey],
                          );
                        }}
                      >
                        {elements[group.element] ?? "检查"} / {group.ruleId} ·{" "}
                        {group.count} 个对象
                      </summary>
                      <p>
                        {group.ruleId} 规则共 {group.count}{" "}
                        个对象，因规则判定需人工裁定或符合例外条件，默认保留。
                      </p>
                      <ul>
                        {Object.entries(group.reasonCounts).map(
                          ([reason, count]) => (
                            <li key={reason}>
                              {reason}：{String(count)} 处
                            </li>
                          ),
                        )}
                      </ul>
                      <p>
                        默认保留；仅您明确选择后按冻结候选处置，规则状态及例外原因不变。
                      </p>
                      {expandedGroups.includes(groupKey) && (
                        <>
                          <Select
                            style={{ width: "100%" }}
                            aria-label={`${group.ruleId}组待裁定处置`}
                            value={
                              [...candidateIds].every((id) =>
                                selectedIds.has(id),
                              )
                                ? "candidate"
                                : [...candidateIds].some((id) =>
                                      selectedIds.has(id),
                                    )
                                  ? "mixed"
                                  : "keep"
                            }
                            disabled={!editable || busy || !candidateIds.size}
                            options={[
                              { value: "keep", label: "保留本组" },
                              {
                                value: "candidate",
                                label: `按本组候选处置：${candidateLabel}`,
                              },
                              {
                                value: "mixed",
                                label: "逐对象选择",
                                disabled: true,
                              },
                            ]}
                            onChange={(value) =>
                              update(
                                value === "candidate"
                                  ? [...new Set([...ids, ...candidateIds])]
                                  : ids.filter((id) => !candidateIds.has(id)),
                              )
                            }
                          />
                          {members
                            .slice(0, groupPages[groupKey] ?? 50)
                            .map((item) => (
                              <details key={item.id}>
                                <summary>
                                  {item.featureId} / {suggestionTier(item)} /{" "}
                                  {modificationAction(item)}
                                </summary>
                                <Select
                                  style={{ width: "100%" }}
                                  aria-label={`${item.featureId}待裁定处置`}
                                  value={
                                    selectedIds.has(item.id)
                                      ? "candidate"
                                      : "keep"
                                  }
                                  disabled={
                                    !editable || busy || !item.candidateAction
                                  }
                                  options={[
                                    { value: "keep", label: "保留" },
                                    {
                                      value: "candidate",
                                      label: `按候选处置：${modificationAction(item)}`,
                                    },
                                  ]}
                                  onChange={(value) =>
                                    update(
                                      value === "candidate"
                                        ? [...new Set([...ids, item.id])]
                                        : ids.filter((id) => id !== item.id),
                                    )
                                  }
                                />
                                {editable &&
                                  item.featureId?.startsWith("AG-") && (
                                    <Select
                                      aria-label={`蚀变组动作 ${item.featureId}`}
                                      value={
                                        alterationActions[item.featureId] ??
                                        "keep"
                                      }
                                      disabled={busy}
                                      options={[
                                        { value: "exclude", label: "明确剔除" },
                                        {
                                          value: "downweight",
                                          label: "降权（0.5）",
                                        },
                                        { value: "keep", label: "保留" },
                                      ]}
                                      onChange={(
                                        action:
                                          | "exclude"
                                          | "downweight"
                                          | "keep",
                                      ) => {
                                        setAlterationActions((current) => ({
                                          ...current,
                                          [item.featureId!]: action,
                                        }));
                                        update([...new Set([...ids, item.id])]);
                                      }}
                                    />
                                  )}
                                <MultiElementEvidence suggestion={item} />
                                <p>{item.reason}</p>
                                <Link
                                  target="_blank"
                                  rel="noopener"
                                  to={`/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}&suggestion=${encodeURIComponent(item.id)}`}
                                >
                                  在地图上定位此对象
                                </Link>
                              </details>
                            ))}
                          {members.length > (groupPages[groupKey] ?? 50) && (
                            <Button
                              onClick={() =>
                                setGroupPages((current) => ({
                                  ...current,
                                  [groupKey]: (current[groupKey] ?? 50) + 50,
                                }))
                              }
                            >
                              查看更多待裁定对象
                            </Button>
                          )}
                        </>
                      )}
                    </details>
                  );
                })}
              </details>
            )}
          </div>
          {editable && (
            <div className="geology-review-controls">
              {reviewError && (
                <Alert
                  type="error"
                  showIcon
                  role="alert"
                  title={`审批未提交：${reviewError}`}
                />
              )}
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
                已选择 {ids.length} 项（有效建议{" "}
                {ids.filter((id) => modelIds.has(id)).length} 项、用户裁定{" "}
                {ids.filter((id) => userIds.has(id)).length} 项）。
                仅执行当前勾选的对象与动作，保存新成果版本；未选中和待裁定项保持原样。
              </p>
              <div className="geology-review-buttons">
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!ids.length}
                  onClick={() => {
                    const actions = Object.fromEntries(
                      Object.entries(alterationActions).filter(([group]) =>
                        suggestions.some(
                          (item) =>
                            item.featureId === group &&
                            selectedIds.has(item.id),
                        ),
                      ),
                    );
                    if (Object.keys(actions).length)
                      onReview?.("approve", feedback.trim(), ids, actions);
                    else onReview?.("approve", feedback.trim(), ids);
                  }}
                >
                  批准所选操作并继续
                </Button>
                <Button
                  disabled={busy}
                  onClick={() =>
                    onReview?.(
                      "approve",
                      feedback.trim() || "本轮保留全部数据",
                      [],
                    )
                  }
                >
                  本轮不修改并继续
                </Button>
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
