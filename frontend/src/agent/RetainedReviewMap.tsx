import { Alert, Button, Spin } from "antd";
import { useEffect, useMemo, useState } from "react";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import LocalGeologyReviewMaps from "../map/LocalGeologyReviewMaps";
import { queryReviewMap, record, reviewBounds } from "../map/geologyReviewData";

const empty: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
type Background = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection;
  faults: GeoJsonFeatureCollection;
  afterFaults: GeoJsonFeatureCollection;
};

export default function RetainedReviewMap({
  workflow,
  objects,
  focused,
  onFocus,
}: {
  workflow: AgentWorkflow;
  objects: GeoJsonFeatureCollection;
  focused?: string;
  onFocus: (id: string) => void;
}) {
  const map = record(workflow.plan.multiElementMap);
  const before = record(map.before);
  const after = record(map.after);
  const inputs = record(workflow.plan.inputs);
  const manifest = record(
    record(record(workflow.plan.algorithms)["geology-multi-apply"]).manifest,
  );
  const cleanFaults =
    Array.isArray(manifest.outputs) &&
    manifest.outputs.some((output) => record(output).key === "final_faults");
  const ids = [
    before.lithology ?? inputs.lithology,
    after.lithology ?? before.lithology ?? inputs.lithology,
    before.faults ?? inputs.faults,
    after.faults ??
      (after.lithology && cleanFaults
        ? undefined
        : (before.faults ?? inputs.faults)),
  ];
  const key = JSON.stringify([
    workflow.projectId,
    workflow.id,
    workflow.planHash,
    ids,
  ]);
  const [background, setBackground] = useState<Background>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [locate, setLocate] = useState(false);
  useEffect(() => {
    let disposed = false;
    setBackground(undefined);
    setError("");
    setLoading(false);
    const refs = JSON.parse(key)[3] as unknown[];
    if (!Number.isSafeInteger(refs[0]) || Number(refs[0]) <= 0) return;
    const requests = new Map<number, Promise<GeoJsonFeatureCollection>>();
    const read = (value: unknown, mixed = false, allowEmpty = mixed) => {
      if (!Number.isSafeInteger(value) || Number(value) <= 0)
        return Promise.resolve(empty);
      const id = Number(value);
      let pending = requests.get(id);
      if (!pending) {
        pending = queryReviewMap(id, {
          displayGeometry: true,
          loadStyle: true,
          allowEmpty,
          mixed,
        });
        requests.set(id, pending);
      }
      return pending;
    };
    setLoading(true);
    setError("");
    setBackground(undefined);
    void Promise.all([
      read(refs[0]),
      read(refs[1], false, true),
      read(refs[2], true),
      read(refs[3], true),
    ])
      .then(([before, after, faults, afterFaults]) => {
        if (!disposed)
          setBackground({
            before: before!,
            after: after!,
            faults: faults!,
            afterFaults: afterFaults!,
          });
      })
      .catch((reason: unknown) => {
        if (!disposed)
          setError(reason instanceof Error ? reason.message : "底图读取失败");
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [key, attempt]);
  useEffect(() => setLocate(Boolean(focused)), [focused]);
  const focus = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: objects.features.filter(
        (feature) => String(feature.id) === focused,
      ),
    }),
    [objects, focused],
  );
  const markers = useMemo<GeoJsonFeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: objects.features.flatMap((feature) => {
        const extent = reviewBounds({
          type: "FeatureCollection",
          features: [feature],
        });
        if (!extent) return [];
        const element = String(feature.properties.element ?? "");
        return [
          {
            ...feature,
            geometry: {
              type: "Point" as const,
              coordinates: [
                (extent[0] + extent[2]) / 2,
                (extent[1] + extent[3]) / 2,
              ],
            },
            properties: {
              ...feature.properties,
              _review_outlineOnly: false,
              fill_color:
                element === "lithology"
                  ? "#2381b5"
                  : element === "structure"
                    ? "#d96535"
                    : "#9b59a1",
              legend_label:
                element === "lithology"
                  ? "岩性疑点定位"
                  : element === "structure"
                    ? "构造疑点定位"
                    : "蚀变组定位",
            },
          },
        ];
      }),
    }),
    [objects],
  );
  const spotlightFeatures = useMemo<GeoJsonFeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: focus.features.flatMap((feature) =>
        feature.properties._review_outlineOnly === true
          ? markers.features.filter((marker) => marker.id === feature.id)
          : [feature],
      ),
    }),
    [focus, markers],
  );
  const ranges = useMemo<GeoJsonFeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: focus.features
        .filter((feature) => feature.properties._review_outlineOnly === true)
        .map((feature) => ({
          ...feature,
          properties: { ...feature.properties, _review_navigation: true },
        })),
    }),
    [focus],
  );
  const bounds = useMemo(
    () =>
      reviewBounds(
        locate && focus.features.length
          ? focus
          : (background?.before ?? objects),
      ),
    [locate, focus, background, objects],
  );
  const overlays = useMemo(
    () => [
      ...(background
        ? [
            {
              key: "faults",
              label: "构造",
              before: background.faults,
              after: background.afterFaults,
              color: "#76566d",
            },
          ]
        : []),
      {
        key: "held-evidence",
        label: "疑点定位",
        before: empty,
        after: markers,
        color: "#dc861d",
      },
      ...(ranges.features.length
        ? [
            {
              key: "navigation-range",
              label: "蚀变组定位范围",
              before: empty,
              after: ranges,
              color: "#d98524",
            },
          ]
        : []),
    ],
    [background, markers, ranges],
  );
  const inspect = (feature: GeoJsonFeatureCollection["features"][number]) => {
    const target = objects.features.find(
      (item) =>
        String(item.id) === String(feature.id) ||
        item.properties.feature_id === feature.properties.feature_id,
    );
    if (target) onFocus(String(target.id));
  };
  return (
    <div className="logic-retained-map" aria-label="地质底图与待核查对象">
      <div className="logic-retained-map-toolbar">
        <span>结合地质背景核查所选对象，左右地图联动。</span>
        <Button size="small" onClick={() => setLocate(false)}>
          查看全区
        </Button>
        <Button
          size="small"
          disabled={!focused}
          onClick={() => setLocate(true)}
        >
          定位所选对象
        </Button>
        <Button
          size="small"
          target="_blank"
          rel="noopener"
          href={`/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}${focused ? `&suggestion=${encodeURIComponent(focused)}` : ""}`}
        >
          打开完整对比
        </Button>
      </div>
      {loading && (
        <div role="status">
          <Spin size="small" /> 正在读取地质底图…
        </div>
      )}
      {error && (
        <Alert
          type="warning"
          title="地质底图暂未加载"
          description={error}
          action={
            <Button
              size="small"
              onClick={() => setAttempt((value) => value + 1)}
            >
              重试底图
            </Button>
          }
        />
      )}
      <LocalGeologyReviewMaps
        before={background?.before ?? objects}
        after={background?.after ?? null}
        differences={empty}
        bounds={bounds}
        single={!background}
        inspectionOnly
        overlays={background ? overlays : []}
        beforeLabel={background ? "本次检查采用的地质资料" : "待核查对象位置"}
        afterLabel={
          after.lithology ? "当前成果与待核查对象" : "待核查对象（尚未执行）"
        }
        compactLegend
        spotlight={
          focused
            ? {
                before: background ? empty : focus,
                after: spotlightFeatures,
                beforeLabel: background
                  ? undefined
                  : String(focus.features[0]?.properties.feature_id ?? ""),
                afterLabel: String(
                  focus.features[0]?.properties.feature_id ?? "",
                ),
                outlineOnly: true,
              }
            : null
        }
        onSelect={() => {}}
        onInspect={inspect}
      />
    </div>
  );
}
