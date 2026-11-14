import { useEffect, useMemo, useRef, useState } from "react";
import type {
  MonitoringProduct,
  ResourceListItem,
} from "../api/generated/types.gen";

export type ProductView = "current" | "history" | "standard" | "uploaded";
export function useMonitorProductSelection({
  items,
  references = [],
  sourceId,
  currentBatchId,
}: {
  items: MonitoringProduct[];
  references?: ResourceListItem[];
  sourceId?: number;
  currentBatchId?: string;
}) {
  const [view, setView] = useState<ProductView>("current");
  const [key, setKey] = useState<string>();
  const chosen = useRef(false);
  const previousBatch = useRef<string | undefined>(undefined);
  const previousSource = useRef(sourceId);
  const latestOwned = items.find(
    (item) =>
      item.provenance?.owned &&
      item.provenance.type === "system_interpretation",
  );
  const batch = currentBatchId ?? latestOwned?.provenance?.batchId ?? undefined;
  const candidates = useMemo(
    () =>
      items.filter(
        (item) =>
          sourceId === undefined ||
          (sourceId > 0 && item.sourceResourceIds.includes(sourceId)),
      ),
    [items, sourceId],
  );
  const system = (item: MonitoringProduct) =>
    item.provenance?.type === "system_interpretation" ||
    (!item.provenance && item.kind === "model");
  const groups = {
    current: candidates.filter(
      (item) =>
        system(item) && Boolean(batch) && item.provenance?.batchId === batch,
    ),
    history: candidates.filter(
      (item) => system(item) && item.provenance?.batchId !== batch,
    ),
    standard: candidates.filter(
      (item) => item.provenance?.type === "uploaded_standard",
    ),
    uploaded: candidates.filter(
      (item) => !system(item) && item.provenance?.type !== "uploaded_standard",
    ),
  };
  useEffect(() => {
    if (batch && batch !== previousBatch.current) {
      previousBatch.current = batch;
      chosen.current = false;
      setView("current");
      setKey(undefined);
    }
    if (!chosen.current && !batch && items.length)
      setView(items.some(system) ? "history" : "uploaded");
  }, [batch, items]);
  useEffect(() => {
    if (previousSource.current !== sourceId) {
      previousSource.current = sourceId;
      setKey(undefined);
    }
  }, [sourceId]);
  const choices = groups[view];
  const selected =
    choices.find((item) => `product:${item.id}` === key) ??
    (!key ? choices[0] : undefined);
  const reference =
    view === "standard" && !key?.startsWith("product:")
      ? references.find((item) => `resource:${item.id}` === key)
      : undefined;
  const selectView = (next: ProductView) => {
    chosen.current = true;
    setView(next);
    setKey(undefined);
  };
  const selectKey = (next: string) => {
    chosen.current = true;
    setKey(next);
  };
  const showCurrent = () => {
    chosen.current = false;
    setView("current");
    setKey(undefined);
  };
  return {
    hasCurrentTask: Boolean(currentBatchId),
    hasUploaded: groups.uploaded.length > 0,
    view,
    selectView,
    key: reference
      ? `resource:${reference.id}`
      : selected
        ? `product:${selected.id}`
        : key,
    selectKey,
    selected: reference ? undefined : selected,
    reference,
    choices,
    references,
    batch,
    showCurrent,
  };
}

export type MonitorProductSelection = ReturnType<
  typeof useMonitorProductSelection
>;
