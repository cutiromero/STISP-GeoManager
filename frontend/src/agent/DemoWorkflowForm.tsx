import {
  Alert,
  Button,
  Input,
  InputNumber,
  Select,
  Space,
  Tooltip,
} from "antd";
import { useEffect, useState } from "react";
import type {
  AgentResource,
  ComputeCandidate,
} from "../api/generated/types.gen";
import {
  geologyInputIssues,
  geologyRoleHelp,
  geologyWorkflowIssues,
} from "./geologyWorkflowInputs";

export type DemoWorkflowType =
  | "ecology_investigation"
  | "geology_correction"
  | "geology_age_correction"
  | "geology_map_review";
type Role = { key: string; label: string; kind: string; match: RegExp };
export const demoRoles: Record<DemoWorkflowType, Role[]> = {
  ecology_investigation: [
    {
      key: "early_image",
      label: "前期影像",
      kind: "raster",
      match: /前期|早期|early|before/i,
    },
    {
      key: "late_image",
      label: "后期影像",
      kind: "raster",
      match: /后期|晚期|late|after/i,
    },
    {
      key: "valid_mask",
      label: "共同有效像元掩膜",
      kind: "raster",
      match: /有效|掩膜|valid|mask/i,
    },
    {
      key: "zones",
      label: "调查分区",
      kind: "vector",
      match: /分区|调查区|zones|district/i,
    },
    {
      key: "context",
      label: "生态背景与观测记录",
      kind: "table",
      match: /背景|观测|context|observation/i,
    },
  ],
  geology_correction: [
    {
      key: "initial_map",
      label: "初始填图",
      kind: "vector",
      match: /初始|原始|initial|original/i,
    },
    {
      key: "surveys",
      label: "调查证据",
      kind: "table",
      match: /调查|证据|survey|evidence/i,
    },
    {
      key: "rules",
      label: "结构化检查规则",
      kind: "table",
      match: /规则|rules/i,
    },
  ],
  geology_age_correction: [
    {
      key: "initial_map",
      label: "初始地质图副本",
      kind: "vector",
      match: /时代.*初始|初始.*时代|演示.*设错|age.*initial/i,
    },
    {
      key: "surveys",
      label: "空间背景与资料说明",
      kind: "table",
      match: /空间背景|资料说明|age.*context/i,
    },
    {
      key: "rules",
      label: "地层时代适用规则",
      kind: "table",
      match: /时代.*规则|age.*rules/i,
    },
  ],
  geology_map_review: [
    {
      key: "initial_map",
      label: "待检查地质图",
      kind: "vector",
      match: /待检查.*地质图|geology.*review.*input/i,
    },
    {
      key: "coverage",
      label: "制图范围",
      kind: "vector",
      match: /制图.*(?:范围|覆盖)|coverage/i,
    },
    {
      key: "rules",
      label: "专家规则",
      kind: "table",
      match: /专家.*规则|review.*rules/i,
    },
  ],
};

export const demoGoals: Record<DemoWorkflowType, string> = {
  ecology_investigation:
    "分析两期植被变化，结合生态背景和观测证据确定调查优先区，说明依据与待补资料。",
  geology_correction:
    "检查初始填图，结合调查证据与规则修正明确问题，输出修改图和依据并再次复核。",
  geology_age_correction:
    "检查真实地质图副本中明确标注的少量时代录入错误，结合辞书、地区及地层条件进行受约束编辑，保存前后地图、理由和复查结果。",
  geology_map_review:
    "请检查这张待提交的地质图，查阅专家知识，说明发现的问题和建议修改；经我批准后修正地图，复核结果并生成检查报告和统计表。",
};

function matchingCandidates(
  type: DemoWorkflowType,
  role: Role,
  candidates: ComputeCandidate[],
) {
  return candidates.filter(
    (candidate) =>
      candidate.kind === role.kind &&
      (type !== "geology_map_review" ||
        !geologyInputIssues(role.key, candidate).length),
  );
}

export function demoInputsReady(
  type: DemoWorkflowType,
  inputs: Record<string, number>,
  candidates?: ComputeCandidate[],
) {
  return (
    demoRoles[type].every((role) => (inputs[role.key] ?? 0) > 0) &&
    (type !== "geology_map_review" ||
      !candidates ||
      !geologyWorkflowIssues(inputs, candidates).length)
  );
}

export default function DemoWorkflowForm({
  type,
  candidates,
  resources,
  inputs,
  parameters,
  disabled,
  evidenceOnly = false,
  preset,
  onPresetRestore,
  onInputsChange,
  onParametersChange,
}: {
  type: DemoWorkflowType;
  candidates: ComputeCandidate[];
  resources: AgentResource[];
  inputs: Record<string, number>;
  parameters: Record<string, unknown>;
  disabled: boolean;
  evidenceOnly?: boolean;
  preset?: {
    inputs: Record<string, number>;
    parameters: Record<string, unknown>;
  };
  onPresetRestore?: () => void;
  onInputsChange: (value: Record<string, number>) => void;
  onParametersChange: (value: Record<string, unknown>) => void;
}) {
  const roles = demoRoles[type];
  const [matchFeedback, setMatchFeedback] = useState("");
  useEffect(() => setMatchFeedback(""), [type]);
  const inputIssues =
    type === "geology_map_review"
      ? geologyWorkflowIssues(inputs, candidates)
      : [];
  const presetReady = Boolean(
    preset && demoInputsReady(type, preset.inputs, candidates),
  );
  const selected = roles.flatMap((role) => {
    const resource = resources.find((entry) => entry.id === inputs[role.key]);
    const candidate = candidates.find((entry) => entry.id === inputs[role.key]);
    return candidate
      ? [
          {
            role,
            name: resource?.name ?? candidate.name,
            description: resource?.description ?? "",
            fileFormat: candidate.fileFormat ?? "",
          },
        ]
      : [];
  });
  const setParameter = (key: string, value: unknown) =>
    onParametersChange({ ...parameters, [key]: value });
  const autoMatch = () => {
    const next = { ...inputs };
    const matched: string[] = [];
    const unresolved: string[] = [];
    for (const role of roles) {
      const found = matchingCandidates(type, role, candidates).filter((entry) =>
        role.match.test(
          resources.find((item) => item.id === entry.id)?.name ?? entry.name,
        ),
      );
      const exact = found.filter(
        (entry) =>
          (
            resources.find((item) => item.id === entry.id)?.name ?? entry.name
          ).trim() === role.label,
      );
      const unique = exact.length === 1 ? exact : found;
      if (unique.length === 1) {
        next[role.key] = unique[0]!.id;
        matched.push(role.label);
      } else {
        const selectedCompatible = matchingCandidates(
          type,
          role,
          candidates,
        ).some((item) => item.id === next[role.key]);
        const previousSelection = next[role.key];
        if (previousSelection && !selectedCompatible) delete next[role.key];
        unresolved.push(
          `${role.label}${found.length ? "有多个匹配" : "没有兼容的名称匹配"}${previousSelection ? (selectedCompatible ? "，已保留兼容的手动选择，请核对" : "，原选择不兼容，已清空") : "，请手动选择"}`,
        );
      }
    }
    onInputsChange(next);
    setMatchFeedback(
      [
        matched.length
          ? `已重新匹配：${matched.join("、")}。`
          : "未找到唯一匹配的资料。",
        ...unresolved,
      ].join(" "),
    );
  };
  const bandLimit = Math.min(
    ...["early_image", "late_image"].map(
      (key) =>
        candidates.find((entry) => entry.id === inputs[key])?.bands || 99,
    ),
  );
  return (
    <section
      className="agent-demo-form"
      aria-label={
        type === "ecology_investigation" ? "生态调查资料" : "地质纠偏资料"
      }
    >
      <div className="agent-demo-form-heading">
        <strong>按角色选择本次资料</strong>
        <Space size={6} wrap>
          {type === "geology_map_review" && (
            <Tooltip
              title={
                presetReady
                  ? "恢复当前项目活动演示资料及默认参数，不启动计算。"
                  : "当前项目预设不完整或不兼容，请先补齐资料。"
              }
            >
              <Button
                aria-label="预设"
                size="small"
                disabled={disabled || evidenceOnly || !presetReady}
                onClick={() => {
                  onPresetRestore?.();
                  setMatchFeedback(
                    "已恢复当前项目预设资料及参数，请核对后生成执行计划。",
                  );
                }}
              >
                预设
              </Button>
            </Tooltip>
          )}
          <Tooltip title="重新按资料名称匹配并更新已有选项。多个匹配时保留当前选择并提示手动核对，不会直接运行。">
            <Button
              size="small"
              disabled={disabled || evidenceOnly}
              onClick={autoMatch}
            >
              按名称匹配资料
            </Button>
          </Tooltip>
        </Space>
      </div>
      {matchFeedback && <Alert type="info" showIcon title={matchFeedback} />}
      {type === "geology_map_review" && !presetReady && (
        <p className="agent-demo-hint">
          当前项目尚无完整可用的预设资料，可按格式要求选择自己的资料。
        </p>
      )}
      {type === "geology_age_correction" && (
        <Alert
          type="info"
          title="真实底图 / 演示录入错误"
          description="本案例核对地层名称、地区和辞书中的时代定义，修改副本中的少量时代属性。人工精修图用于独立对照，岩性和边界保留。"
        />
      )}
      {type === "geology_map_review" && (
        <Alert
          type="info"
          title="地质成果智能检查与修正 / 演示案例"
          description="先依据当前资料生成执行计划，再检索专家知识并检查地图。专家规则是算法可执行的条件；下方“知识依据”决定检索哪个知识分区，两者需相互对应。您批准具体建议后才修改地图。"
        />
      )}
      <div className="agent-demo-fields">
        {roles.map((role) => (
          <label key={role.key}>
            <span>{role.label}</span>
            <Select
              aria-label={role.label}
              showSearch
              allowClear
              optionFilterProp="label"
              disabled={disabled || (evidenceOnly && role.key !== "context")}
              placeholder={`选择${role.label}`}
              value={inputs[role.key]}
              status={
                inputIssues.some((message) =>
                  message.startsWith(role.label + "："),
                )
                  ? "error"
                  : undefined
              }
              options={matchingCandidates(type, role, candidates).map(
                (entry) => ({
                  value: entry.id,
                  label:
                    resources.find((item) => item.id === entry.id)?.name ??
                    entry.name,
                }),
              )}
              onChange={(id) => {
                const next = { ...inputs };
                if (id === undefined) delete next[role.key];
                else next[role.key] = id;
                onInputsChange(next);
              }}
            />
            {type === "geology_map_review" && (
              <small className="agent-demo-hint">
                {geologyRoleHelp[role.key]}
              </small>
            )}
          </label>
        ))}
      </div>
      {!!inputIssues.length && (
        <Alert
          type="error"
          showIcon
          title="当前资料不满足本场景要求"
          description={
            <ul>
              {inputIssues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          }
        />
      )}
      {type === "ecology_investigation" && (
        <>
          <div className="agent-demo-fields agent-demo-parameters">
            {(
              [
                ["early_date", "前期日期"],
                ["late_date", "后期日期"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                <span>{label}</span>
                <Input
                  type="date"
                  aria-label={label}
                  disabled={disabled || evidenceOnly}
                  value={
                    typeof parameters[key] === "string" ? parameters[key] : ""
                  }
                  onChange={(event) => setParameter(key, event.target.value)}
                />
              </label>
            ))}
            {(
              [
                ["red", "红光波段", 1],
                ["nir", "近红外波段", 2],
              ] as const
            ).map(([key, label, fallback]) => (
              <label key={key}>
                <span>{label}</span>
                <InputNumber
                  aria-label={String(label)}
                  disabled={disabled || evidenceOnly}
                  min={1}
                  max={bandLimit}
                  precision={0}
                  value={Number(parameters[String(key)] ?? fallback)}
                  onChange={(value) => setParameter(String(key), value)}
                />
              </label>
            ))}
            <label>
              <span>下降阈值</span>
              <InputNumber
                aria-label="下降阈值"
                disabled={disabled || evidenceOnly}
                min={-2}
                max={-0.000001}
                step={0.05}
                value={Number(parameters.decline_threshold ?? -0.15)}
                onChange={(value) => setParameter("decline_threshold", value)}
              />
            </label>
            <label>
              <span>最低有效覆盖率</span>
              <InputNumber
                aria-label="最低有效覆盖率"
                disabled={disabled || evidenceOnly}
                min={0}
                max={1}
                step={0.1}
                value={Number(parameters.min_coverage ?? 0.65)}
                onChange={(value) => setParameter("min_coverage", value)}
              />
            </label>
          </div>
          <p className="agent-demo-hint">
            日期、波段及阈值会随执行计划保存。选择补充观测版背景表后，可重新运行并对比调查建议。
          </p>
        </>
      )}
      {!!selected.length && (
        <div className="agent-demo-source-notes" aria-label="已选资料说明">
          {selected.map(({ role, name, description, fileFormat }) => (
            <div key={role.key}>
              <strong>
                {role.label} / {name}
              </strong>
              {fileFormat && <small>资料格式：{fileFormat}</small>}
              {description && <p>{description}</p>}
            </div>
          ))}
        </div>
      )}
      {!demoInputsReady(type, inputs, candidates) && (
        <Alert
          type="info"
          title="为每个角色选择资料后，生成可核对的执行计划。"
        />
      )}
    </section>
  );
}
