import {
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import { Alert, Button, Input } from "antd";
import { useId, useRef, useState } from "react";
import { useComputeText } from "../compute/ui";
import { object } from "./hermesConversation";

export type HermesControl = {
  kind: "clarify" | "approval";
  request_id: string;
  execution_generation: number;
  question: string;
  choices: string[];
  multiSelect: boolean;
};

export function pendingControl(value: unknown): HermesControl | undefined {
  const event = object(value);
  const kind =
    event.kind ??
    (event.event === "clarify.request"
      ? "clarify"
      : event.event === "approval.request"
        ? "approval"
        : undefined);
  if (
    (kind !== "clarify" && kind !== "approval") ||
    typeof event.prompt_id !== "string" ||
    typeof event.execution_generation !== "number"
  )
    return;
  const question =
    kind === "clarify" ? event.question : event.description || event.command;
  return {
    kind,
    request_id: event.prompt_id,
    execution_generation: event.execution_generation,
    question: typeof question === "string" ? question : "",
    choices: Array.isArray(event.choices)
      ? [
          ...new Set(
            event.choices.filter(
              (choice): choice is string =>
                typeof choice === "string" &&
                (kind === "clarify" || choice === "once" || choice === "deny"),
            ),
          ),
        ]
      : [],
    multiSelect: kind === "clarify" && event.multi_select === true,
  };
}

export default function HermesQuestion({
  control,
  remaining,
  onReply,
}: {
  control: HermesControl;
  remaining: number;
  onReply: (answer: string) => Promise<string | undefined>;
}) {
  const ui = useComputeText();
  const heading = useId();
  const [selected, setSelected] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const inFlight = useRef(false);
  const clarify = control.kind === "clarify";
  const label = clarify ? ui("问题", "Question") : ui("操作确认", "Approval");
  const question =
    control.question ||
    (clarify
      ? ui("请补充信息", "Add information")
      : ui("请确认操作", "Confirm operation"));
  const answers = [...selected, ...(custom.trim() ? [custom.trim()] : [])];
  const answer = control.multiSelect
    ? JSON.stringify(answers)
    : (answers[0] ?? "");
  const replyLabel = clarify ? ui("发送", "Send") : ui("确认", "Confirm");

  async function reply(value: string) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    try {
      setError(await onReply(value));
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  if (collapsed) {
    return (
      <div className="hermes-question-slot is-collapsed">
        <Button
          icon={<QuestionCircleOutlined aria-hidden />}
          onClick={() => setCollapsed(false)}
        >
          {ui("查看待答问题", "Show pending question")}
          {remaining > 1 && ` (${remaining})`}
        </Button>
      </div>
    );
  }
  return (
    <section
      className="hermes-question-slot hermes-question"
      aria-labelledby={heading}
    >
      <header>
        <span>
          <QuestionCircleOutlined aria-hidden /> {label}
        </span>
        {remaining > 1 && (
          <small>{ui(`${remaining} 项待处理`, `${remaining} pending`)}</small>
        )}
        <Button
          type="text"
          size="small"
          icon={<CloseOutlined />}
          aria-label={ui("收起问题", "Collapse question")}
          disabled={sending}
          onClick={() => setCollapsed(true)}
        />
      </header>
      <div className="hermes-question-body">
        <h3 id={heading}>{question}</h3>
        {!!control.choices.length && (
          <div
            className="hermes-question-choices"
            role="group"
            aria-label={
              control.multiSelect
                ? ui("可多选", "Multiple choices")
                : ui("选项", "Choices")
            }
          >
            {control.choices.map((choice) => {
              const checked = selected.includes(choice);
              return (
                <Button
                  key={choice}
                  type="text"
                  className="hermes-question-choice"
                  aria-pressed={checked}
                  disabled={sending}
                  onClick={() => {
                    if (!control.multiSelect) setCustom("");
                    setSelected(
                      checked
                        ? selected.filter((item) => item !== choice)
                        : control.multiSelect
                          ? [...selected, choice]
                          : [choice],
                    );
                  }}
                >
                  <span className="hermes-question-mark" aria-hidden="true">
                    {checked && <CheckOutlined />}
                  </span>
                  {clarify
                    ? choice
                    : choice === "once"
                      ? ui("批准一次", "Approve once")
                      : ui("拒绝", "Deny")}
                </Button>
              );
            })}
          </div>
        )}
      </div>
      {error && <Alert type="error" title={error} />}
      <footer>
        {clarify && (
          <Input
            prefix={<EditOutlined />}
            variant="borderless"
            aria-label={ui("自行填写回复", "Write your own reply")}
            placeholder={ui("自行填写回复", "Write your own reply")}
            value={custom}
            disabled={sending}
            maxLength={12000}
            onChange={(event) => {
              setCustom(event.target.value);
              if (!control.multiSelect) setSelected([]);
            }}
            onPressEnter={(event) => {
              if (event.nativeEvent.isComposing || !answers.length) return;
              event.preventDefault();
              void reply(answer);
            }}
          />
        )}
        <div className="hermes-question-actions">
          {clarify && (
            <Button
              autoInsertSpace={false}
              disabled={sending}
              onClick={() => void reply("")}
            >
              {ui("跳过", "Skip")}
            </Button>
          )}
          <Button
            type="primary"
            autoInsertSpace={false}
            aria-label={replyLabel}
            disabled={sending || !answers.length}
            loading={sending}
            onClick={() => void reply(answer)}
          >
            {replyLabel}
          </Button>
        </div>
      </footer>
    </section>
  );
}
