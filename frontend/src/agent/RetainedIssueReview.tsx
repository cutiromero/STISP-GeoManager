import { Alert, Button, Checkbox, Input, Select, Table, Tag } from "antd";
import { useMemo, useState } from "react";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import LocalGeologyReviewMaps from "../map/LocalGeologyReviewMaps";
import { record, reviewBounds } from "../map/geologyReviewData";
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
  review: "继续核查",
};
const elements: Record<string, string> = {
  lithology: "岩性",
  structure: "构造",
  alteration: "蚀变",
};
const empty: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [],
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
          label: item.featureId,
        },
      })),
    }),
    [items],
  );
  const bounds = useMemo(() => reviewBounds(collection), [collection]);
  const automatic = Array.isArray(scope.automaticSuggestionIds)
    ? scope.automaticSuggestionIds.length
    : 0;
  const total = Number(index.total ?? items.length);
  return (
    <section className="logic-retained-review" aria-label="保留对象核查">
      {!readonly && (
        <p className="logic-description">
          {automatic > 0
            ? `${automatic} 项确定性处置沿用原授权，无需逐项确认。`
            : ""}
          请查看以下待裁定与例外，勾选需要执行候选处置的对象；未选对象保持原样。
        </p>
      )}
      <Alert
        type="info"
        title={`共 ${total} 条保留对象，已读取 ${items.length} 条`}
        description="地图展示已读取对象的实际位置，蚀变组以定位范围表示。可缩放、平移并点击查看依据。候选动作仅在您明确选择后执行；没有有效候选的对象只能保留核查。"
      />
      {collection.features.length > 0 && (
        <LocalGeologyReviewMaps
          before={collection}
          after={null}
          differences={empty}
          bounds={bounds}
          inspectionOnly
          single
          spotlight={
            focused
              ? {
                  before: {
                    type: "FeatureCollection",
                    features: collection.features.filter(
                      (feature) => String(feature.id) === focused,
                    ),
                  },
                  after: empty,
                  beforeLabel: active?.featureId,
                  outlineOnly: true,
                  dimBackground: true,
                }
              : null
          }
          beforeLabel="待核查对象位置"
          compactLegend
          onSelect={() => {}}
          onInspect={(feature) => setFocused(String(feature.id))}
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
          选择全部有效候选（{candidateIds.length} 项）
        </Checkbox>
      )}
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
          readonly
            ? undefined
            : {
                selectedRowKeys: selected,
                preserveSelectedRowKeys: true,
                onChange: (keys) => setSelected(keys.map(String)),
                getCheckboxProps: (item) => ({
                  disabled: busy || !item.candidateAction,
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
                  {item.status === "exception" ? "规则例外" : "待裁定"}
                </Tag>
                <p>{item.reason}</p>
              </>
            ),
          },
          {
            title: "候选处置",
            key: "action",
            width: 110,
            render: (_, item) =>
              item.candidateAction
                ? (labels[item.candidateAction] ?? item.candidateAction)
                : "保留核查",
          },
        ]}
      />
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
            <strong>候选处置：</strong>
            {labels[active.candidateAction ?? ""] ?? "保留核查"}
            {active.candidateTargetCode
              ? `，目标代号 ${active.candidateTargetCode}`
              : active.candidateAction === "downweight"
                ? "，权重 0.5，保留对象"
                : active.candidateAction === "exclude"
                  ? "，从修正后成果剔除"
                  : ""}
          </p>
          {!readonly && active.candidateAction && (
            <Checkbox
              aria-label="选择当前对象的候选处置"
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
              选择当前对象的候选处置
            </Checkbox>
          )}
          <MultiElementEvidence suggestion={active} />
          {!readonly &&
            active.featureId?.startsWith("AG-") &&
            active.candidateAction && (
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
            已选择 {selected.length}{" "}
            项人工处置，其余保留。确认后将重新生成处置结果、复查和前后对比，上一轮成果保留。
          </p>
          <Input.TextArea
            aria-label="保留对象裁定意见"
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
              : "保留未选对象并继续"}
          </Button>
        </div>
      )}
    </section>
  );
}
