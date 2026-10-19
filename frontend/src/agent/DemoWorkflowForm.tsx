import { Alert, Button, Input, InputNumber, Select, Tooltip } from "antd";
import type {
  AgentResource,
  ComputeCandidate,
} from "../api/generated/types.gen";

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
      match: /制图范围|coverage/i,
    },
    {
      key: "rules",
      label: "专家规则",
      kind: "table",
      match: /专家规则|review.*rules/i,
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

function matchingCandidates(role: Role, candidates: ComputeCandidate[]) {
  return candidates.filter((candidate) => candidate.kind === role.kind);
}

export function demoInputsReady(
  type: DemoWorkflowType,
  inputs: Record<string, number>,
) {
  return demoRoles[type].every((role) => (inputs[role.key] ?? 0) > 0);
}

export default function DemoWorkflowForm({
  type,
  candidates,
  resources,
  inputs,
  parameters,
  disabled,
  evidenceOnly = false,
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
  onInputsChange: (value: Record<string, number>) => void;
  onParametersChange: (value: Record<string, unknown>) => void;
}) {
  const roles = demoRoles[type];
  const selected = roles.flatMap((role) => {
    const resource = resources.find((entry) => entry.id === inputs[role.key]);
    const candidate = candidates.find((entry) => entry.id === inputs[role.key]);
    return candidate
      ? [
          {
            role,
            name: resource?.name ?? candidate.name,
            description: resource?.description ?? "",
          },
        ]
      : [];
  });
  const setParameter = (key: string, value: unknown) =>
    onParametersChange({ ...parameters, [key]: value });
  const autoMatch = () => {
    const next = { ...inputs };
    for (const role of roles) {
      if (next[role.key]) continue;
      const found = matchingCandidates(role, candidates).filter((entry) =>
        role.match.test(
          resources.find((item) => item.id === entry.id)?.name ?? entry.name,
        ),
      );
      if (found.length === 1) next[role.key] = found[0]!.id;
    }
    onInputsChange(next);
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
        <Tooltip title="根据资料名称填入唯一匹配的建议，不会直接运行。请在运行前核对；也可逐项手动选择。">
          <Button
            size="small"
            disabled={disabled || evidenceOnly}
            onClick={autoMatch}
          >
            按名称匹配资料
          </Button>
        </Tooltip>
      </div>
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
          description="先检查地图并形成有知识依据的建议。您选择并批准建议后，再生成修正后地质图、修改范围和检查报告。"
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
              options={matchingCandidates(role, candidates).map((entry) => ({
                value: entry.id,
                label:
                  resources.find((item) => item.id === entry.id)?.name ??
                  entry.name,
              }))}
              onChange={(id) => {
                const next = { ...inputs };
                if (id === undefined) delete next[role.key];
                else next[role.key] = id;
                onInputsChange(next);
              }}
            />
          </label>
        ))}
      </div>
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
          {selected.map(({ role, name, description }) => (
            <div key={role.key}>
              <strong>
                {role.label} / {name}
              </strong>
              {description && <p>{description}</p>}
            </div>
          ))}
        </div>
      )}
      {!demoInputsReady(type, inputs) && (
        <Alert
          type="info"
          title="为每个角色选择资料后，生成可核对的执行计划。"
        />
      )}
    </section>
  );
}
