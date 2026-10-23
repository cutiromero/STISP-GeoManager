import {
  AimOutlined,
  ArrowLeftOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Checkbox, Empty, Spin, Tag } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import {
  MultiElementEvidence,
  formatMultiElementObservation,
} from "../agent/MultiElementStory";
import WorkflowReportFile from "../agent/WorkflowReportFile";
import GeologyReviewMaps from "./GeologyReviewMaps";
import {
  previewSuggestions,
  queryReviewMap,
  record,
  reviewBounds,
} from "./geologyReviewData";
import type { ReviewOverlay } from "./reviewVectorLayers";

const empty: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
type Feature = GeoJsonFeatureCollection["features"][number];
type MultiMaps = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
  overlays: ReviewOverlay[];
  issues: GeoJsonFeatureCollection;
};
const displayFields: Record<string, string> = {
  name: "岩性名称",
  geo_sym: "地质代号",
  element: "要素",
  rule_id: "命中规则",
  rule_version: "规则版本",
  current_label: "改前状态",
  suggested_label: "建议状态",
  old_value: "改前状态",
  new_value: "改后状态",
  reason: "原因与依据",
  status: "处理状态",
  state: "处理状态",
  weight: "参与权重",
  action: "实际操作",
  suggested_action: "检查建议操作",
  actual_changed: "实际发生变化",
  measurements_json: "实际测量值",
  conditions: "适用条件",
  exceptions: "地质例外与证据缺口",
  grade: "优先核查证据组合等级",
  area_km2: "面积（平方公里）",
  explanation: "形成依据",
  evidence_json: "具体证据链",
  alt: "矿物识别类型",
  inferred: "是否推测交汇",
  gap_m: "推测间距（米）",
  angle_deg: "夹角（度）",
  type: "交汇性质",
};
const values: Record<string, string> = {
  suggested: "建议处理",
  review: "待裁定",
  exception: "例外候选",
  retained: "保留",
  keep: "保留",
  retain: "保留",
  downweight: "降权",
  exclude: "本次暂不参与",
  remove: "剔除",
  set_code: "校正地质代号",
  merge: "融合图斑",
  reclassify: "重分类",
  lithology: "岩性",
  structure: "构造",
  alteration: "蚀变",
};
function readable(value: unknown): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number")
    return value.toLocaleString("zh-CN", { maximumFractionDigits: 5 });
  if (typeof value === "string") {
    if (value.startsWith("[") || value.startsWith("{")) {
      try {
        return readable(JSON.parse(value));
      } catch {
        /* show source text */
      }
    }
    return values[value] ?? value;
  }
  if (Array.isArray(value)) return value.map(readable).join("；");
  return Object.entries(record(value))
    .map(([key, item]) => `${displayFields[key] ?? key}：${readable(item)}`)
    .join("；");
}

export default function MultiElementWorkspace({
  workflow,
  suggestionId,
  onReload,
}: {
  workflow: AgentWorkflow;
  suggestionId: string | null;
  onReload: () => void;
}) {
  const navigate = useNavigate();
  const { bootstrap } = useAppContext();
  const [data, setData] = useState<MultiMaps>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [focus, setFocus] = useState<[number, number, number, number] | null>(
    null,
  );
  const [selected, setSelected] = useState<Feature>();
  const [optionalData, setOptionalData] = useState<
    Record<string, GeoJsonFeatureCollection>
  >({});
  const [optionalErrors, setOptionalErrors] = useState<Record<string, string>>(
    {},
  );
  const [optionalLoading, setOptionalLoading] = useState<string[]>([]);
  const optionalRequests = useRef(
    new Map<string, Promise<GeoJsonFeatureCollection>>(),
  );
  const resourceRequests = useRef(
    new Map<number, Promise<GeoJsonFeatureCollection>>(),
  );
  const [visible, setVisible] = useState([
    "faults",
    "intersections",
    "prospects",
  ]);
  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError("");
    setData(undefined);
    setOptionalData({});
    setOptionalErrors({});
    setOptionalLoading([]);
    const load = async () => {
      const map = workflow.plan.multiElementMap ?? {};
      const inputs = record(workflow.plan.inputs);
      const beforeId = map.before?.lithology ?? Number(inputs.lithology);
      const faultsId = map.before?.faults ?? Number(inputs.faults);
      if (!beforeId || !faultsId)
        throw new Error("当前任务尚无完整岩性和构造输入");
      const requests = resourceRequests.current;
      const query = (id: number | undefined) => {
        if (!id) return Promise.resolve(empty);
        if (!requests.has(id))
          requests.set(
            id,
            queryReviewMap(id, { mixed: true, allowEmpty: true }).catch(
              (reason: unknown) => {
                requests.delete(id);
                throw reason;
              },
            ),
          );
        return requests.get(id)!;
      };
      const merge = async (ids: number[]) => ({
        type: "FeatureCollection" as const,
        features: (await Promise.all(ids.map(query))).flatMap(
          (item) => item.features,
        ),
      });
      const [
        before,
        after,
        faults,
        afterFaults,
        changes,
        intersections,
        beforeProspects,
        afterProspects,
      ] = await Promise.all([
        query(beforeId),
        map.after?.lithology
          ? query(map.after.lithology)
          : Promise.resolve(null),
        query(faultsId),
        query(map.after?.faults ?? faultsId),
        merge(map.changes ?? []),
        query(map.intersections),
        query(map.beforeProspects),
        query(map.afterProspects),
      ]);
      if (disposed) return;
      const differences =
        map.changes !== undefined ? changes : previewSuggestions(workflow);
      const issues = previewSuggestions(workflow);
      const overlays: ReviewOverlay[] = [
        {
          key: "faults",
          label: "构造",
          before: faults,
          after: afterFaults,
          color: "#76566d",
        },
        {
          key: "checks",
          label: "待核查项",
          before: issues,
          after: issues,
          color: "#b0823e",
        },
        {
          key: "alterations",
          label: "矿物与处理状态",
          before: empty,
          after: empty,
          color: "#648e91",
        },
        {
          key: "intersections",
          label: "构造交汇",
          after: intersections,
          color: "#b4526e",
        },
        {
          key: "prospects",
          label: "优先核查远景区 A/B",
          before: beforeProspects,
          after: afterProspects,
          color: "#537fc0",
        },
      ];
      setData({ before, after, differences, overlays, issues });
      const suggestion = workflow.modificationReview?.suggestions.find(
        (item) => item.id === suggestionId,
      );
      const feature = [...differences.features, ...issues.features].find(
        (item) =>
          item.properties.suggestion_id === suggestionId ||
          item.properties.issue_id === suggestionId ||
          (suggestion &&
            String(item.properties.feature_id) === suggestion.featureId &&
            item.properties.rule_id === suggestion.ruleId),
      );
      setSelected(feature);
      setFocus(
        reviewBounds(
          feature ? { type: "FeatureCollection", features: [feature] } : before,
        ),
      );
    };
    void load()
      .catch((reason: unknown) => {
        if (!disposed)
          setError(reason instanceof Error ? reason.message : "地图读取失败");
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [workflow, suggestionId]);
  useEffect(() => {
    if (!data) return;
    let disposed = false;
    const map = workflow.plan.multiElementMap ?? {};
    const initialCheck = (
      Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
    )
      .map(record)
      .find((stage) => stage.name === "check");
    const checkOutputs = Array.isArray(initialCheck?.outputs)
      ? initialCheck.outputs.map(record)
      : [];
    const beforeAlterations = Number(
      checkOutputs.find((output) => output.key === "alterations")?.resourceId,
    );
    const groups = [
      { key: "checks", visibleKey: "checks", ids: map.checks ?? [] },
      {
        key: "alterations-before",
        visibleKey: "alterations",
        ids: beforeAlterations > 0 ? [beforeAlterations] : [],
      },
      {
        key: "alterations-after",
        visibleKey: "alterations",
        ids: map.alterations ? [map.alterations] : [],
      },
    ].filter(
      (group) => visible.includes(group.visibleKey) && group.ids.length > 0,
    );
    setOptionalLoading(groups.map((group) => group.key));
    void Promise.allSettled(
      groups.map(async ({ key, ids }) => {
        const cacheKey = `${workflow.id}:${key}:${ids.join(",")}`;
        if (!optionalRequests.current.has(cacheKey)) {
          const query = Promise.all(
            ids.map((id) => {
              if (!resourceRequests.current.has(id))
                resourceRequests.current.set(
                  id,
                  queryReviewMap(id, { mixed: true, allowEmpty: true }).catch(
                    (reason: unknown) => {
                      resourceRequests.current.delete(id);
                      throw reason;
                    },
                  ),
                );
              return resourceRequests.current.get(id)!;
            }),
          ).then((items) => ({
            type: "FeatureCollection" as const,
            features: items.flatMap((item) => item.features),
          }));
          optionalRequests.current.set(cacheKey, query);
        }
        const features = await optionalRequests.current.get(cacheKey)!;
        return { key, features };
      }),
    ).then((results) => {
      if (disposed) return;
      for (const [index, result] of results.entries()) {
        const key = groups[index]!.key;
        if (result.status === "fulfilled") {
          setOptionalData((current) => ({
            ...current,
            [key]: result.value.features,
          }));
          setOptionalErrors((current) => {
            const next = { ...current };
            delete next[key];
            return next;
          });
        } else {
          const reason: unknown = result.reason;
          setOptionalErrors((current) => ({
            ...current,
            [key]: reason instanceof Error ? reason.message : "图层读取失败",
          }));
          optionalRequests.current.delete(
            `${workflow.id}:${key}:${groups[index]!.ids.join(",")}`,
          );
        }
      }
      setOptionalLoading([]);
    });
    return () => {
      disposed = true;
    };
  }, [data, visible, workflow.id, workflow.plan]);
  const issues = optionalData.checks ?? data?.issues ?? empty;
  const overlayKey = visible
    .filter(
      (key) =>
        !["checks", "alterations"].includes(key) ||
        Boolean(
          key === "alterations"
            ? optionalData["alterations-before"] ||
                optionalData["alterations-after"]
            : optionalData[key],
        ),
    )
    .join("|");
  const overlays = useMemo(
    () =>
      data?.overlays
        .filter((item) => overlayKey.split("|").includes(item.key))
        .map((item) =>
          item.key === "alterations"
            ? {
                ...item,
                before: optionalData["alterations-before"],
                after: optionalData["alterations-after"],
              }
            : optionalData[item.key]
              ? {
                  ...item,
                  before: optionalData[item.key],
                  after: optionalData[item.key],
                }
              : item,
        ) ?? [],
    [data, overlayKey, optionalData],
  );
  const inspect = (feature: Feature) => {
    setSelected(feature);
    setFocus(reviewBounds({ type: "FeatureCollection", features: [feature] }));
  };
  const suggestion = workflow.modificationReview?.suggestions.find(
    (item) =>
      selected &&
      (item.id === selected.properties.suggestion_id ||
        item.id === selected.properties.issue_id ||
        (item.featureId === String(selected.properties.feature_id) &&
          item.ruleId === selected.properties.rule_id)),
  );
  return (
    <main className="geology-review-workspace multi-element-workspace">
      <header className="geology-review-workspace-header">
        <div>
          <span className="geology-review-eyebrow">地理工作台演示案例</span>
          <h1>海德乌拉地质综合推理</h1>
          <p>
            同一视角对照当次真实图层，点击对象查看测量、规则与实际处理；A/B表示优先核查证据组合等级。
          </p>
        </div>
        <div className="geology-review-workspace-actions">
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate("/agent/workbench")}
          >
            返回对话
          </Button>
          <Button icon={<ReloadOutlined />} onClick={onReload}>
            刷新结果
          </Button>
          <Button
            icon={<AimOutlined />}
            disabled={!selected}
            onClick={() => selected && inspect(selected)}
          >
            定位当前对象
          </Button>
        </div>
      </header>
      <Alert
        showIcon
        type="info"
        title="演示案例"
        description="岩性与构造为模拟识别输入（演示）；矿物为遥感矿物识别结果（演示案例）。草拟规则仅在本案例试用，待裁定与未批准对象保留。"
      />
      {error && <Alert type="error" showIcon title={error} />}
      {loading && (
        <div className="geology-review-workspace-loading">
          <Spin />
          正在读取本次实际任务图层…
        </div>
      )}
      {data && (
        <>
          <div className="multi-element-map-controls">
            <strong>联动图层</strong>
            <Checkbox.Group
              options={data.overlays.map((item) => ({
                value: item.key,
                label: item.label,
              }))}
              value={visible}
              onChange={(items) => setVisible(items.map(String))}
            />
            {optionalLoading.length > 0 && (
              <span role="status">正在读取所选图层…</span>
            )}
          </div>
          {Object.entries(optionalErrors)
            .filter(([key]) =>
              visible.includes(
                key.startsWith("alterations-") ? "alterations" : key,
              ),
            )
            .map(([key, reason]) => (
              <Alert
                key={key}
                type="warning"
                showIcon
                title={`${key === "checks" ? "待核查项" : "矿物与处理状态"}未能加载`}
                description={`${reason}。基础双图仍可查看；取消勾选后重新勾选可重试。`}
              />
            ))}
          <div className="geology-review-workspace-body">
            <section className="geology-review-map-area">
              <GeologyReviewMaps
                before={data.before}
                after={data.after}
                differences={data.differences}
                overlays={overlays}
                bounds={focus}
                onSelect={(index) => {
                  const feature = data.differences.features[index];
                  if (feature) inspect(feature);
                }}
                onInspect={inspect}
                accessToken={bootstrap.map.mapboxAccessToken}
                beforeLabel="本次检查采用的岩性与构造"
                afterLabel="获批修正版本及综合分析"
                previewLabel="当前输入与检查范围，尚无修正版本"
                compactLegend
              />
            </section>
            <aside className="geology-review-map-inspector">
              <Tag color="blue">真实任务图层</Tag>
              <h2>对象与依据</h2>
              <p>
                变化高亮来自实际差异；批准前显示建议范围。实心点为几何交汇，空心点为推测交汇；灰色虚线为本轮不参与的构造，原线仍保留。
              </p>
              <details className="multi-element-map-objects">
                <summary>
                  定位检查记录 / {issues.features.length} 条规则命中
                </summary>
                {!optionalData.checks && (
                  <p>
                    当前列出模型已引用的建议，勾选“待核查项”读取完整检查图层。
                  </p>
                )}
                <div className="geology-review-change-list">
                  {issues.features.slice(0, 100).map((feature) => (
                    <button
                      key={String(
                        feature.properties.issue_id ??
                          feature.id ??
                          `${feature.properties.feature_id}:${feature.properties.rule_id}`,
                      )}
                      onClick={() => inspect(feature)}
                    >
                      <span>
                        {String(feature.properties.rule_id ?? "检查对象")} /{" "}
                        {String(
                          feature.properties.name ??
                            feature.properties.element ??
                            "实际疑点",
                        )}
                      </span>
                      <small>{readable(feature.properties.status ?? "")}</small>
                    </button>
                  ))}
                </div>
                {issues.features.length > 100 && (
                  <p>此处列出前100个对象，其他对象可直接点击地图查看。</p>
                )}
              </details>
              {selected ? (
                <section className="geology-review-selected-change">
                  <dl>
                    {Object.entries(selected.properties)
                      .filter(([key]) => key in displayFields)
                      .map(([key, value]) => (
                        <div key={key}>
                          <dt>{displayFields[key]}</dt>
                          <dd>
                            {key === "measurements_json"
                              ? formatMultiElementObservation(value)
                              : readable(value)}
                          </dd>
                        </div>
                      ))}
                  </dl>
                  {suggestion && (
                    <>
                      {workflow.modificationReview?.approvedSuggestionIds.includes(
                        suggestion.id,
                      ) && (
                        <p>
                          <strong>用户获批操作：</strong>
                          {readable(suggestion.action)}
                        </p>
                      )}
                      <MultiElementEvidence suggestion={suggestion} />
                    </>
                  )}
                </section>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="点击疑点、交汇点或远景区查看依据"
                />
              )}
            </aside>
          </div>
          {workflow.status === "succeeded" && (
            <div className="geology-review-workspace-report">
              <WorkflowReportFile
                workflowId={workflow.id}
                projectId={workflow.projectId}
              />
            </div>
          )}
        </>
      )}
    </main>
  );
}
