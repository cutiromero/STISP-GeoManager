import { Alert, Button, Checkbox, Input, Select, Table, Tag } from "antd";
import { useMemo, useState } from "react";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";
import RetainedReviewMap from "./RetainedReviewMap";
import type { LogicTaskProps } from "./logicTaskTypes";
import { MultiElementEvidence } from "./MultiElementStory";

type Actions = Record<string, "keep" | "exclude" | "downweight">;
const labels: Record<string, string> = {
  set_code: "修正代号",
  reclassify: "重新分类",
  merge: "合并",
  exclude: "剔除",
  downweight: "降权",
  remove: "剔除",
  keep: "保留",
  review: "复核并保留原样",
};
const elements: Record<string, string> = {
  lithology: "岩性",
  structure: "构造",
  alteration: "蚀变",
};

export default function RetainedIssueReview({
  workflow,
  busy = false,
  onReview,
  reviewError,
  readonly = false,
}: {
  workflow: AgentWorkflow;
  busy?: boolean;
  onReview?: LogicTaskProps["onReview"];
  reviewError?: string;
  readonly?: boolean;
}) {
  const items = workflow.modificationReview?.suggestions ?? [];
  const scope = record(workflow.plan.retainedReview);
  const index = record(workflow.plan.reviewIndex);
  const candidateIds = Array.isArray(index.candidateIds)
    ? index.candidateIds.map(String)
    : items.filter((item) => item.candidateAction).map((item) => item.id);
  const [selected, setSelected] = useState<string[]>([]);
  const [focused, setFocused] = useState<string>();
  const [feedback, setFeedback] = useState("");
  const [actions, setActions] = useState<Actions>({});
  const active = items.find((item) => item.id === focused);
  const collection = useMemo<GeoJsonFeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: items.map((item) => ({
        type: "Feature",
        id: item.id,
        geometry: item.preview,
        properties: {
          feature_id: item.featureId,
          rule_id: item.ruleId,
          status: item.status,
          element: item.element,
          label: item.featureId,
          name: item.featureId,
          _review_outlineOnly: item.element === "alteration",
        },
      })),
    }),
    [items],
  );
  const automatic = Array.isArray(scope.automaticSuggestionIds)
    ? scope.automaticSuggestionIds.length
    : 0;
  const total = Number(index.total ?? items.length);
  const selectable = new Set(candidateIds);
  const hasCandidates = selectable.size > 0;
  const initialReview = scope.kind === "initial";
  return (
    <section className="logic-retained-review" aria-label="待核查疑点">
      {!readonly && (
        <p className="logic-description">
          {automatic > 0
            ? `${automatic} 项已核验处置沿用原授权，在本页确认后执行，无需逐项勾选。`
            : ""}
          请根据地图和依据勾选要处理的疑点。确认后按各项所列动作执行，未选疑点保持原样。
        </p>
      )}
      <Alert
        type="info"
        title={
          total > 0
            ? `共 ${total} 项待核查疑点，已读取 ${items.length} 项`
            : "本次没有待核查疑点"
        }
        description={
          readonly
            ? "地图展示已授权的处置位置和待核查范围。标记表示授权或核查范围，实际修改请查看清洗成果。"
            : "点击疑点查看位置和依据。勾选“复核并保留原样”的疑点会执行实际复核并记录结果，不改变原资料。"
        }
      />
      {workflow.plan.reviewIndex?.automaticMap &&
        workflow.plan.reviewIndex.automaticMap.total > 0 && (
          <p className="logic-automatic-map-note">
            <i aria-hidden="true" /> 已授权处置{" "}
            {workflow.plan.reviewIndex.automaticMap.total}{" "}
            项，以浅灰绿圆点显示，邻近位置自动合并；待核查疑点使用醒目标记。
            {workflow.plan.reviewIndex.automaticMap.locatedCount <
            workflow.plan.reviewIndex.automaticMap.total
              ? `其中 ${workflow.plan.reviewIndex.automaticMap.locatedCount} 项具备可定位范围。`
              : ""}
          </p>
        )}
      {(collection.features.length > 0 ||
        Boolean(workflow.plan.reviewIndex?.automaticMap?.points.length)) && (
        <RetainedReviewMap
          workflow={workflow}
          objects={collection}
          focused={focused}
          onFocus={setFocused}
        />
      )}
      {!readonly && candidateIds.length > 0 && (
        <Checkbox
          checked={candidateIds.every((id) => selected.includes(id))}
          indeterminate={
            candidateIds.some((id) => selected.includes(id)) &&
            !candidateIds.every((id) => selected.includes(id))
          }
          disabled={busy}
          onChange={(event) =>
            setSelected(event.target.checked ? candidateIds : [])
          }
        >
          选择全部待核查疑点（{candidateIds.length} 项）
        </Checkbox>
      )}
      {items.length > 0 && (
        <Table
          size="small"
          rowKey="id"
          dataSource={items}
          pagination={{
            pageSize: 10,
            showSizeChanger: false,
            showTotal: (n) => `已读取 ${n} 条`,
          }}
          scroll={{ x: 600 }}
          rowSelection={
            readonly || !hasCandidates
              ? undefined
              : {
                  selectedRowKeys: selected,
                  preserveSelectedRowKeys: true,
                  onChange: (keys) => setSelected(keys.map(String)),
                  getCheckboxProps: (item) => ({
                    disabled: busy || !selectable.has(item.id),
                    "aria-label": `处置${item.featureId}`,
                  }),
                }
          }
          columns={[
            {
              title: "对象",
              dataIndex: "featureId",
              width: 150,
              render: (value, item) => (
                <Button
                  type="link"
                  size="small"
                  onClick={() => setFocused(item.id)}
                >
                  {value}
                </Button>
              ),
            },
            {
              title: "要素",
              dataIndex: "element",
              width: 70,
              render: (value) => elements[String(value)] ?? value,
            },
            {
              title: "规则与原因",
              key: "reason",
              render: (_, item) => (
                <>
                  <Tag color={item.status === "exception" ? "orange" : "gold"}>
                    {item.ruleId} ·{" "}
                    {item.status === "exception" ? "规则例外" : "待核查"}
                  </Tag>
                  <p>{item.reason}</p>
                </>
              ),
            },
            {
              title: "执行动作",
              key: "action",
              width: 110,
              render: (_, item) =>
                item.suggestedState === "已复核，未修改"
                  ? item.suggestedState
                  : (labels[item.candidateAction ?? ""] ?? "保留核查"),
            },
          ]}
        />
      )}
      {active && (
        <article className="logic-retained-evidence" aria-label="当前对象依据">
          <h4>
            {active.featureId} · {active.ruleId}
          </h4>
          <p>{active.reason}</p>
          <p>
            <strong>当前识别：</strong>
            {active.currentState}
          </p>
          <p>
            <strong>执行动作：</strong>
            {labels[active.candidateAction ?? ""] ?? "保留核查"}
            {active.candidateTargetCode
              ? `，目标代号 ${active.candidateTargetCode}`
              : active.candidateAction === "downweight"
                ? "，权重 0.5，保留对象"
                : active.candidateAction === "exclude"
                  ? "，从修正后成果剔除"
                  : ""}
          </p>
          {!readonly && selectable.has(active.id) && (
            <Checkbox
              aria-label="选择当前待核查疑点"
              checked={selected.includes(active.id)}
              disabled={busy}
              onChange={(event) =>
                setSelected((previous) =>
                  event.target.checked
                    ? [...new Set([...previous, active.id])]
                    : previous.filter((id) => id !== active.id),
                )
              }
            >
              选择当前待核查疑点
            </Checkbox>
          )}
          {Array.isArray(active.observations?.related_rule_hits) && (
            <ul aria-label="同一疑点命中的规则">
              {active.observations.related_rule_hits.map((value) => {
                const hit = record(value);
                return (
                  <li key={String(hit.id)}>
                    {String(hit.rule_id)}：{String(hit.reason)}
                  </li>
                );
              })}
            </ul>
          )}
          <MultiElementEvidence suggestion={active} />
          {!readonly &&
            active.featureId?.startsWith("AG-") &&
            active.candidateAction &&
            active.candidateAction !== "review" && (
              <Select
                aria-label="当前蚀变对象处置"
                value={
                  selected.includes(active.id)
                    ? (actions[active.featureId] ??
                      (active.candidateAction === "exclude" ||
                      active.candidateAction === "downweight"
                        ? active.candidateAction
                        : "keep"))
                    : "keep"
                }
                options={[
                  { value: "keep", label: "保留" },
                  { value: "downweight", label: "降权" },
                  { value: "exclude", label: "剔除" },
                ].filter(
                  (option) =>
                    option.value === "keep" ||
                    active.allowedActions?.includes(option.value),
                )}
                onChange={(value) => {
                  setActions((previous) => {
                    const next = { ...previous };
                    if (value === "keep") delete next[active.featureId!];
                    else next[active.featureId!] = value;
                    return next;
                  });
                  setSelected((previous) =>
                    value === "keep"
                      ? previous.filter((id) => id !== active.id)
                      : [...new Set([...previous, active.id])],
                  );
                }}
              />
            )}
        </article>
      )}
      {!readonly && onReview && (
        <div className="geology-review-controls">
          <p>
            已选择 {selected.length} 项待核查疑点，其余保留。
            {initialReview
              ? "确认后开始处置，再生成复查和前后对比。"
              : "确认后生成新一轮处置、复查和前后对比，上一轮成果保留。"}
          </p>
          <Input.TextArea
            aria-label="疑点核查意见"
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            disabled={busy}
            placeholder="可填写裁定依据或补充核查意见"
            maxLength={4000}
            autoSize={{ minRows: 2, maxRows: 4 }}
          />
          {reviewError && <Alert type="error" title={reviewError} />}
          <Button
            type="primary"
            loading={busy}
            onClick={() =>
              onReview(
                "approve",
                feedback,
                selected,
                Object.fromEntries(
                  Object.entries(actions).filter(([feature]) =>
                    items.some(
                      (item) =>
                        item.featureId === feature &&
                        selected.includes(item.id),
                    ),
                  ),
                ),
              )
            }
          >
            {selected.length
              ? `执行所选 ${selected.length} 项并继续`
              : "保留未选疑点并继续"}
          </Button>
        </div>
      )}
    </section>
  );
}
