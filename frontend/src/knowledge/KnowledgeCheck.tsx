import { Alert, Button, Input, Space, Tag } from "antd";
import { useEffect, useState } from "react";
import type {
  KnowledgeCheckResult,
  KnowledgeEntry,
} from "../api/generated/types.gen";
import { knowledgeApi } from "../api/knowledge";

function blankFacts(entry: KnowledgeEntry) {
  if (entry.ruleKind === "mineral_equilibrium")
    return { minerals: [], equilibrium: null, system: "" };
  if (entry.ruleKind === "numeric_range") {
    const field =
      typeof entry.ruleConfig.field === "string"
        ? entry.ruleConfig.field
        : "field";
    return { values: { [field]: null }, units: { [field]: "" } };
  }
  return { fields: [] };
}
export default function KnowledgeCheck({ entry }: { entry: KnowledgeEntry }) {
  const [facts, setFacts] = useState("{}");
  const [result, setResult] = useState<KnowledgeCheckResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setResult(null);
    setError("");
  }, [entry.id]);
  async function check() {
    setError("");
    setResult(null);
    try {
      const parsed: unknown = JSON.parse(facts);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error(
          "请填写一个事实对象，例如包含实际矿物名称或观测数值的 JSON。",
        );
      setBusy(true);
      setResult(
        await knowledgeApi.check({
          facts: parsed as Record<string, unknown>,
          entryIds: [entry.id],
        }),
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="knowledge-check">
      <h3>用实际观测核查</h3>
      <p>填写事实后核查这条规则。条件不足时会列出需补充的信息。</p>
      <Input.TextArea
        aria-label="核查事实 JSON"
        value={facts}
        onChange={(event) => {
          setFacts(event.target.value);
          setResult(null);
        }}
        rows={7}
        spellCheck={false}
      />
      <Space wrap>
        <Button type="primary" loading={busy} onClick={() => void check()}>
          核查条件
        </Button>
        <Button
          onClick={() => {
            setFacts(JSON.stringify(blankFacts(entry), null, 2));
            setResult(null);
          }}
        >
          填入空白模板
        </Button>
      </Space>
      {error && <Alert type="error" showIcon title={error} />}
      {result && (
        <div aria-live="polite">
          <p>已核查 {result.checked} 条规则</p>
          {result.findings.map((finding) => (
            <Alert
              key={finding.entryId}
              showIcon
              type={
                finding.status === "conflict"
                  ? "warning"
                  : finding.status === "pass"
                    ? "success"
                    : "info"
              }
              title={
                <>
                  {
                    {
                      conflict: "发现冲突",
                      pass: "本条规则通过",
                      needs_context: "需要补充条件",
                    }[finding.status]
                  }{" "}
                  <Tag>v{finding.revision}</Tag>
                </>
              }
              description={finding.detail}
            />
          ))}
        </div>
      )}
    </section>
  );
}
