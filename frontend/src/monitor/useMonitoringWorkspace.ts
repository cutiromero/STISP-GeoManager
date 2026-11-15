import { useEffect, useMemo, useState } from "react";
import { requestJson } from "../api/client";
import type {
  MonitoringSourceCatalog,
  MonitoringSourceTimePage,
} from "../api/generated/types.gen";

export type MonitorRegion = {
  west: number;
  south: number;
  east: number;
  north: number;
};
export const validRegion = (value?: MonitorRegion): value is MonitorRegion =>
  Boolean(
    value &&
    Object.values(value).every(Number.isFinite) &&
    -180 <= value.west &&
    value.west < value.east &&
    value.east <= 180 &&
    -85 <= value.south &&
    value.south < value.north &&
    value.north <= 85,
  );
export const observationProducts = [
  { value: "gwis_ba", label: "GWIS 火烧面积" },
  { value: "gfed_ba", label: "GFED 火烧面积" },
  { value: "fcci_ba", label: "FCCI 月火烧面积" },
  { value: "cams_frpfire", label: "CAMS 火辐射功率" },
];

export const monitoringPeriodLabel = (
  product: string,
  time?: { date: string; endDate: string },
) =>
  time
    ? product === "fcci_ba"
      ? time.date.slice(0, 7)
      : `${time.date} — ${time.endDate}`
    : "";

export function useMonitoringWorkspace(
  scene: MonitoringSourceCatalog["scene"],
  projectId: number,
) {
  const [loadedCatalog, setCatalog] = useState<MonitoringSourceCatalog>();
  const catalog =
    loadedCatalog?.projectId === projectId && loadedCatalog.scene === scene
      ? loadedCatalog
      : undefined;
  const [error, setError] = useState<string>();
  const [revision, refresh] = useState(0);
  const [collection, setCollection] = useState<string>();
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [setId, setSetId] = useState<string>();
  const [sourceId, setSourceId] = useState<number>();
  const [product, setProduct] = useState("gwis_ba");
  const [year, setYear] = useState<number>();
  const [ordinal, setOrdinal] = useState<number>();
  const [loadedTimes, setLoadedTimes] = useState<{
    key: string;
    page: MonitoringSourceTimePage;
  }>();
  const [region, setRegion] = useState<MonitorRegion>();
  const [drawing, setDrawing] = useState(false);
  const [sourceVisible, setSourceVisible] = useState(false);
  const [sourceOpacity, setSourceOpacity] = useState(70);
  const [resultVisible, setResultVisible] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    const query = new URLSearchParams({ scene, offset: String(offset) });
    if (collection) query.set("collection", collection);
    void requestJson<MonitoringSourceCatalog>(
      `/api/ecology/monitoring/sources/?${query}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setCatalog(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setCatalog(undefined);
          setError(String(reason.message ?? reason));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scene, projectId, revision, collection, offset]);
  const inputSet =
    catalog?.inputSets.find((row) => row.id === setId) ?? catalog?.inputSets[0];
  const source =
    catalog?.assets.find((row) => row.resource.id === sourceId) ??
    catalog?.assets.find(
      (row) => row.resource.id === inputSet?.resources.slice(-1)[0]?.id,
    ) ??
    catalog?.assets[0];
  const years =
    source?.years.filter((row) =>
      row.validProducts.some((value) => value === product),
    ) ?? [];
  const selectedYear =
    years.find((row) => row.year === year)?.year ?? years.slice(-1)[0]?.year;
  const timeKey = `${projectId}:${scene}:${source?.resource.id}:${source?.metadata.indexVersion}:${selectedYear}:${product}`;
  const timePage = loadedTimes?.key === timeKey ? loadedTimes.page : undefined;
  useEffect(() => {
    if (source?.metadata.sourceSchema.kind !== "native_cube" || !selectedYear)
      return;
    const controller = new AbortController();
    const query = new URLSearchParams({
      scene,
      resourceId: String(source.resource.id),
      year: String(selectedYear),
      product,
    });
    void requestJson<MonitoringSourceTimePage>(
      `/api/ecology/monitoring/source-times/?${query}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted)
          setLoadedTimes({ key: timeKey, page: value });
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(String(reason.message ?? reason));
      });
    return () => controller.abort();
  }, [
    scene,
    projectId,
    source?.resource.id,
    source?.metadata.indexVersion,
    selectedYear,
    product,
    timeKey,
  ]);
  const times = useMemo(
    () =>
      (timePage?.items ?? []).filter(
        (row, index, rows) =>
          product !== "fcci_ba" ||
          index === 0 ||
          row.date.slice(0, 7) !== rows[index - 1]!.date.slice(0, 7),
      ),
    [timePage, product],
  );
  const time =
    times.find((row) => row.ordinal === ordinal) ?? times.slice(-1)[0];
  const inputs: Record<string, number> =
    scene === "wildfire"
      ? source
        ? { cube: source.resource.id }
        : {}
      : (inputSet?.inputs ?? {});
  const ready = Boolean(
    validRegion(region) &&
    catalog?.method &&
    (scene === "wildfire" ? time : inputSet),
  );
  return {
    scene,
    catalog,
    loading,
    error,
    refresh: () => refresh((v) => v + 1),
    collection,
    selectCollection: (value: string) => {
      setCollection(value || undefined);
      setOffset(0);
      setSetId(undefined);
      setSourceId(undefined);
    },
    offset,
    previousPage: () => setOffset((v) => Math.max(0, v - 200)),
    nextPage: () =>
      catalog?.nextOffset != null && setOffset(catalog.nextOffset),
    inputSet,
    selectSet: (id: string) => {
      setSetId(id);
      const row = catalog?.inputSets.find((item) => item.id === id);
      setSourceId(row?.resources.slice(-1)[0]?.id);
    },
    source,
    setSourceId,
    product,
    setProduct,
    years,
    selectedYear,
    setYear,
    time,
    times,
    setOrdinal,
    region,
    setRegion,
    drawing,
    setDrawing,
    sourceVisible,
    setSourceVisible,
    sourceOpacity,
    setSourceOpacity,
    resultVisible,
    setResultVisible,
    inputs,
    ready,
  };
}
export type MonitoringWorkspace = ReturnType<typeof useMonitoringWorkspace>;
