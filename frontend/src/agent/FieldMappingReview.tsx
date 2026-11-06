import { Alert, Button, Checkbox, Drawer, Select, Tag, Typography } from "antd";
import { useState } from "react";
import type {
  AgentFieldMappingReview,
  AgentResearchIntent,
} from "../api/generated/types.gen";

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
  workspace = false,
  inputs = [],
}: {
  review: AgentFieldMappingReview;
  busy: boolean;
  onConfirm: (mapping: Mapping, applyRules?: boolean) => void;
  compact?: boolean;
  startAnalysis?: boolean;
  onAdjustRoles?: () => void;
  workspace?: boolean;
  inputs?: AgentResearchIntent["inputSummary"];
}) {
  const [applyRules, setApplyRules] = useState(true);
  const [mapping, setMapping] = useState<Mapping>(() => initialMapping(review));
  const [editing, setEditing] = useState<string | undefined>(() =>
    workspace
      ? review.roles.find((role) =>
          role.targets.some((t) => t.required && !t.field),
        )?.role
      : undefined,
  );
  const missing = review.roles.flatMap((role) =>
    role.targets
      .filter((target) => target.required && !mapping[role.role]?.[target.key])
      .map((target) => `${role.label}的“${target.label}”`),
  );
  const roleFields = (role: AgentFieldMappingReview["roles"][number]) => (
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
                [role.role]: { ...old[role.role], [target.key]: field ?? null },
              }))
            }
          />
          {target.field &&
            (compact && !workspace ? (
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
  );
  const rows = inputs.length
    ? inputs.map((input) => ({ ...input, fileName: input.name }))
    : review.roles.map((role) => ({
        role: role.role,
        label: role.label,
        name: role.fileName,
        fileName: role.fileName,
        resourceId: role.resourceId,
      }));
  const selected = review.roles.find((role) => role.role === editing);
  return (
    <section
      className={workspace ? "logic-input-review" : "agent-demo-form"}
      aria-label="确认字段含义"
    >
      {!workspace && (
        <div className="agent-demo-form-heading">
          <strong>{startAnalysis ? "核对资料与字段" : "确认字段含义"}</strong>
          <Tag color={review.modelMode === "real" ? "blue" : "default"}>
            {review.modelMode === "real" ? "智能体判断" : "按字段名推荐"}
          </Tag>
        </div>
      )}
      {workspace ? (
        <p className="logic-description">
          请核对资料与字段，仅在对应关系不正确时修改。原始资料保持不变。
        </p>
      ) : (
        !compact && (
          <p className="agent-demo-hint">
            平台会按您确认的对应关系生成工作副本，原始文件不变。不需要的字段可以留空；带“必需”的字段必须选择。
            {startAnalysis &&
              "本次一次核对资料角色、字段及执行范围，随后自动检查、复查并生成成果。"}
          </p>
        )
      )}
      {review.questions.map((question) => (
        <Alert key={question} type="warning" showIcon title={question} />
      ))}
      {workspace ? (
        <div className="logic-input-list">
          {rows.map((input) => {
            const role = review.roles.find((item) => item.role === input.role);
            const incomplete = role?.targets.some(
              (target) => target.required && !mapping[role.role]?.[target.key],
            );
            return (
              <div
                className="logic-input-row"
                key={`${input.role}:${input.resourceId}`}
              >
                <div>
                  <strong>{input.name}</strong>
                  <small>
                    {role
                      ? role.targets
                          .filter((t) => mapping[role.role]?.[t.key])
                          .map(
                            (t) => `${t.label}：${mapping[role.role]?.[t.key]}`,
                          )
                          .join(" / ")
                      : "本次已匹配资料"}
                  </small>
                </div>
                <span>
                  {input.label}
                  {incomplete && (
                    <small className="logic-required">需选择必需字段</small>
                  )}
                </span>
                {role ? (
                  <Button
                    type="link"
                    size="small"
                    aria-label={`修改${role.label}字段`}
                    onClick={() => setEditing(role.role)}
                  >
                    修改
                  </Button>
                ) : (
                  <span className="logic-muted">无需字段配置</span>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        review.roles.map(roleFields)
      )}
      {missing.length > 0 && (
        <Alert
          type="error"
          showIcon
          title={`请先选择：${missing.join("、")}`}
          action={
            workspace ? (
              <Button
                size="small"
                onClick={() =>
                  setEditing(
                    review.roles.find((r) =>
                      r.targets.some(
                        (t) => t.required && !mapping[r.role]?.[t.key],
                      ),
                    )?.role,
                  )
                }
              >
                选择字段
              </Button>
            ) : undefined
          }
        />
      )}
      {startAnalysis && (
        <div className="logic-input-authorization">
          <Checkbox
            checked={applyRules}
            disabled={busy}
            onChange={(e) => setApplyRules(e.target.checked)}
          >
            自动执行已核验的规则建议（仅工作副本）
          </Checkbox>
          <small>待裁定、例外和冲突对象保留；取消勾选可先审阅处置建议。</small>
        </div>
      )}
      <div
        className={workspace ? "logic-input-actions" : "agent-research-actions"}
      >
        <Button
          type="primary"
          loading={busy}
          disabled={missing.length > 0}
          onClick={() =>
            startAnalysis ? onConfirm(mapping, applyRules) : onConfirm(mapping)
          }
        >
          {workspace
            ? "确认并开始"
            : startAnalysis
              ? "确认资料并开始分析"
              : "确认字段并继续"}
        </Button>
        {onAdjustRoles && (
          <Button disabled={busy} onClick={onAdjustRoles}>
            调整资料角色
          </Button>
        )}
      </div>
      {workspace && (
        <Drawer
          className="logic-field-drawer"
          title="修改字段对应"
          open={Boolean(selected)}
          size={560}
          onClose={() => setEditing(undefined)}
          styles={{ wrapper: { maxWidth: "100%" } }}
          footer={
            <Button
              type="primary"
              disabled={
                busy ||
                Boolean(
                  selected?.targets.some(
                    (t) => t.required && !mapping[selected.role]?.[t.key],
                  ),
                )
              }
              onClick={() => setEditing(undefined)}
            >
              保存对应关系
            </Button>
          }
        >
          {selected && roleFields(selected)}
        </Drawer>
      )}
    </section>
  );
}
