import { Alert, Button, Select, Tag, Typography } from "antd";
import { useState } from "react";
import type { AgentFieldMappingReview } from "../api/generated/types.gen";

type Mapping = Record<string, Record<string, string | null>>;

function initialMapping(review: AgentFieldMappingReview): Mapping {
  return Object.fromEntries(
    review.roles.map((role) => [
      role.role,
      Object.fromEntries(
        role.targets.map((target) => [target.key, target.field ?? null]),
      ),
    ]),
  );
}

export default function FieldMappingReview({
  review,
  busy,
  onConfirm,
  compact = false,
  startAnalysis = false,
  onAdjustRoles,
}: {
  review: AgentFieldMappingReview;
  busy: boolean;
  onConfirm: (mapping: Mapping) => void;
  compact?: boolean;
  startAnalysis?: boolean;
  onAdjustRoles?: () => void;
}) {
  const [mapping, setMapping] = useState<Mapping>(() => initialMapping(review));
  const missing = review.roles.flatMap((role) =>
    role.targets
      .filter((target) => target.required && !mapping[role.role]?.[target.key])
      .map((target) => `${role.label}的“${target.label}”`),
  );
  return (
    <section className="agent-demo-form" aria-label="确认字段含义">
      <div className="agent-demo-form-heading">
        <strong>{startAnalysis ? "核对资料与字段" : "确认字段含义"}</strong>
        <Tag color={review.modelMode === "real" ? "blue" : "default"}>
          {review.modelMode === "real" ? "智能体判断" : "按字段名推荐"}
        </Tag>
      </div>
      {!compact && (
        <p className="agent-demo-hint">
          平台会按您确认的对应关系生成工作副本，原始文件不变。不需要的字段可以留空；带“必需”的字段必须选择。
          {startAnalysis &&
            "确认后将自动开始检查与分析，修改建议仍须单独批准。"}
        </p>
      )}
      {review.questions.map((question) => (
        <Alert key={question} type="warning" showIcon title={question} />
      ))}
      {review.roles.map((role) => (
        <div key={role.role} className="agent-demo-mapping">
          <Typography.Text strong>
            {role.label} · {role.fileName}
          </Typography.Text>
          {role.targets.map((target) => (
            <label key={target.key} className="agent-workflow-parameter">
              <span>
                {target.label}
                {target.required && <Tag color="red">必需</Tag>}
              </span>
              <Select
                aria-label={`${role.label}的${target.label}`}
                allowClear={!target.required}
                disabled={busy}
                value={mapping[role.role]?.[target.key] ?? undefined}
                placeholder="不对应"
                options={role.fields.map((field) => ({
                  value: field,
                  label: field,
                }))}
                onChange={(field: string | undefined) =>
                  setMapping((old) => ({
                    ...old,
                    [role.role]: {
                      ...old[role.role],
                      [target.key]: field ?? null,
                    },
                  }))
                }
              />
              {target.field &&
                (compact ? (
                  <details>
                    <summary>判断依据</summary>
                    <Typography.Text type="secondary">
                      {target.reason}
                    </Typography.Text>
                  </details>
                ) : (
                  <Typography.Text type="secondary">
                    {target.reason}
                  </Typography.Text>
                ))}
            </label>
          ))}
        </div>
      ))}
      {missing.length > 0 && (
        <Alert
          type="error"
          showIcon
          title={`请先选择：${missing.join("、")}`}
        />
      )}
      <Button
        type="primary"
        loading={busy}
        disabled={missing.length > 0}
        onClick={() => onConfirm(mapping)}
      >
        {startAnalysis ? "确认资料并开始分析" : "确认字段并继续"}
      </Button>
      {onAdjustRoles && (
        <Button disabled={busy} onClick={onAdjustRoles}>
          调整资料角色
        </Button>
      )}
    </section>
  );
}
