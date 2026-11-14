import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MonitoringProductList } from "../api/generated/types.gen";
import { getMonitoringProducts } from "./productApi";

export function useMonitoringProducts(scene: MonitoringProductList["scene"]) {
  const { t } = useTranslation();
  const pending = useRef<AbortController | undefined>(undefined);
  const [page, setPage] = useState<MonitoringProductList>();
  const [selectedId, setSelectedId] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<string>();
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setFailure(undefined);
    setLoading(true);
    void getMonitoringProducts(scene, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setPage(value);
        setSelectedId((current) =>
          value.items.some((item) => item.id === current) ? current : undefined,
        );
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setPage(undefined);
        setSelectedId(undefined);
        setFailure(
          error instanceof Error ? error.message : t("monitor.sourceError"),
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scene, revision, t]);
  const loadMore = async () => {
    if (!page?.nextBeforeId || loading) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    try {
      const value = await getMonitoringProducts(
        scene,
        controller.signal,
        page.nextBeforeId,
      );
      if (!controller.signal.aborted)
        setPage((previous) =>
          previous
            ? {
                ...value,
                items: [
                  ...previous.items,
                  ...value.items.filter(
                    (item) => !previous.items.some((old) => old.id === item.id),
                  ),
                ],
              }
            : value,
        );
    } catch (error) {
      if (!controller.signal.aborted) {
        setPage(undefined);
        setSelectedId(undefined);
        setFailure(
          error instanceof Error ? error.message : t("monitor.sourceError"),
        );
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };
  const selected =
    page?.items.find((item) => item.id === selectedId) ?? page?.items[0];
  return {
    page,
    selected,
    selectedId,
    setSelectedId,
    loading,
    failure,
    setFailure,
    revision,
    setRevision,
    loadMore,
  };
}
