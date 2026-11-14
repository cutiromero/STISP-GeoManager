import { useCallback, useEffect, useRef, useState } from "react";
import type { BusinessFlowRun } from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";

const visible = () => document.visibilityState !== "hidden";
const active = new Set(["queued", "running", "waiting_compute"]);

export function useMonitorTask(
  projectId: number,
  userId: number | undefined,
  onCompleted: () => void,
  definitionId?: number,
) {
  const key = `monitor-task:${userId ?? "anonymous"}:${projectId}:landcover`;
  const [flow, setFlow] = useState<BusinessFlowRun>();
  const [error, setError] = useState<string>();
  const latest = useRef(flow);
  latest.current = flow;
  const completed = useRef(onCompleted);
  completed.current = onCompleted;
  const accept = useCallback(
    (next: BusinessFlowRun) => {
      if (next.projectId !== projectId) return;
      const previous = latest.current;
      if (
        previous?.id === next.id &&
        (next.revision < previous.revision ||
          (next.revision === previous.revision &&
            next.updatedAt < previous.updatedAt))
      )
        return;
      latest.current = next;
      setFlow(next);
      setError(undefined);
      try {
        sessionStorage.setItem(key, next.id);
      } catch {}
      if (
        previous?.id === next.id &&
        active.has(previous.status) &&
        next.status === "succeeded"
      )
        completed.current();
    },
    [projectId, key],
  );
  useEffect(() => {
    if (!userId || !definitionId) return;
    const controller = new AbortController();
    let id: string | null = null;
    try {
      id = sessionStorage.getItem(key);
    } catch {}
    if (id && /^[a-f0-9-]{36}$/.test(id))
      void businessFlowsApi
        .run(id, { signal: controller.signal })
        .then(accept)
        .catch((reason) => {
          if (controller.signal.aborted) return;
          if (
            reason instanceof ApiError &&
            [403, 404].includes(reason.status)
          ) {
            try {
              sessionStorage.removeItem(key);
            } catch {}
          } else
            setError(
              reason instanceof Error ? reason.message : "暂时无法读取任务记录",
            );
        });
    if (!id)
      void businessFlowsApi
        .runs({ signal: controller.signal })
        .then((result) => {
          const running = result.items.find(
            (row) => row.flowId === definitionId && active.has(row.status),
          );
          if (running && !controller.signal.aborted)
            return businessFlowsApi
              .run(running.id, { signal: controller.signal })
              .then(accept);
        })
        .catch(() => {});
    return () => controller.abort();
  }, [key, userId, accept, definitionId]);
  useEffect(() => {
    if (!flow || !active.has(flow.status)) return;
    const id = flow.id;
    const controller = new AbortController();
    let stopped = false;
    let pending = false;
    let timer: ReturnType<typeof setTimeout>;
    const read = async () => {
      clearTimeout(timer);
      if (stopped || pending || !visible()) return;
      pending = true;
      try {
        const next = await businessFlowsApi.run(id, {
          signal: controller.signal,
        });
        if (!stopped && latest.current?.id === id) accept(next);
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "暂时无法更新任务状态",
          );
      } finally {
        pending = false;
        if (
          !stopped &&
          latest.current?.id === id &&
          active.has(latest.current.status) &&
          visible()
        )
          timer = setTimeout(read, 2000);
      }
    };
    const visibility = () => {
      if (visible()) void read();
      else clearTimeout(timer);
    };
    timer = setTimeout(read, 2000);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [flow?.id, flow?.status, accept]);
  return { flow, accept, error };
}
