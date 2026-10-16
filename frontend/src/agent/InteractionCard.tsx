import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Form,
  Input,
  Radio,
  Space,
  Tag,
} from "antd";
import { CheckOutlined, MessageOutlined } from "@ant-design/icons";
import { useRef, useState } from "react";
import { agentApi } from "../api/agent";
import type {
  AgentInteraction,
  AgentInteractionUpdate,
  AgentRun,
} from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";

type Answers = NonNullable<AgentInteractionUpdate["answers"]>;
type Props = {
  run: AgentRun;
  disabled?: boolean;
  onChanged: (run: AgentRun) => void;
};

function answerLabel(
  card: AgentInteraction,
  key: string,
  value: string | string[],
) {
  const question = card.questions.find((item) => item.key === key);
  const values = Array.isArray(value) ? value : [value];
  return values
    .map(
      (item) =>
        question?.options?.find((option) => option.value === item)?.label ??
        item,
    )
    .join("、");
}

function AnsweredQuestions({ cards }: { cards: AgentInteraction[] }) {
  if (!cards.length) return null;
  return (
    <Collapse
      className="agent-interaction-history"
      ghost
      size="small"
      items={cards.map((card) => ({
        key: card.questionId,
        label: (
          <Space size={8}>
            <CheckOutlined />
            <span>{card.title}</span>
            <span className="agent-muted">
              {card.status === "cancelled" ? "已取消" : "已补充"}
            </span>
          </Space>
        ),
        children: (
          <div className="agent-interaction-receipt">
            <p>{card.reason}</p>
            {Object.entries(card.answer?.answers ?? {}).map(([key, value]) => (
              <p key={key}>
                <strong>
                  {card.questions.find((item) => item.key === key)?.label ??
                    key}
                  ：
                </strong>
                {answerLabel(card, key, value)}
              </p>
            ))}
            {card.answer?.text && <p>补充说明：{card.answer.text}</p>}
            {card.status === "cancelled" && (
              <p>已停止等待，后续操作不会继续启动。</p>
            )}
          </div>
        ),
      }))}
    />
  );
}

function PendingQuestion({
  card,
  runId,
  disabled,
  onChanged,
}: {
  card: AgentInteraction;
  runId: number;
  disabled?: boolean;
  onChanged: Props["onChanged"];
}) {
  const [form] = Form.useForm<Answers>();
  const [supplementaryText, setSupplementaryText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const defaults: Answers = {};
  for (const question of card.questions) {
    if (question.defaultValue != null)
      defaults[question.key] = question.defaultValue;
  }
  const submit = async (
    action: "answer" | "cancel",
    answers: Answers = {},
    text = "",
  ) => {
    if (inFlight.current || disabled) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    const fingerprint = JSON.stringify({ action, answers, text });
    if (retry.current?.fingerprint !== fingerprint) {
      retry.current = { fingerprint, key: createUuid() };
    }
    try {
      onChanged(
        await agentApi.answerInteraction(runId, {
          action,
          questionId: card.questionId,
          revision: card.revision,
          submissionKey: retry.current.key,
          answers,
          text,
        }),
      );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "回答未送达，请重试。当前问题已保留。",
      );
      // A lost response or another tab may already have advanced this task.
      try {
        const latest = await agentApi.poll(runId);
        onChanged(latest.run);
      } catch {
        // Keep the visible question and retry key until authorization refresh.
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return (
    <section
      className="agent-interaction-card"
      aria-label={
        card.kind === "review" ? "等待您审核的问题" : "等待您回答的问题"
      }
      data-question-id={card.questionId}
    >
      <div className="agent-interaction-heading">
        <MessageOutlined />
        <strong>{card.title}</strong>
        <Tag color="blue">
          {card.kind === "review" ? "等待您审核" : "等待您回答"}
        </Tag>
      </div>
      <p className="agent-interaction-reason">{card.reason}</p>
      {card.plan && (
        <p className="agent-interaction-plan">接下来的安排：{card.plan}</p>
      )}
      {error && <Alert type="error" title={error} showIcon />}
      <Form
        form={form}
        layout="vertical"
        initialValues={defaults}
        disabled={busy || disabled}
        onFinish={(values) => {
          const answers: Answers = {};
          for (const question of card.questions) {
            const value = values[question.key];
            if (value !== undefined) answers[question.key] = value;
          }
          void submit("answer", answers, supplementaryText);
        }}
      >
        {card.questions.map((question) => (
          <Form.Item
            key={question.key}
            name={question.key}
            label={question.label}
            rules={[
              {
                validator: async (_, value) => {
                  const supplemental = supplementaryText.trim();
                  const missing = Array.isArray(value)
                    ? !value.length
                    : !String(value ?? "").trim();
                  if (
                    question.required &&
                    missing &&
                    !(card.kind === "input" && supplemental)
                  ) {
                    throw new Error("请作答，或在下方补充需要模型理解的信息。");
                  }
                },
              },
            ]}
          >
            {question.type === "text" ? (
              <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
            ) : question.type === "multiple" ? (
              <Checkbox.Group className="agent-interaction-options">
                {(question.options ?? []).map((option) => (
                  <Checkbox key={option.value} value={option.value}>
                    <span>{option.label}</span>
                    {option.description && <small>{option.description}</small>}
                  </Checkbox>
                ))}
              </Checkbox.Group>
            ) : (
              <Radio.Group className="agent-interaction-options">
                {(question.options ?? []).map((option) => (
                  <Radio key={option.value} value={option.value}>
                    <span>{option.label}</span>
                    {option.description && <small>{option.description}</small>}
                  </Radio>
                ))}
              </Radio.Group>
            )}
          </Form.Item>
        ))}
        <Form.Item label="补充说明（可选）">
          <Input.TextArea
            value={supplementaryText}
            onChange={(event) => setSupplementaryText(event.target.value)}
            placeholder="可以补充条件、纠正前面的信息，或说明希望怎样处理。"
            autoSize={{ minRows: 2, maxRows: 5 }}
          />
        </Form.Item>
        <div className="agent-interaction-actions">
          <Button type="primary" htmlType="submit" loading={busy}>
            确认并继续
          </Button>
          <Button
            onClick={() => void submit("cancel")}
            disabled={busy || disabled}
          >
            取消等待
          </Button>
          <span>默认值需要您确认后才会发送。</span>
        </div>
      </Form>
    </section>
  );
}

export default function InteractionCard({ run, disabled, onChanged }: Props) {
  const current = run.interaction;
  const history = (run.interactionHistory ?? []).filter(
    (card) => card.status !== "pending",
  );
  return (
    <div className="agent-interaction">
      <AnsweredQuestions cards={history} />
      {current?.status === "pending" &&
        ["waiting_input", "waiting_review"].includes(run.status) && (
          <PendingQuestion
            key={`${current.questionId}:${current.revision}`}
            card={current}
            runId={run.id}
            disabled={disabled}
            onChanged={onChanged}
          />
        )}
    </div>
  );
}
