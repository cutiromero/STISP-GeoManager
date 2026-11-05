import {
  AimOutlined,
  ArrowLeftOutlined,
  LeftOutlined,
  RightOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Checkbox, Empty, Spin, Tag } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
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
import MultiElementTourCard from "./MultiElementTourCard";
import MultiElementOutcome from "./MultiElementOutcome";
import MultiElementChapters, {
  type StoryChapter,
} from "./MultiElementChapters";
import WorkflowValidationPanel from "./WorkflowValidationPanel";
import {
  actualTourChanges,
  featureCollection,
  prospectChanges,
  tourAlgorithm,
  tourFeature,
  tourLabels,
} from "./multiElementTour";
import "./multi-element-tour.css";
import {
  queryWorkflowVectors,
  usesCleanGeologyResults,
} from "./workflowOutputMaps";

const empty: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
function savedStory(id: string) {
  try {
    return record(
      JSON.parse(sessionStorage.getItem(`geology-story:${id}`) ?? "{}"),
    );
  } catch {
    return {};
  }
}
type Feature = GeoJsonFeatureCollection["features"][number];
type MultiMaps = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
  overlays: ReviewOverlay[];
  issues: GeoJsonFeatureCollection;
  beforeProspects: GeoJsonFeatureCollection;
  afterProspects: GeoJsonFeatureCollection;
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
  exclude: "剔除（从修正后成果删除）",
  remove: "剔除（从修正后成果删除）",
  set_code: "改代号",
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
  onPage,
}: {
  workflow: AgentWorkflow;
  suggestionId: string | null;
  onReload: () => void;
  onPage?: (offset: number) => Promise<void>;
}) {
  const navigate = useNavigate();
  const [chapter, setChapter] = useState<StoryChapter>(() => {
    const value = savedStory(workflow.id).chapter;
    return [
      "all",
      "lithology",
      "structure",
      "alteration",
      "investigation",
    ].includes(String(value))
      ? (value as StoryChapter)
      : "all";
  });
  const [data, setData] = useState<MultiMaps>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pageLoading, setPageLoading] = useState(false);
  const changePage = async (offset: number) => {
    if (!onPage || pageLoading) return;
    setPageLoading(true);
    setError("");
    try {
      await onPage(offset);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "修改详情读取失败");
    } finally {
      setPageLoading(false);
    }
  };
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [slow, setSlow] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const retryLoad = () => {
    resourceRequests.current.clear();
    setAttempt((value) => value + 1);
  };
  const [focus, setFocus] = useState<[number, number, number, number] | null>(
    null,
  );
  const [selected, setSelected] = useState<Feature>();
  const [tourKey, setTourKey] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"tour" | "overview" | "outcome">(
    "overview",
  );
  const [outcomeGrade, setOutcomeGrade] = useState<string | null>(null);
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
  const [visible, setVisible] = useState<string[]>(() => {
    const value = savedStory(workflow.id).visible;
    return Array.isArray(value)
      ? value.filter(
          (key): key is string =>
            typeof key === "string" &&
            [
              "checks",
              "faults",
              "intersections",
              "prospects",
              "alterations",
              "changes",
            ].includes(key),
        )
      : ["faults", "intersections", "prospects"];
  });
  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError("");
    setData(undefined);
    setProgress({ done: 0, total: 0 });
    setSlow(false);
    // A long read offers a retry instead of an open-ended wait.
    const slowTimer = window.setTimeout(() => {
      if (!disposed) setSlow(true);
    }, 45_000);
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
      const counted = <T,>(work: Promise<T>) => {
        setProgress((value) => ({ ...value, total: value.total + 1 }));
        return work.then((result) => {
          if (!disposed)
            setProgress((value) => ({ ...value, done: value.done + 1 }));
          return result;
        });
      };
      const query = (id: number | undefined) => {
        if (!id) return Promise.resolve(empty);
        if (!requests.has(id))
          requests.set(
            id,
            queryReviewMap(id, {
              mixed: true,
              allowEmpty: true,
              loadStyle: true,
              displayGeometry: true,
            }).catch((reason: unknown) => {
              requests.delete(id);
              throw reason;
            }),
          );
        return requests.get(id)!;
      };
      const [
        before,
        after,
        faults,
        afterFaults,
        changes,
        beforeIntersections,
        intersections,
        beforeProspects,
        afterProspects,
      ] = await Promise.all([
        counted(query(beforeId)),
        map.after?.lithology
          ? counted(query(map.after.lithology))
          : Promise.resolve(null),
        counted(query(faultsId)),
        counted(
          query(
            map.after?.faults ??
              (usesCleanGeologyResults(workflow) && map.after
                ? undefined
                : faultsId),
          ),
        ),
        Promise.resolve(
          (workflow.plan.compareFeatures as
            | GeoJsonFeatureCollection
            | undefined) ?? empty,
        ),
        counted(
          map.beforeIntersections
            ? query(map.beforeIntersections)
            : queryWorkflowVectors(workflow, "relations", [
                "before_intersections",
              ]),
        ),
        counted(query(map.intersections)),
        counted(query(map.beforeProspects)),
        counted(query(map.afterProspects)),
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
          label: "有效蚀变",
          before: empty,
          after: empty,
          color: "#648e91",
        },
        {
          key: "intersections",
          label: "构造交汇",
          before: beforeIntersections,
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
      setData({
        before,
        after,
        differences,
        overlays,
        issues,
        beforeProspects,
        afterProspects,
      });
      const saved = savedStory(workflow.id);
      const requestedId =
        suggestionId ??
        (typeof saved.tourKey === "string" ? saved.tourKey : null);
      const suggestion = workflow.modificationReview?.suggestions.find(
        (item) => item.id === requestedId,
      );
      const requestedFeature = [
        ...differences.features,
        ...issues.features,
      ].find(
        (item) =>
          item.properties.suggestion_id === requestedId ||
          item.properties.issue_id === requestedId ||
          (suggestion &&
            String(item.properties.feature_id) === suggestion.featureId &&
            item.properties.rule_id === suggestion.ruleId),
      );
      const tourChanges = actualTourChanges(workflow, differences);
      const current =
        tourChanges.find((item) => item.key === requestedId) ??
        tourChanges.find(
          (item) =>
            saved.chapter === "all" ||
            item.suggestion.element === saved.chapter,
        ) ??
        tourChanges[0];
      const feature = requestedFeature ?? current?.feature;
      setTourKey(current?.key ?? null);
      const restoredOutcome =
        saved.viewMode === "outcome" &&
        !suggestionId &&
        map.beforeProspects &&
        map.afterProspects;
      setViewMode(
        restoredOutcome
          ? "outcome"
          : saved.viewMode === "overview" && !suggestionId
            ? "overview"
            : current && (!suggestionId || current.key === suggestionId)
              ? "tour"
              : "overview",
      );
      setSelected(feature);
      const restoredZones = restoredOutcome
        ? prospectChanges(beforeProspects, afterProspects)
        : null;
      setFocus(
        reviewBounds(
          restoredZones
            ? featureCollection([
                ...restoredZones.before.features,
                ...restoredZones.after.features,
              ])
            : saved.viewMode === "overview" && !suggestionId
              ? before
              : feature
                ? featureCollection([feature])
                : before,
        ),
      );
    };
    void load()
      .catch((reason: unknown) => {
        if (!disposed)
          setError(reason instanceof Error ? reason.message : "地图读取失败");
      })
      .finally(() => {
        window.clearTimeout(slowTimer);
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      window.clearTimeout(slowTimer);
    };
  }, [workflow, suggestionId, attempt]);
  const allTour = useMemo(
    () => (data ? actualTourChanges(workflow, data.differences) : []),
    [data, workflow],
  );
  const tour = useMemo(
    () =>
      allTour.filter(
        (item) =>
          chapter === "all" ||
          chapter === "investigation" ||
          item.suggestion.element === chapter,
      ),
    [allTour, chapter],
  );
  useEffect(() => {
    if (!data) return;
    try {
      sessionStorage.setItem(
        `geology-story:${workflow.id}`,
        JSON.stringify({ chapter, tourKey, viewMode, visible }),
      );
    } catch {
      /* storage availability does not prevent map use */
    }
  }, [data, workflow.id, chapter, tourKey, viewMode, visible]);
  const tourIndex = Math.max(
    0,
    tour.findIndex((item) => item.key === tourKey),
  );
  const currentTour = tour[tourIndex];
  const storyNeedsAlterations =
    viewMode === "tour" && currentTour?.suggestion.element === "alteration";
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
    const beforeAlterations =
      map.beforeAlterations ??
      Number(
        checkOutputs.find((output) => output.key === "alterations")?.resourceId,
      );
    const groups = [
      {
        key: "checks",
        visibleKey: "checks",
        ids: map.checks ?? [],
        stage: "check",
        outputs: ["lithology_issues", "fault_issues", "alteration_issues"],
      },
      {
        key: "alterations-before",
        visibleKey: "alterations",
        ids: beforeAlterations > 0 ? [beforeAlterations] : [],
        stage: "check",
        outputs: ["alterations"],
      },
      {
        key: "alterations-after",
        visibleKey: "alterations",
        ids: map.alterations ? [map.alterations] : [],
        stage: "apply",
        outputs: [
          usesCleanGeologyResults(workflow)
            ? "final_alterations"
            : "alterations",
        ],
      },
    ].filter(
      (group) =>
        (visible.includes(group.visibleKey) ||
          (group.visibleKey === "alterations" && storyNeedsAlterations)) &&
        (group.ids.length > 0 ||
          (Array.isArray(workflow.plan.stages) &&
            workflow.plan.stages
              .map(record)
              .some(
                (stage) =>
                  stage.name === group.stage && stage.status === "completed",
              ))),
    );
    setOptionalLoading(groups.map((group) => group.key));
    void Promise.allSettled(
      groups.map(async ({ key, ids, stage, outputs }) => {
        const cacheKey = `${workflow.id}:${key}:${ids.join(",")}`;
        if (!optionalRequests.current.has(cacheKey)) {
          const query = ids.length
            ? Promise.all(
                ids.map((id) => {
                  if (!resourceRequests.current.has(id))
                    resourceRequests.current.set(
                      id,
                      queryReviewMap(id, {
                        mixed: true,
                        allowEmpty: true,
                        displayGeometry: true,
                      }).catch((reason: unknown) => {
                        resourceRequests.current.delete(id);
                        throw reason;
                      }),
                    );
                  return resourceRequests.current.get(id)!;
                }),
              ).then((items) => ({
                type: "FeatureCollection" as const,
                features: items.flatMap((item) => item.features),
              }))
            : queryWorkflowVectors(workflow, stage, outputs);
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
  }, [data, visible, workflow.id, workflow.plan, storyNeedsAlterations]);
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
  const shownChecks = visible.includes("checks")
    ? optionalData.checks
    : undefined;
  const shownAlterationsBefore = visible.includes("alterations")
    ? optionalData["alterations-before"]
    : undefined;
  const shownAlterationsAfter = visible.includes("alterations")
    ? optionalData["alterations-after"]
    : undefined;
  const overlays = useMemo(
    () =>
      data?.overlays
        .filter((item) => overlayKey.split("|").includes(item.key))
        .map((item) =>
          item.key === "alterations"
            ? {
                ...item,
                before: shownAlterationsBefore,
                after: shownAlterationsAfter,
              }
            : item.key === "checks" && shownChecks
              ? {
                  ...item,
                  before: shownChecks,
                  after: shownChecks,
                }
              : item,
        ) ?? [],
    [
      data,
      overlayKey,
      shownChecks,
      shownAlterationsBefore,
      shownAlterationsAfter,
    ],
  );
  const inspect = (feature: Feature) => {
    setSelected(feature);
    setFocus(reviewBounds({ type: "FeatureCollection", features: [feature] }));
    const item = allTour.find(
      (item) =>
        item.feature === feature ||
        (String(feature.properties.feature_id ?? feature.properties.line_id) ===
          item.suggestion.featureId &&
          (!feature.properties.rule_id ||
            feature.properties.rule_id === item.suggestion.ruleId)),
    );
    if (item) {
      if (chapter !== "all" && chapter !== item.suggestion.element)
        setChapter(item.suggestion.element as StoryChapter);
      setTourKey(item.key);
      setViewMode("tour");
    } else if (viewMode !== "outcome" || !feature.properties.grade)
      setViewMode("overview");
  };
  const showTour = (index: number) => {
    const item = tour[index];
    if (item) {
      inspect(item.feature);
      if (chapter === "investigation") setChapter("all");
    }
  };
  const outcome = useMemo(
    () =>
      data &&
      workflow.plan.multiElementMap?.beforeProspects &&
      workflow.plan.multiElementMap.afterProspects
        ? prospectChanges(data.beforeProspects, data.afterProspects)
        : null,
    [data, workflow.plan],
  );
  const focusedOutcome = useMemo(
    () =>
      outcome
        ? {
            before: featureCollection(
              outcome.before.features.filter(
                (feature) =>
                  !outcomeGrade || feature.properties.grade === outcomeGrade,
              ),
            ),
            after: featureCollection(
              outcome.after.features.filter(
                (feature) =>
                  !outcomeGrade || feature.properties.grade === outcomeGrade,
              ),
            ),
          }
        : null,
    [outcome, outcomeGrade],
  );
  const showOutcome = (grade?: string) => {
    if (!outcome) return;
    setOutcomeGrade(grade ?? null);
    setViewMode("outcome");
    setChapter("investigation");
    setFocus(
      reviewBounds(
        featureCollection(
          [...outcome.before.features, ...outcome.after.features].filter(
            (feature) => !grade || feature.properties.grade === grade,
          ),
        ),
      ),
    );
  };
  const showChapter = (next: StoryChapter) => {
    setChapter(next);
    if (next === "investigation") {
      showOutcome();
      return;
    }
    const item = allTour.find(
      (change) => next === "all" || change.suggestion.element === next,
    );
    if (item) {
      setTourKey(item.key);
      setSelected(item.feature);
      setViewMode("tour");
      setFocus(reviewBounds(featureCollection([item.feature])));
    } else {
      setViewMode("overview");
      setFocus(data ? reviewBounds(data.before) : null);
    }
    setVisible(
      next === "structure"
        ? ["faults", "intersections"]
        : next === "alteration"
          ? ["alterations"]
          : next === "lithology"
            ? []
            : ["faults", "intersections", "prospects"],
    );
  };
  const tourBefore = currentTour
    ? tourFeature(
        currentTour.suggestion.element === "structure"
          ? data?.overlays.find((overlay) => overlay.key === "faults")?.before
          : currentTour.suggestion.element === "alteration"
            ? optionalData["alterations-before"]
            : data?.before,
        currentTour,
      )
    : undefined;
  const tourAfter = currentTour
    ? tourFeature(
        currentTour.suggestion.element === "structure"
          ? data?.overlays.find((overlay) => overlay.key === "faults")?.after
          : currentTour.suggestion.element === "alteration"
            ? optionalData["alterations-after"]
            : data?.after,
        currentTour,
      )
    : undefined;
  const spotlight = useMemo(() => {
    if (viewMode === "outcome" && focusedOutcome) return focusedOutcome;
    if (viewMode !== "tour" || !currentTour) return null;
    const currentLabels = tourLabels(currentTour, tourBefore, tourAfter);
    return {
      before: featureCollection([tourBefore ?? currentTour.feature]),
      after: featureCollection(
        usesCleanGeologyResults(workflow) && currentTour.action === "exclude"
          ? []
          : [
              tourAfter ?? {
                ...currentTour.feature,
                properties: {
                  ...currentTour.feature.properties,
                  state: currentTour.action,
                },
              },
            ],
      ),
      beforeLabel: currentLabels.before,
      afterLabel: currentLabels.after,
    };
  }, [viewMode, focusedOutcome, currentTour, tourBefore, tourAfter, workflow]);
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
          <span className="geology-review-eyebrow">
            {workflow.workflowType === "geology_generic"
              ? "地理工作台 · 本次资料"
              : "地理工作台演示案例"}
          </span>
          <h1>
            {workflow.workflowType === "geology_generic"
              ? "地质综合推理"
              : "海德乌拉地质综合推理"}
          </h1>
          <p>从一处修改看懂检查依据、实际处置与调查建议的变化。</p>
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
            onClick={() =>
              viewMode === "outcome"
                ? showOutcome(outcomeGrade ?? undefined)
                : selected && inspect(selected)
            }
          >
            {viewMode === "outcome" ? "定位变化区" : "定位当前对象"}
          </Button>
        </div>
      </header>
      <Alert
        showIcon
        type="info"
        title={
          workflow.workflowType === "geology_generic"
            ? "用户上传资料：字段含义经确认后生成工作副本。规则为试用规则，待裁定与未批准对象保留。"
            : "演示案例：岩性与构造为模拟识别；矿物为遥感矿物识别结果。规则在本案例试用，待裁定与未批准对象保留。"
        }
      />
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            <Button size="small" onClick={() => retryLoad()}>
              重试
            </Button>
          }
        />
      )}
      {loading && (
        <div className="geology-review-workspace-loading" role="status">
          <Spin />
          正在读取本次任务图层
          {progress.total > 0 &&
            `（已读取 ${progress.done}/${progress.total} 项）`}
          …
          {slow && (
            <>
              <span>读取较慢，可能是图层较大或网络较慢。</span>
              <Button size="small" onClick={() => retryLoad()}>
                重新读取
              </Button>
            </>
          )}
        </div>
      )}
      {data && (
        <>
          <MultiElementChapters
            workflow={workflow}
            active={chapter}
            tour={allTour}
            onChange={showChapter}
            intersections={data.overlays.find(
              (item) => item.key === "intersections",
            )}
          />
          {tour.length > 0 && (
            <nav className="multi-tour-toolbar" aria-label="修改导览">
              {onPage && (
                <div>
                  <Button
                    loading={pageLoading}
                    disabled={
                      Number(record(workflow.plan.pagination).offset) <= 0
                    }
                    onClick={() =>
                      void changePage(
                        Math.max(
                          0,
                          Number(record(workflow.plan.pagination).offset) - 25,
                        ),
                      )
                    }
                  >
                    上一页修改
                  </Button>
                  <Button
                    loading={pageLoading}
                    disabled={
                      Number(record(workflow.plan.pagination).offset) + 25 >=
                      Number(record(workflow.plan.pagination).total)
                    }
                    onClick={() =>
                      void changePage(
                        Number(record(workflow.plan.pagination).offset) + 25,
                      )
                    }
                  >
                    下一页修改
                  </Button>
                  <span>
                    共 {Number(record(workflow.plan.pagination).total)}{" "}
                    处，当前按页读取
                  </span>
                </div>
              )}
              <div className="multi-tour-pager">
                <Button
                  icon={<LeftOutlined />}
                  aria-label="上一处修改"
                  disabled={tourIndex <= 0}
                  onClick={() => showTour(tourIndex - 1)}
                >
                  上一处
                </Button>
                <strong aria-live="polite">
                  第{tourIndex + 1}处，共{tour.length}处
                </strong>
                <Button
                  icon={<RightOutlined />}
                  aria-label="下一处修改"
                  disabled={tourIndex >= tour.length - 1}
                  onClick={() => showTour(tourIndex + 1)}
                >
                  下一处
                </Button>
              </div>
              <div className="multi-tour-view-switch">
                <Button
                  type={viewMode === "tour" ? "primary" : "default"}
                  onClick={() => showTour(tourIndex)}
                >
                  逐处看修改
                </Button>
                <Button
                  type={viewMode === "overview" ? "primary" : "default"}
                  onClick={() => {
                    setViewMode("overview");
                    setFocus(reviewBounds(data.before));
                  }}
                >
                  查看全区
                </Button>
              </div>
            </nav>
          )}
          {viewMode === "overview" && (
            <div className="multi-element-map-controls">
              <strong>联动图层</strong>
              <Checkbox.Group
                options={[
                  ...data.overlays.map((item) => ({
                    value: item.key,
                    label: item.label,
                  })),
                  { value: "changes", label: "修正记录" },
                ]}
                value={visible}
                onChange={(items) => setVisible(items.map(String))}
              />
              {optionalLoading.length > 0 && (
                <span role="status">正在读取所选图层…</span>
              )}
            </div>
          )}
          {storyNeedsAlterations && optionalLoading.length > 0 && (
            <div className="multi-tour-loading" role="status">
              <Spin size="small" />
              正在读取当前矿物的实际前后权重…
            </div>
          )}
          {Object.entries(optionalErrors)
            .filter(
              ([key]) =>
                visible.includes(
                  key.startsWith("alterations-") ? "alterations" : key,
                ) ||
                (storyNeedsAlterations && key.startsWith("alterations-")),
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
          <div
            className={`geology-review-workspace-body${viewMode !== "overview" ? " multi-tour-layout" : ""}`}
          >
            <section className="geology-review-map-area">
              <div
                className="multi-tour-map-stage"
                data-current-change={
                  viewMode === "tour" ? currentTour?.key : undefined
                }
                aria-label={
                  viewMode === "tour"
                    ? "当前对象前后状态"
                    : viewMode === "outcome"
                      ? "调查建议前后对比"
                      : "全区前后对比"
                }
              >
                <GeologyReviewMaps
                  before={data.before}
                  after={data.after}
                  differences={
                    visible.includes("changes") ? data.differences : empty
                  }
                  overlays={overlays}
                  bounds={focus}
                  onSelect={(index) => {
                    const feature = data.differences.features[index];
                    if (feature) inspect(feature);
                  }}
                  onInspect={inspect}
                  beforeLabel={
                    viewMode === "tour"
                      ? "改前"
                      : viewMode === "outcome"
                        ? "处理前的核查区"
                        : "本次检查采用的岩性与构造"
                  }
                  afterLabel={
                    viewMode === "tour"
                      ? "改后"
                      : viewMode === "outcome"
                        ? "更新后的核查区"
                        : "获批修正版本及综合分析"
                  }
                  previewLabel="当前输入与检查范围，尚无修正版本"
                  compactLegend
                  spotlight={spotlight}
                />
              </div>
              {viewMode === "tour" && currentTour && (
                <MultiElementTourCard
                  change={currentTour}
                  before={tourBefore}
                  after={tourAfter}
                  algorithm={tourAlgorithm(workflow)}
                  cleanResults={usesCleanGeologyResults(workflow)}
                  loading={
                    currentTour.suggestion.element === "alteration" &&
                    optionalLoading.some((key) => key.startsWith("alterations"))
                  }
                />
              )}
              {viewMode === "outcome" && (
                <p className="multi-tour-map-note">
                  只突出实际改变的核查区；相同的核查区保持淡化。左右拖动、缩放保持同一视角。
                </p>
              )}
            </section>
            {viewMode === "overview" && (
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
                        <small>
                          {readable(feature.properties.status ?? "")}
                        </small>
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
            )}
          </div>
          {outcome && (
            <MultiElementOutcome
              result={outcome}
              active={viewMode === "outcome"}
              onFocus={showOutcome}
              onObjectFocus={inspect}
            />
          )}
          <WorkflowValidationPanel workflowId={workflow.id} />
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
