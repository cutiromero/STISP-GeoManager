import { LeftOutlined, ReloadOutlined, RightOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  InputNumber,
  Select,
  Segmented,
  Spin,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { modificationAction } from "../agent/modificationPresentation";
import { Link, useSearchParams } from "react-router-dom";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import { geologyReviewOutcome } from "../agent/geologyReviewOutcome";
import GeologyReviewMaps from "./LocalGeologyReviewMaps";
import MultiElementTourCard from "./MultiElementTourCard";
import { usesCleanGeologyResults } from "./workflowOutputMaps";
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
  canLoad,
  comparisonVisible,
  registerLayer,
  onVisibilityChange,
  onSuggestionChange,
  onLayerDisplay,
  selectedObject,
  onSwitchProject,
  onFamilyChange,
}: {
  workflowId: string;
  projectId: string;
  projectTagId: string | null;
  suggestionId: string | null;
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
  onFamilyChange?: (value: boolean) => void;
  selectedObject?: Record<string, unknown> | null;
}) {
  const [params, setParams] = useSearchParams();
  const side = params.get("compareSide") === "before" ? "before" : "after";
  const scope = params.get("compareScope") === "all" ? "all" : "current";
  const [data, setData] = useState<WorkbenchReviewComparison | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [overlaysLoading, setOverlaysLoading] = useState(false);
  const [showOverlays, setShowOverlays] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState(0);
  const [showChanges, setShowChanges] = useState(false);
  const cleanFamily =
    data?.workflow.workflowType === "geology_generic" ||
    data?.workflow.workflowType === "geology_multi_element_reasoning";
  const changesVisible = showChanges || !cleanFamily;
  useEffect(() => {
    onFamilyChange?.(cleanFamily);
    return () => onFamilyChange?.(false);
  }, [cleanFamily, onFamilyChange]);
  const latest = useRef({ registerLayer, onLayerDisplay });
  latest.current = { registerLayer, onLayerDisplay };
  useEffect(() => {
    let disposed = false;
    setData(null);
    setError("");
    setLoading(true);
    setRecordsLoading(true);
    setShowOverlays(false);
    setOverlaysLoading(false);
    if (!canLoad) {
      setError("当前账号没有查询和加载检查成果图层的权限");
      setLoading(false);
      setRecordsLoading(false);
      return;
    }
    void loadWorkbenchReviewComparison({
      workflowId,
      projectId,
      projectTagId,
      registerLayer: (profile, result, placement) =>
        latest.current.registerLayer(profile, result, placement),
      isCurrent: () => !disposed,
      deferOverlays: true,
      onPrimary: (value) => {
        if (!disposed) {
          setData(value);
          setLoading(false);
        }
      },
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
        if (!disposed) {
          setLoading(false);
          setRecordsLoading(false);
        }
      });
    return () => {
      disposed = true;
    };
  }, [workflowId, projectId, projectTagId, canLoad, revision]);
  const selectedElement = data?.tour?.[selected]?.suggestion.element;
  const selectedOverlay =
    selectedElement === "structure"
      ? "faults"
      : selectedElement === "alteration"
        ? "alterations"
        : undefined;
  const overlayRequest = showOverlays ? undefined : selectedOverlay;
  const overlaysReady = showOverlays
    ? ["faults", "alterations", "intersections", "prospects"].every((key) =>
        data?.overlays?.some((overlay) => overlay.key === key),
      )
    : Boolean(
        data?.overlays?.some((overlay) => overlay.key === selectedOverlay),
      );
  useEffect(() => {
    if (
      (!showOverlays && !selectedOverlay) ||
      !data?.loadOverlays ||
      overlaysReady
    ) {
      setOverlaysLoading(false);
      return;
    }
    let disposed = false;
    setOverlaysLoading(true);
    void data
      .loadOverlays(overlayRequest)
      .then((overlays) => {
        if (!disposed) {
          setOverlaysLoading(false);
          setData(
            (current) =>
              current && {
                ...current,
                overlays: [
                  ...(current.overlays ?? []).filter(
                    (existing) =>
                      !overlays.some((item) => item.key === existing.key),
                  ),
                  ...overlays,
                ],
              },
          );
        }
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(
            reason instanceof Error
              ? reason.message
              : "辅助图层读取失败，请重新勾选重试",
          );
          setShowOverlays(false);
        }
      })
      .finally(() => {
        if (!disposed) setOverlaysLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [
    showOverlays,
    selectedOverlay,
    overlayRequest,
    overlaysReady,
    data?.loadOverlays,
  ]);
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
  }, [data?.differences, suggestionId]);
  useEffect(() => {
    if (!data) return;
    const feature = data.differences.features[selected],
      current = feature ? featureCollection([feature]) : null;
    latest.current.onLayerDisplay?.(
      side,
      changesVisible
        ? scope === "all"
          ? data.differences
          : (current ?? data.differences)
        : featureCollection([]),
      changesVisible ? current : null,
    );
  }, [data, selected, side, scope, comparisonVisible, changesVisible]);
  const updateSetting = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };
  const features = data?.differences.features ?? [],
    current = features[selected],
    properties = current?.properties ?? {};
  const groups = useMemo(() => {
    if (!cleanFamily) return [];
    const result = new Map<
      string,
      { key: string; title: string; reason: string; indices: number[] }
    >();
    features.forEach((feature, index) => {
      const suggestion = data?.tour?.[index]?.suggestion;
      const props = feature.properties;
      const element = suggestion?.element ?? props.element ?? props.kind;
      const rule = suggestion?.ruleId ?? props.rule_id ?? "检查";
      const action =
        suggestion?.action ??
        props.action ??
        props.suggested_action ??
        props.kind;
      const key = JSON.stringify([element, rule, action]);
      const group = result.get(key) ?? {
        key,
        title: `${({ lithology: "岩性", structure: "构造", alteration: "蚀变" } as Record<string, string>)[String(element)] ?? "地质对象"} / ${rule} / ${modificationAction({ action: String(action), suggestedState: String(action) })}`,
        reason:
          suggestion?.reason ??
          String(props.reason ?? "按本组知识规则核对实际修改"),
        indices: [],
      };
      group.indices.push(index);
      result.set(key, group);
    });
    return [...result.values()];
  }, [features, data?.tour, cleanFamily]);
  const group = groups.find((item) => item.indices.includes(selected));
  const groupPosition = group?.indices.indexOf(selected) ?? 0;
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
  const labels = tour
    ? tourLabels(
        tour,
        tourBefore,
        tourAfter,
        Boolean(selectedOverlay) &&
          !data?.overlays?.some((item) => item.key === selectedOverlay),
      )
    : null;
  const outcome = geologyReviewOutcome(data?.workflow);
  const focus = current
    ? reviewBounds(
        featureCollection([
          current,
          ...(tourBefore ? [tourBefore] : []),
          ...(tourAfter ? [tourAfter] : []),
        ]),
      )
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
    scope === "all" && !cleanFamily
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
  const focusSpotlight = useMemo(
    () =>
      spotlight && {
        ...spotlight,
        outlineOnly: cleanFamily,
        dimBackground: !cleanFamily,
      },
    [
      spotlight?.before.features[0],
      spotlight?.after.features[0],
      spotlight?.beforeLabel,
      spotlight?.afterLabel,
      cleanFamily,
    ],
  );
  const mapBounds = useMemo(() => focus, [focus?.join(",")]);
  const mapDifferences = useMemo(
    () =>
      !changesVisible
        ? featureCollection([])
        : scope === "current" && current
          ? featureCollection([current])
          : (data?.differences ?? featureCollection([])),
    [changesVisible, scope, current, data?.differences],
  );
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
      className={`geology-workbench-compare ${comparisonVisible ? "is-comparing" : "is-single"} ${cleanFamily ? "is-clean" : ""}`}
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
        {cleanFamily && (
          <Checkbox
            checked={showChanges}
            onChange={(event) => setShowChanges(event.target.checked)}
          >
            修正记录 / 实际修改范围
          </Checkbox>
        )}
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
            {data.loadOverlays && (
              <Checkbox
                checked={showOverlays}
                onChange={(event) => setShowOverlays(event.target.checked)}
              >
                构造 / 蚀变等辅助图层{overlaysLoading ? "（加载中…）" : ""}
              </Checkbox>
            )}
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
            <small>
              {cleanFamily && !changesVisible
                ? "修正后仅显示干净成果；勾选修正记录可查看实际修改范围。"
                : "橙色表示实际修改范围；成果图层保留正常单元配色。"}
            </small>
          </div>
          {comparisonVisible && (
            <div className="geology-workbench-compare-maps">
              <GeologyReviewMaps
                before={data.before}
                after={data.after}
                differences={mapDifferences}
                bounds={mapBounds}
                onSelect={(index) =>
                  scope === "current" ? select(selected) : select(index)
                }
                beforeLabel={data.beforeName}
                afterLabel={data.afterName}
                inspectionOnly={Boolean(outcome)}
                previewLabel={outcome ? "检查后原图，保持不变" : data.afterName}
                compactLegend
                spotlight={focusSpotlight}
                overlays={showOverlays ? data.overlays : undefined}
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
                {group && (
                  <div className="geology-workbench-group-navigation">
                    <Select
                      aria-label="修改分组"
                      value={group.key}
                      options={groups.map((item) => ({
                        value: item.key,
                        label: `${item.title}（${item.indices.length} 处）`,
                      }))}
                      onChange={(key) =>
                        select(
                          groups.find((item) => item.key === key)!.indices[0]!,
                        )
                      }
                    />
                    <label>
                      跳到组内第{" "}
                      <InputNumber
                        aria-label="组内位置"
                        min={1}
                        max={group.indices.length}
                        value={groupPosition + 1}
                        precision={0}
                        onChange={(position) => {
                          const index = group.indices[Number(position) - 1];
                          if (position !== null && index !== undefined)
                            select(index);
                        }}
                      />{" "}
                      处 / {group.indices.length} 处
                    </label>
                    <p>{group.reason}</p>
                  </div>
                )}
                <nav aria-label="切换修改位置">
                  <Button
                    aria-label="上一处修改"
                    size="small"
                    icon={<LeftOutlined />}
                    disabled={group ? groupPosition === 0 : selected === 0}
                    onClick={() =>
                      select(group?.indices[groupPosition - 1] ?? selected - 1)
                    }
                  >
                    上一处
                  </Button>
                  <strong>
                    第 {selected + 1} 处，共 {features.length} 处
                  </strong>
                  <Button
                    aria-label="下一处修改"
                    size="small"
                    icon={<RightOutlined />}
                    disabled={
                      group
                        ? groupPosition >= group.indices.length - 1
                        : selected >= features.length - 1
                    }
                    onClick={() =>
                      select(group?.indices[groupPosition + 1] ?? selected + 1)
                    }
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
                    cleanResults={usesCleanGeologyResults(data.workflow)}
                    loading={
                      Boolean(selectedOverlay) &&
                      !data.overlays?.some(
                        (item) => item.key === selectedOverlay,
                      )
                    }
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
                {recordsLoading
                  ? "正在加载修改记录…"
                  : error
                    ? "修改记录未能完整读取，请刷新成果重试。"
                    : outcome
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
