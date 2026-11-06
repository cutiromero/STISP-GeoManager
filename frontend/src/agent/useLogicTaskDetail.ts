import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import type { AgentWorkflow } from "../api/generated/types.gen";

type Part = "steps" | "suggestions";
type Snapshot = {
  scope: string;
  part: Part;
  value?: AgentWorkflow;
  loading: boolean;
  error: string;
};

export function useLogicTaskDetail(workflow: AgentWorkflow) {
  const current = useRef(workflow);
  current.current = workflow;
  const identity = `${workflow.projectId}:${workflow.id}`;
  const scope = useRef(identity);
  scope.current = identity;
  const request = useRef<AbortController | undefined>(undefined);
  const cache = useRef<{
    scope: string;
    values: Partial<Record<Part, AgentWorkflow>>;
  }>({ scope: identity, values: {} });
  const [snapshot, setSnapshot] = useState<Snapshot>({
    scope: identity,
    part: "steps",
    loading: false,
    error: "",
  });
  useEffect(() => () => request.current?.abort(), [identity]);
  const load = useCallback(
    async (part: Part, append = false, refresh = false) => {
      request.current?.abort();
      const task = current.current;
      const expected = `${task.projectId}:${task.id}`;
      if (cache.current.scope !== expected)
        cache.current = { scope: expected, values: {} };
      const previous = cache.current.values[part];
      const reviewing =
        task.status === "waiting_approval" &&
        task.plan.phase === "review_modifications";
      if (
        previous &&
        !append &&
        !refresh &&
        (!reviewing || previous.planHash === task.planHash)
      ) {
        setSnapshot({
          scope: expected,
          part,
          value: previous,
          loading: false,
          error: "",
        });
        return;
      }
      const controller = new AbortController();
      request.current = controller;
      setSnapshot({
        scope: expected,
        part,
        value: previous,
        loading: true,
        error: "",
      });
      try {
        const next = await agentApi.workflow(task.id, {
          view: "inspection",
          part,
          signal: controller.signal,
          ...(append
            ? {
                offset:
                  part === "steps"
                    ? (previous?.steps.length ?? 0)
                    : (previous?.modificationReview?.suggestions.length ?? 0),
              }
            : {}),
        });
        if (controller.signal.aborted || scope.current !== expected) return;
        if (append && previous && next.planHash !== previous.planHash)
          throw new Error("记录已经更新，请先读取最新内容后再继续翻页");
        const latest = current.current;
        if (
          latest.status === "waiting_approval" &&
          latest.plan.phase === "review_modifications" &&
          next.planHash !== latest.planHash
        )
          throw new Error("处置方案已更新，请读取最新建议后再确认");
        const value =
          append && previous
            ? {
                ...next,
                steps: [
                  ...new Map(
                    [...previous.steps, ...next.steps].map((s) => [s.id, s]),
                  ).values(),
                ].sort((a, b) => a.sequence - b.sequence),
                modificationReview: next.modificationReview && {
                  ...next.modificationReview,
                  suggestions: [
                    ...new Map(
                      [
                        ...(previous.modificationReview?.suggestions ?? []),
                        ...next.modificationReview.suggestions,
                      ].map((s) => [s.id, s]),
                    ).values(),
                  ],
                },
              }
            : next;
        cache.current.values[part] = value;
        setSnapshot({
          scope: expected,
          part,
          value,
          loading: false,
          error: "",
        });
      } catch (reason) {
        if (controller.signal.aborted || scope.current !== expected) return;
        setSnapshot({
          scope: expected,
          part,
          value: previous,
          loading: false,
          error:
            reason instanceof Error ? reason.message : "暂时无法读取任务详情",
        });
      }
    },
    [],
  );
  const valid = snapshot.scope === identity;
  return {
    detail: valid && snapshot.value ? snapshot.value : workflow,
    stepsDetail:
      cache.current.scope === identity ? cache.current.values.steps : undefined,
    suggestionsDetail:
      cache.current.scope === identity
        ? cache.current.values.suggestions
        : undefined,
    loading: valid && snapshot.loading,
    error: valid ? snapshot.error : "",
    part: snapshot.part,
    load,
    initialized: valid && Boolean(snapshot.value),
  };
}
