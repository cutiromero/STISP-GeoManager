import { Alert, Button, Select, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import type {
  BusinessFlowInputAdapterChoices,
  BusinessFlowInputPlan,
  BusinessFlowInputPreparation,
  ComputeParameterSpec,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import { ApiError } from "../api/client";
import { canonicalReadKey } from "../api/readFlights";
import { browserSessionEpoch } from "../auth/browserSession";
import { getActiveProject } from "../projects/session";
import { ComputeParameterControl } from "../compute/ComputeAlgorithmFields";
import { useComputeText } from "../compute/ui";

const PREPARATION_DELAY_MS = 180;
export function preparationKey(value: BusinessFlowInputPreparation) {
  return canonicalReadKey({
    request: value,
    epoch: browserSessionEpoch(),
    project: getActiveProject(),
  });
}
const kinds: Record<string, string> = {
  vector: "矢量",
  raster: "栅格",
  table: "表格",
  document: "文档",
  image: "图片",
  gene: "基因数据",
};

export default function InputAdaptationReview({
  flowId,
  request,
  disabled,
  onChoices,
  onStatus,
}: {
  flowId: number;
  request: BusinessFlowInputPreparation;
  disabled: boolean;
  onChoices: (value: BusinessFlowInputAdapterChoices) => void;
  onStatus: (key: string, ready: boolean, plan?: BusinessFlowInputPlan) => void;
}) {
  const ui = useComputeText();
  const key = preparationKey(request),
    base = preparationKey({ ...request, inputAdapters: undefined });
  const callbacks = useRef({ onChoices, onStatus });
  callbacks.current = { onChoices, onStatus };
  const current = useRef(key);
  current.current = key;
  const [attempt, setAttempt] = useState(0);
  const [value, setValue] = useState<{
    base: string;
    key: string;
    plan?: BusinessFlowInputPlan;
    loading: boolean;
    error: string;
  }>({ base, key, loading: true, error: "" });
  useEffect(() => {
    const controller = new AbortController();
    callbacks.current.onStatus(key, false);
    setValue((previous) => ({
      base,
      key,
      plan: previous.base === base ? previous.plan : undefined,
      loading: true,
      error: "",
    }));
    if (!Object.keys(request.inputs).length) {
      const plan = { ready: true, items: [] };
      setValue({ base, key, plan, loading: false, error: "" });
      callbacks.current.onStatus(key, true, plan);
      return () => controller.abort();
    }
    const timer = setTimeout(() => {
      void businessFlowsApi
        .prepareInputs(flowId, request, { signal: controller.signal })
        .then((plan) => {
          if (controller.signal.aborted || current.current !== key) return;
          setValue({ base, key, plan, loading: false, error: "" });
          callbacks.current.onStatus(key, plan.ready, plan);
        })
        .catch((error) => {
          if (controller.signal.aborted || current.current !== key) return;
          setValue((previous) => ({
            base,
            key,
            plan:
              error instanceof ApiError &&
              [401, 403, 404].includes(error.status)
                ? undefined
                : previous.base === base
                  ? previous.plan
                  : undefined,
            loading: false,
            error:
              error instanceof Error
                ? error.message
                : "输入适配方案暂时无法读取",
          }));
          callbacks.current.onStatus(key, false);
        });
    }, PREPARATION_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [flowId, key, attempt]);
  const active = value.base === base ? value : undefined;
  const changed = (
    role: string,
    versionId: number,
    parameters: Record<string, unknown>,
  ) =>
    callbacks.current.onChoices({
      ...request.inputAdapters,
      [role]: { versionId, parameters },
    });
  const rows =
    active?.plan?.items.filter((item) => item.status !== "direct") ?? [];
  if (!rows.length && !active?.loading && !active?.error) return null;
  return (
    <section
      className="flow-input-adaptation"
      aria-label={ui("输入适配方案", "Input adaptation plan")}
    >
      {active?.loading && (
        <div role="status" className="flow-input-adaptation-status">
          <Spin size="small" />{" "}
          {ui(
            "正在匹配输入规范与转换能力…",
            "Matching inputs and conversion capabilities…",
          )}
        </div>
      )}
      {active?.error && (
        <Alert
          type="warning"
          title={active.error}
          action={
            <Button onClick={() => setAttempt((value) => value + 1)}>
              {ui("重试规划", "Retry preparation")}
            </Button>
          }
        />
      )}
      {rows.length > 0 && <h3>{ui("输入适配", "Input adaptation")}</h3>}
      {rows.map((item) => {
        const selected = item.candidates?.find(
          (candidate) =>
            candidate.versionId ===
            (request.inputAdapters?.[item.role]?.versionId ?? item.versionId),
        );
        const parameters = {
          ...item.parameters,
          ...request.inputAdapters?.[item.role]?.parameters,
        };
        const specs = (selected?.parameters ?? []) as ComputeParameterSpec[];
        return (
          <div className="flow-input-adaptation-source" key={item.role}>
            <strong>{item.sourceName}</strong>
            <small>
              {kinds[item.sourceType] ?? item.sourceType} →{" "}
              {item.targetTypes.map((type) => kinds[type] ?? type).join(" / ")}
            </small>
            {item.status === "unavailable" ? (
              <Alert
                type="info"
                title={ui(
                  "尚无符合规范的已发布转换工具",
                  "No published converter meets this requirement",
                )}
                description={ui(
                  "保留当前选择。可选择其他资料，或在计算中心登记兼容的转换算子后重试。",
                  "Keep this selection, choose another source, or register a compatible converter in the compute center.",
                )}
              />
            ) : (
              <>
                <Select
                  aria-label={`${item.sourceName}：转换工具`}
                  value={selected?.versionId}
                  disabled={disabled}
                  placeholder={ui(
                    "选择适合任务含义的转换工具",
                    "Choose a converter matching this task",
                  )}
                  options={item.candidates?.map((candidate) => ({
                    value: candidate.versionId,
                    label: candidate.name,
                  }))}
                  onChange={(versionId) => changed(item.role, versionId, {})}
                />
                {selected && <p>{selected.description}</p>}
                {selected && (
                  <div className="flow-input-adaptation-parameters">
                    {specs
                      .filter(
                        (spec) =>
                          !spec.when ||
                          parameters[String(spec.when.key)] ===
                            spec.when.equals,
                      )
                      .map((spec) => (
                        <label key={spec.key}>
                          <span>{spec.label}</span>
                          <ComputeParameterControl
                            parameter={spec}
                            candidate={{
                              fields: item.fields ?? [],
                              bands: item.sourceBands ?? 0,
                            }}
                            value={parameters[spec.key]}
                            checked={parameters[spec.key] === true}
                            onChange={(next) =>
                              changed(item.role, selected.versionId, {
                                ...parameters,
                                [spec.key]: next,
                              })
                            }
                          />
                        </label>
                      ))}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}
