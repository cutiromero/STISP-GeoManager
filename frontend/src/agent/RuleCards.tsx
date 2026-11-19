import { Tag, Typography } from "antd";
import type { AgentWorkflow } from "../api/generated/types.gen";

type RuleBasis = {
  type?: string;
  statement?: string;
  gap?: string;
  refs?: { citation?: string; verification?: string }[];
};
type TrialRule = {
  id?: string;
  name?: string;
  element?: string;
  relation?: string;
  status?: string;
  basis?: RuleBasis;
};

function boundRules(workflow: AgentWorkflow) {
  return workflow.evidence
    .map((entry) => {
      const config = (entry as { ruleConfig?: { rule?: TrialRule } })
        .ruleConfig;
      const binding = (entry as { trialBinding?: { ruleVersion?: string } })
        .trialBinding;
      return binding && config?.rule
        ? { rule: config.rule, version: binding.ruleVersion ?? "", status: entry.status }
        : null;
    })
    .filter((item) => item !== null)
    .sort((left, right) =>
      String(left.rule.id).localeCompare(String(right.rule.id), "zh-CN", {
        numeric: true,
      }),
    );
}

function supportStatus(basis: RuleBasis | undefined) {
  const verified = (basis?.refs ?? [])
    .map((ref) => ref.verification)
    .filter(Boolean);
  if (verified.length) return verified.join("；");
  return basis?.type === "经验假设" ? "尚无文献，待专家确认" : "未列出文献";
}

/** The applied rule revisions and their evidence. */
export default function RuleCards({ workflow }: { workflow: AgentWorkflow }) {
  const rules = boundRules(workflow);
  if (!rules.length) return null;
  return (
    <details className="agent-rule-cards">
      <summary>
        本次采用的地质规则（{rules.length} 条）
      </summary>
      <ul>
        {rules.map(({ rule, version, status }) => (
          <li key={rule.id}>
            <div className="agent-rule-card-heading">
              <strong>
                {rule.id} {rule.name}
              </strong>
              <Tag>{version || "未标版本"}</Tag>
              <Tag color={status === "published" ? "blue" : "orange"}>
                {status === "published" ? "项目已发布" : "待专业核查"}
              </Tag>
            </div>
            <Typography.Text type="secondary">
              {[rule.element, rule.relation].filter(Boolean).join(" · ")}
            </Typography.Text>
            <dl>
              <dt>依据类型</dt>
              <dd>{rule.basis?.type ?? "未标注"}</dd>
              <dt>支撑状态</dt>
              <dd>{supportStatus(rule.basis)}</dd>
              {rule.basis?.gap && (
                <>
                  <dt>已知不足</dt>
                  <dd>{rule.basis.gap}</dd>
                </>
              )}
            </dl>
          </li>
        ))}
      </ul>
    </details>
  );
}
