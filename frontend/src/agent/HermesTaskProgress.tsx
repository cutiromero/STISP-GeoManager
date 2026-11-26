import {
  ApartmentOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  ExpandOutlined,
  LoadingOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Button, Drawer, Progress, Tabs } from "antd";
import { useId, useState } from "react";
import type { HermesMessage } from "../api/generated";
import { useComputeText } from "../compute/ui";
import { object, toolPayload } from "./hermesConversation";

type Status = "pending" | "in_progress" | "completed" | "cancelled";
type Task = { id: string; title: string; status: Status; parent?: string };
export type TodoPlan = { revision: number; tasks: Task[] };
type Step = { id: string; title: string; direction: string; after: string[] };
export type ResearchPath = { name: string; versionId: number; steps: Step[] };

const statusIcons = {
  pending: ClockCircleOutlined,
  in_progress: LoadingOutlined,
  completed: CheckCircleOutlined,
  cancelled: CloseCircleOutlined,
};

export function todoPlan(value: unknown): TodoPlan | undefined {
  const content = toolPayload(value);
  if (!Array.isArray(content.todos) || typeof content.revision !== "number")
    return;
  const tasks = content.todos.flatMap((item): Task[] => {
    const { id, content: title, status, parent } = object(item);
    if (
      typeof id !== "string" ||
      typeof title !== "string" ||
      (status !== "pending" &&
        status !== "in_progress" &&
        status !== "completed" &&
        status !== "cancelled")
    )
      return [];
    return [
      {
        id,
        title,
        status,
        parent: typeof parent === "string" ? parent : undefined,
      },
    ];
  });
  return { revision: content.revision, tasks };
}

export function researchPath(value: unknown): ResearchPath | undefined {
  const { versionId, name, suggestedSteps } = toolPayload(value);
  if (
    typeof versionId !== "number" ||
    typeof name !== "string" ||
    !Array.isArray(suggestedSteps)
  )
    return;
  const steps = suggestedSteps.flatMap((item): Step[] => {
    const { id, title, direction, after } = object(item);
    if (typeof id !== "string" || typeof title !== "string") return [];
    return [
      {
        id,
        title,
        direction: typeof direction === "string" ? direction : "",
        after: Array.isArray(after)
          ? after.filter((key): key is string => typeof key === "string")
          : [],
      },
    ];
  });
  return { name, versionId, steps };
}

export function latestTaskProgress(messages: HermesMessage[]) {
  let plan: TodoPlan | undefined;
  let path: ResearchPath | undefined;
  for (
    let index = messages.length - 1;
    index >= 0 && (!plan || !path);
    index--
  ) {
    const message = messages[index];
    if (message?.role !== "tool") continue;
    if (!plan && message.tool_name === "todo_list")
      plan = todoPlan(message.content);
    if (!path && message.tool_name === "get_research_workflow")
      path = researchPath(message.content);
  }
  return { plan, path };
}

type ProgressNode = {
  id: string;
  title: string;
  status?: Status;
  description?: string;
  parent?: string;
  after?: string[];
};

export default function HermesTaskProgress({
  plan,
  path,
  draftTitle,
}: {
  plan?: TodoPlan;
  path?: ResearchPath;
  draftTitle?: string;
}) {
  const ui = useComputeText();
  const tabId = useId();
  const [view, setView] = useState<string>();
  const [expanded, setExpanded] = useState(false);
  const [selection, setSelection] = useState<{ group: string; id: string }>();
  const tasks = plan?.tasks ?? [];
  const flowTitle = path?.name ?? draftTitle;
  const choices = [
    ...(tasks.length
      ? [{ key: "tasks", label: ui("任务清单", "Task list") }]
      : []),
    ...(flowTitle
      ? [{ key: "workflow", label: ui("业务流", "Workflow") }]
      : []),
  ];
  const active =
    choices.find(({ key }) => key === view)?.key ?? choices[0]?.key;
  if (!active) return null;
  const showTasks = active === "tasks";
  const group = showTasks
    ? active
    : `workflow:${path?.versionId ?? draftTitle}`;
  const nodes: ProgressNode[] = showTasks
    ? tasks
    : (path?.steps ?? []).map((step) => ({
        ...step,
        description: step.direction,
      }));
  const running = nodes.find((node) => node.status === "in_progress");
  const selected =
    (selection?.group === group
      ? nodes.find((node) => node.id === selection.id)
      : undefined) ??
    running ??
    nodes[0];
  const select = (id: string) => setSelection({ group, id });
  const completed = tasks.filter((task) => task.status === "completed").length;
  const statusLabels = {
    pending: ui("待处理", "Pending"),
    in_progress: ui("进行中", "In progress"),
    completed: ui("已完成", "Completed"),
    cancelled: ui("已取消", "Cancelled"),
  };
  const title = ui("任务进度", "Task progress");
  const tabItems = choices.map((choice) => ({
    ...choice,
    children:
      choice.key === active ? (
        <div className="hermes-progress-content">
          {!showTasks && <h3>{flowTitle}</h3>}
          {showTasks && (
            <div className="hermes-progress-count">
              <div>
                <span>{ui("节点完成", "Nodes completed")}</span>
                <strong>
                  {completed} / {tasks.length}
                </strong>
              </div>
              <Progress
                percent={Math.round((completed / tasks.length) * 100)}
                showInfo={false}
                size="small"
                strokeColor="#5b8b7c"
                aria-label={ui("节点完成进度", "Node completion progress")}
              />
            </div>
          )}
          <Nodes
            nodes={nodes}
            selected={selected}
            statuses={statusLabels}
            onSelect={select}
          />
          {selected && (
            <NodeDetail
              node={selected}
              status={selected.status && statusLabels[selected.status]}
              nodes={nodes}
              onSelect={select}
            />
          )}
        </div>
      ) : null,
  }));
  return (
    <aside className="hermes-progress-rail" aria-label={title}>
      <header>
        <h2>
          <ApartmentOutlined aria-hidden /> {title}
        </h2>
        <Button
          type="text"
          size="small"
          icon={<ExpandOutlined />}
          aria-label={ui("展开任务进度", "Expand task progress")}
          aria-expanded={expanded}
          onClick={() => setExpanded(true)}
        />
      </header>
      <div className="hermes-progress-inline">
        <Tabs
          id={`${tabId}-inline`}
          size="small"
          activeKey={active}
          items={tabItems}
          onChange={setView}
        />
      </div>
      <Drawer
        title={title}
        open={expanded}
        size="large"
        styles={{ wrapper: { width: "min(100%, 960px)" } }}
        onClose={() => setExpanded(false)}
        destroyOnHidden
        classNames={{ body: "hermes-progress-expanded" }}
      >
        <Tabs
          id={`${tabId}-expanded`}
          size="small"
          activeKey={active}
          items={tabItems}
          onChange={setView}
        />
      </Drawer>
    </aside>
  );
}

function Nodes({
  nodes,
  selected,
  statuses,
  onSelect,
}: {
  nodes: ProgressNode[];
  selected?: ProgressNode;
  statuses: Record<Status, string>;
  onSelect: (id: string) => void;
}) {
  const ui = useComputeText();
  if (!nodes.length)
    return (
      <p className="hermes-progress-empty">
        {ui("等待读取业务步骤", "Waiting for workflow steps")}
      </p>
    );
  return (
    <ol className="hermes-progress-nodes">
      {nodes.map((node) => {
        const Icon = node.status
          ? statusIcons[node.status]
          : UnorderedListOutlined;
        return (
          <li key={node.id} data-subtask={node.parent ? true : undefined}>
            <button
              type="button"
              className="hermes-progress-node"
              data-status={node.status}
              aria-pressed={node.id === selected?.id}
              onClick={() => onSelect(node.id)}
            >
              <span className="hermes-progress-icon" aria-hidden="true">
                <Icon />
              </span>
              <span>
                <strong>{node.title}</strong>
                <small>
                  {node.status
                    ? statuses[node.status]
                    : ui("建议步骤", "Suggested step")}
                </small>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function NodeDetail({
  node,
  status,
  nodes,
  onSelect,
}: {
  node: ProgressNode;
  status?: string;
  nodes: ProgressNode[];
  onSelect: (id: string) => void;
}) {
  const ui = useComputeText();
  const dependencies = nodes.filter(({ id }) => node.after?.includes(id));
  const parent = nodes.find(({ id }) => id === node.parent);
  const children = nodes.filter(({ parent }) => parent === node.id);
  const groups = [
    { label: ui("前置步骤", "Prerequisites"), nodes: dependencies },
    { label: ui("上级任务", "Parent task"), nodes: parent ? [parent] : [] },
    { label: ui("子任务", "Subtasks"), nodes: children },
  ];
  return (
    <section
      className="hermes-node-detail"
      aria-label={ui("节点详情", "Node details")}
    >
      <h3>{node.title}</h3>
      {status && <p>{status}</p>}
      {node.description && node.description !== node.title && (
        <p>{node.description}</p>
      )}
      {groups
        .filter((group) => group.nodes.length)
        .map((group) => (
          <div key={group.label}>
            <small>{group.label}</small>
            {group.nodes.map((related) => (
              <Button
                key={related.id}
                size="small"
                type="link"
                onClick={() => onSelect(related.id)}
              >
                {related.title}
              </Button>
            ))}
          </div>
        ))}
    </section>
  );
}
