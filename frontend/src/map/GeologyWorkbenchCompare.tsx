import { LeftOutlined, ReloadOutlined, RightOutlined } from "@ant-design/icons";
import { Alert, Button, Segmented, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import { geologyReviewOutcome } from "../agent/geologyReviewOutcome";
import GeologyReviewMaps from "./GeologyReviewMaps";
import MultiElementTourCard from "./MultiElementTourCard";
import {
  featureCollection,
  tourAlgorithm,
  tourFeature,
  tourLabels,
} from "./multiElementTour";
import {
  record,
  reviewBounds,
  reviewSuggestionIndex,
} from "./geologyReviewData";
import {
  loadWorkbenchReviewComparison,
  type RegisterReviewLayer,
  type WorkbenchReviewComparison,
} from "./geologyWorkbenchCompareData";
import "./geology-review-workspace.css";
import "./multi-element-tour.css";
import "./geology-workbench-compare.css";

export default function GeologyWorkbenchCompare({
  workflowId,
  projectId,
  projectTagId,
  suggestionId,
  accessToken,
  canLoad,
  comparisonVisible,
  registerLayer,
  onVisibilityChange,
  onSuggestionChange,
  onLayerDisplay,
  selectedObject,
  onSwitchProject,
}: {
  workflowId: string;
  projectId: string;
  projectTagId: string | null;
  suggestionId: string | null;
  accessToken: string;
  canLoad: boolean;
  comparisonVisible: boolean;
  registerLayer: RegisterReviewLayer;
  onVisibilityChange: (visible: boolean) => void;
  onSuggestionChange: (id: string | null) => void;
  onLayerDisplay?: (
    side: "before" | "after",
    changes: GeoJsonFeatureCollection,
    current: GeoJsonFeatureCollection | null,
  ) => void;
  onSwitchProject?: () => void;
  selectedObject?: Record<string, unknown> | null;
}) {
  const [params, setParams] = useSearchParams();
  const side = params.get("compareSide") === "before" ? "before" : "after";
  const scope = params.get("compareScope") === "all" ? "all" : "current";
  const [data, setData] = useState<WorkbenchReviewComparison | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState(0);
  const latest = useRef({ registerLayer, onLayerDisplay });
  latest.current = { registerLayer, onLayerDisplay };
  useEffect(() => {
    let disposed = false;
    setData(null);
    setError("");
    setLoading(true);
    if (!canLoad) {
      setError("当前账号没有查询和加载检查成果图层的权限");
      setLoading(false);
      return;
    }
    void loadWorkbenchReviewComparison({
      workflowId,
      projectId,
      projectTagId,
      registerLayer: (profile, result, placement) =>
        latest.current.registerLayer(profile, result, placement),
      isCurrent: () => !disposed,
    })
      .then((value) => {
        if (!disposed) setData(value);
      })
      .catch((reason: unknown) => {
        if (!disposed)
          setError(
            reason instanceof Error ? reason.message : "检查成果读取失败",
          );
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [workflowId, projectId, projectTagId, canLoad, revision]);
  useEffect(() => {
    if (data)
      setSelected(
        Math.max(
          0,
          data.tour
            ? data.tour.findIndex((item) => item.key === suggestionId)
            : reviewSuggestionIndex(
                data.workflow,
                data.differences,
                suggestionId,
              ),
        ),
      );
  }, [data, suggestionId]);
  useEffect(() => {
    if (!data) return;
    const feature = data.differences.features[selected],
      current = feature ? featureCollection([feature]) : null;
    latest.current.onLayerDisplay?.(
      side,
      scope === "all" ? data.differences : (current ?? data.differences),
      current,
    );
  }, [data, selected, side, scope, comparisonVisible]);
  const updateSetting = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };
  const features = data?.differences.features ?? [],
    current = features[selected],
    properties = current?.properties ?? {};
  const tour = data?.tour?.[selected],
    element = tour?.suggestion.element;
  const overlay = data?.overlays?.find(
    (item) => item.key === (element === "structure" ? "faults" : "alterations"),
  );
  const tourBefore =
    tour &&
    tourFeature(element === "lithology" ? data?.before : overlay?.before, tour);
  const tourAfter =
    tour &&
    tourFeature(element === "lithology" ? data?.after : overlay?.after, tour);
  const labels = tour ? tourLabels(tour, tourBefore, tourAfter) : null;
  const outcome = geologyReviewOutcome(data?.workflow);
  const focus = current
    ? reviewBounds(featureCollection([current]))
    : data
      ? reviewBounds(data.before)
      : null;
  const oldSpotlight =
    current && data
      ? {
          before: featureCollection(
            properties.kind === "fill_gap"
              ? [
                  {
                    ...current,
                    properties: { ...properties, _review_outlineOnly: true },
                  },
                ]
              : data.before.features.filter(
                  (feature) =>
                    String(feature.properties.feature_id ?? feature.id) ===
                    String(properties.feature_id),
                ),
          ),
          after: featureCollection(
            properties.kind === "fill_gap"
              ? [
                  {
                    ...current,
                    properties: {
                      ...properties,
                      _review_outlineOnly: !data.after,
                    },
                  },
                ]
              : (data.after ?? data.before).features.filter(
                  (feature) =>
                    String(feature.properties.feature_id ?? feature.id) ===
                    String(properties.feature_id),
                ),
          ),
          beforeLabel: String(
            properties.current_label || properties.old_value || "未分类",
          ),
          afterLabel: String(
            properties.suggested_label || properties.new_value || "待核对",
          ),
        }
      : null;
  const spotlight =
    scope === "all"
      ? null
      : tour && labels
        ? {
            before: featureCollection([tourBefore ?? tour.feature]),
            after: featureCollection([
              tourAfter ?? {
                ...tour.feature,
                properties: { ...tour.feature.properties, state: tour.action },
              },
            ]),
            beforeLabel: labels.before,
            afterLabel: labels.after,
          }
        : oldSpotlight;
  const select = (index: number) => {
    setSelected(index);
    const feature = features[index];
    const suggestion = data?.workflow.modificationReview?.suggestions.find(
      (item) =>
        item.id === feature?.properties.suggestion_id ||
        (item.featureId === String(feature?.properties.feature_id) &&
          item.kind === feature?.properties.kind),
    );
    onSuggestionChange(data?.tour?.[index]?.key ?? suggestion?.id ?? null);
  };
  const selectRef = useRef(select);
  selectRef.current = select;
  useEffect(() => {
    const id = selectedObject?.feature_id ?? selectedObject?.line_id;
    if (!data || id === undefined || id === null) return;
    const index = data.differences.features.findIndex(
      (feature) =>
        String(feature.properties.feature_id) === String(id) &&
        (!selectedObject?.issue_id ||
          feature.properties.issue_id === selectedObject.issue_id) &&
        (!selectedObject?.rule_id ||
          feature.properties.rule_id === selectedObject.rule_id),
    );
    if (index >= 0) selectRef.current(index);
  }, [data, selectedObject]);
  const currentSuggestion = data?.workflow.modificationReview?.suggestions.find(
    (item) =>
      item.id === suggestionId ||
      (item.featureId === String(properties.feature_id) &&
        item.kind === properties.kind),
  );
  const correctionStage = (
    Array.isArray(data?.workflow.plan.stages) ? data.workflow.plan.stages : []
  )
    .map(record)
    .find((stage) => stage.identifier === "geology-map-correct");
  const correctionAlgorithm = record(
    record(data?.workflow.plan.algorithms)[String(correctionStage?.identifier)],
  );
  return (
    <section
      className={`geology-workbench-compare ${comparisonVisible ? "is-comparing" : "is-single"}`}
      aria-label="地理工作台地质成果对比"
    >
      <header className="geology-workbench-compare-toolbar">
        <div>
          <strong>
            {!data?.tour
              ? "地质成果检查与修正"
              : data.workflow.workflowType === "geology_generic"
                ? "地质综合推理对比"
                : "海德乌拉综合推理对比"}
          </strong>
          <small>
            {comparisonVisible
              ? "同一视角核对修改，单图模式可管理图层与查询数据"
              : "成果已加载到图层，可查看属性、空间查询和导出"}
          </small>
        </div>
        <Segmented
          aria-label="地图显示方式"
          value={comparisonVisible ? "compare" : "single"}
          options={[
            { label: "单图", value: "single" },
            { label: "前后对比", value: "compare" },
          ]}
          onChange={(value) => onVisibilityChange(value === "compare")}
        />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => setRevision((value) => value + 1)}
        >
          刷新成果
        </Button>
        <Link
          to={`/map?geologyReview=${encodeURIComponent(workflowId)}&projectTagId=${projectId}${suggestionId ? `&suggestion=${encodeURIComponent(suggestionId)}` : ""}`}
        >
          独立对比页
        </Link>
      </header>
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            onSwitchProject && (
              <Button onClick={onSwitchProject}>切换项目</Button>
            )
          }
        />
      )}
      {loading && (
        <div className="geology-workbench-compare-loading">
          <Spin />
          正在读取真实图件与检查记录…
        </div>
      )}
      {data && (
        <>
          <div className="geology-workbench-compare-options">
            {!comparisonVisible && (
              <Segmented
                aria-label="单图成果版本"
                value={side}
                options={[
                  { label: "改前", value: "before" },
                  { label: "改后", value: "after" },
                ]}
                onChange={(value) =>
                  updateSetting("compareSide", String(value))
                }
              />
            )}
            <Segmented
              aria-label="修改显示范围"
              value={scope}
              options={[
                { label: "当前修改", value: "current" },
                { label: "全部修改", value: "all" },
              ]}
              onChange={(value) => updateSetting("compareScope", String(value))}
            />
            <small>橙色包含边界、类别、代号、分析状态与权重的实际变化</small>
          </div>
          {comparisonVisible && (
            <div className="geology-workbench-compare-maps">
              <GeologyReviewMaps
                before={data.before}
                after={data.after}
                differences={
                  scope === "current" && current
                    ? featureCollection([current])
                    : data.differences
                }
                bounds={focus}
                onSelect={(index) =>
                  scope === "current" ? select(selected) : select(index)
                }
                accessToken={accessToken}
                beforeLabel={data.beforeName}
                afterLabel={data.afterName}
                inspectionOnly={Boolean(outcome)}
                previewLabel={outcome ? "检查后原图，保持不变" : data.afterName}
                compactLegend
                spotlight={spotlight}
                overlays={data.overlays}
                onInspect={(feature) => {
                  const index = features.findIndex(
                    (item) =>
                      String(item.properties.feature_id) ===
                      String(
                        feature.properties.feature_id ??
                          feature.properties.line_id,
                      ),
                  );
                  if (index >= 0) select(index);
                }}
              />
            </div>
          )}
          <div className="geology-workbench-compare-detail">
            {current ? (
              <>
                <nav aria-label="切换修改位置">
                  <Button
                    size="small"
                    icon={<LeftOutlined />}
                    disabled={selected === 0}
                    onClick={() => select(selected - 1)}
                  >
                    上一处
                  </Button>
                  <strong>
                    第 {selected + 1} 处，共 {features.length} 处
                  </strong>
                  <Button
                    size="small"
                    icon={<RightOutlined />}
                    disabled={selected >= features.length - 1}
                    onClick={() => select(selected + 1)}
                  >
                    下一处
                  </Button>
                </nav>
                {tour ? (
                  <MultiElementTourCard
                    change={tour}
                    before={tourBefore}
                    after={tourAfter}
                    algorithm={tourAlgorithm(data.workflow)}
                  />
                ) : (
                  <>
                    <p>
                      <strong>{data.after ? "实际变化" : "建议修改"}：</strong>
                      {String(
                        properties.current_label ||
                          properties.old_value ||
                          "未分类",
                      )}{" "}
                      →{" "}
                      {String(
                        properties.suggested_label ||
                          properties.new_value ||
                          "待核对",
                      )}
                    </p>
                    <p>
                      <strong>原因与依据：</strong>
                      {String(
                        properties.verified_reason ||
                          properties.reason ||
                          "详见检查报告",
                      )}
                    </p>
                    <details>
                      <summary>知识来源与实际算法</summary>
                      {(currentSuggestion?.ruleRefs ?? []).map((ref) => (
                        <p key={ref.id}>
                          {ref.title}：{ref.source}
                        </p>
                      ))}
                      <p>
                        {String(
                          correctionAlgorithm.name ??
                            correctionStage?.identifier ??
                            "本轮检查算法",
                        )}{" "}
                        {String(
                          record(correctionAlgorithm.manifest).version ?? "",
                        )}
                      </p>
                    </details>
                  </>
                )}
              </>
            ) : (
              <p>
                {outcome
                  ? "本轮保留原图；检查结论与待核查事项见报告。"
                  : "当前尚无可显示的修改范围，请刷新成果或返回对话继续。"}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
