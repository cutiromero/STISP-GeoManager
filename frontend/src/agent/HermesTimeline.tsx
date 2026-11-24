import {
  ApiOutlined,
  CompassOutlined,
  DatabaseOutlined,
  DownOutlined,
  FileSearchOutlined,
  GlobalOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { Popover } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { HermesMessage } from "../api/generated";
import { useComputeText } from "../compute/ui";
import SafeMarkdown from "./SafeMarkdown";
import {
  object,
  toolPayload,
  type Activity,
  type ToolActivity,
} from "./hermesConversation";
import "./hermes-timeline.css";

const operations: Record<string, [string, string]> = {
  search_knowledge: ["检索知识", "Searched knowledge"],
  read_knowledge_document: ["阅读知识文档", "Read knowledge documents"],
  check_knowledge_constraints: ["核对知识规则", "Checked knowledge rules"],
  search_resources: ["查找项目资料", "Searched project data"],
  summarize_resource_catalog: ["统计资料目录", "Summarized data catalog"],
  describe_resource: ["查看资料详情", "Inspected data"],
  read_rows: ["读取数据样本", "Read data samples"],
  summarize_data: ["统计数据", "Summarized data"],
  aggregate_data: ["分组统计", "Aggregated data"],
  get_map_data_profile: ["查看地图资料", "Inspected map data"],
  get_platform_link: ["生成平台入口", "Created a platform link"],
  list_compute_algorithms: ["查找算子", "Searched operators"],
  submit_research_compute: ["提交算子", "Submitted an operator"],
  get_research_compute: ["查询计算进度", "Checked compute progress"],
  read_research_output: ["读取计算成果", "Read compute output"],
  register_research_output: ["登记计算成果", "Registered compute output"],
  list_business_flows: ["查找业务流", "Searched workflows"],
  get_research_workflow: ["读取业务流", "Read a workflow"],
  todo_list: ["更新任务清单", "Updated task list"],
  web_search: ["搜索网页", "Searched the web"],
  web_extract: ["阅读网页", "Read web pages"],
  skill_view: ["查看技能", "Read a skill"],
  tool_search: ["查找工具", "Searched tools"],
  tool_describe: ["查看工具详情", "Inspected tools"],
  clarify: ["确认任务信息", "Clarified the task"],
};

const toolIcon = (name: string) =>
  name.startsWith("web_") ? (
    <GlobalOutlined aria-hidden="true" />
  ) : name.includes("compute") || name.includes("output") ? (
    <DatabaseOutlined aria-hidden="true" />
  ) : name.includes("knowledge") || name.includes("resource") ? (
    <FileSearchOutlined aria-hidden="true" />
  ) : (
    <ApiOutlined aria-hidden="true" />
  );

function ToolGroup({ activity }: { activity: ToolActivity[] }) {
  const ui = useComputeText();
  const counts = new Map<string, number>();
  for (const item of activity)
    counts.set(item.name, (counts.get(item.name) ?? 0) + 1);
  const running = activity.some(({ status }) => status === "running");
  const name = (tool: string) =>
    operations[tool] ? ui(...operations[tool]) : ui("调用工具", "Used a tool");
  const labels = [...counts].map(
    ([tool, count]) => `${name(tool)}${count > 1 ? ` ×${count}` : ""}`,
  );
  return (
    <details className="hermes-tools">
      <summary>
        {running ? (
          <LoadingOutlined aria-hidden="true" />
        ) : (
          toolIcon(activity[0]?.name ?? "")
        )}
        <span>{labels.join(ui("、", ", "))}</span>
        <DownOutlined aria-hidden="true" className="hermes-disclosure" />
      </summary>
      <ul>
        {activity.map((item) => (
          <li key={item.id}>
            <span>{name(item.name)}</span>
            {item.name && <code>{item.name}</code>}
            <span className={`hermes-tool-${item.status}`}>
              {item.status === "running"
                ? ui("进行中", "Running")
                : item.status === "error"
                  ? ui("需调整", "Needs attention")
                  : ui("已完成", "Complete")}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function HermesProgress({
  activities,
  busy,
  startedAt,
  endedAt,
}: {
  activities: Activity[];
  busy: boolean;
  startedAt?: number;
  endedAt?: number;
}) {
  const ui = useComputeText();
  const [elapsed, setElapsed] = useState(0);
  const [open, setOpen] = useState<boolean>();
  useEffect(() => {
    if (!busy || startedAt === undefined) return;
    const update = () =>
      setElapsed(Math.max(0, Math.floor(Date.now() / 1000 - startedAt)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [busy, startedAt]);
  if (!activities.length && !busy) return null;
  const seconds = busy
    ? elapsed
    : startedAt === undefined || endedAt === undefined
      ? 0
      : Math.max(0, Math.floor(endedAt - startedAt));
  const duration =
    seconds >= 60
      ? ui(
          `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`,
          `${Math.floor(seconds / 60)}m ${seconds % 60}s`,
        )
      : ui(`${seconds} 秒`, `${seconds}s`);
  const label = busy
    ? ui(`进行中 · ${duration}`, `Working · ${duration}`)
    : seconds > 0
      ? ui(`用时 ${duration}`, `Worked for ${duration}`)
      : ui("查看进展", "View progress");
  const blocks: ReactNode[] = [];
  let tools: ToolActivity[] = [];
  function flushTools() {
    const first = tools[0];
    if (first) blocks.push(<ToolGroup key={first.id} activity={tools} />);
    tools = [];
  }
  for (const item of activities) {
    if (item.kind === "tool") {
      tools.push(item);
      continue;
    }
    flushTools();
    blocks.push(
      item.kind === "reasoning" ? (
        <details key={item.id} className="hermes-reasoning">
          <summary>
            <CompassOutlined aria-hidden="true" />
            {ui("思考过程", "Reasoning")}
            <DownOutlined aria-hidden="true" className="hermes-disclosure" />
          </summary>
          <div className="hermes-reasoning-content">
            <SafeMarkdown text={item.text} />
          </div>
        </details>
      ) : (
        <div key={item.id} className="hermes-commentary">
          <SafeMarkdown text={item.text} />
        </div>
      ),
    );
  }
  flushTools();
  return (
    <section className="hermes-progress">
      <button
        type="button"
        className="hermes-progress-toggle"
        aria-expanded={open ?? busy}
        onClick={() => setOpen(!(open ?? busy))}
      >
        {busy && <LoadingOutlined aria-hidden="true" />}
        <span>{label}</span>
        <DownOutlined aria-hidden="true" className="hermes-disclosure" />
      </button>
      {(open ?? busy) && <div className="hermes-progress-steps">{blocks}</div>}
    </section>
  );
}

type Citation = {
  title: string;
  url?: string;
  locator?: string;
  excerpt?: string;
};
export type Citations = Map<number, Citation[]>;

function publicUrl(value: unknown) {
  if (typeof value !== "string") return undefined;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

const knowledgeTools = new Set([
  "search_knowledge",
  "read_knowledge_document",
  "check_knowledge_constraints",
]);
export function readCitations(
  messages: HermesMessage[],
  prior: Citations = new Map(),
): Citations {
  const references = new Map(prior);
  for (const message of messages) {
    if (message.role !== "tool" || !knowledgeTools.has(message.tool_name ?? ""))
      continue;
    const payload = toolPayload(message.content);
    for (const collection of [
      payload.items,
      payload.documents,
      payload.findings,
    ]) {
      if (!Array.isArray(collection)) continue;
      for (const row of collection) {
        const item = object(row);
        if (
          typeof item.evidenceId !== "number" ||
          !Number.isSafeInteger(item.evidenceId)
        )
          continue;
        const title = [item.title, item.documentTitle, item.name].find(
          (value): value is string =>
            typeof value === "string" && Boolean(value),
        );
        if (!title) continue;
        const locator =
          typeof item.locator === "string" ? item.locator : undefined;
        const excerpt =
          typeof item.content === "string"
            ? item.content.slice(0, 760)
            : typeof item.summary === "string"
              ? item.summary.slice(0, 760)
              : undefined;
        const urls = Array.isArray(item.sources)
          ? item.sources.map((source) => object(source))
          : [];
        const sources = urls.length
          ? urls.map((source) => ({
              title:
                typeof source.title === "string" && source.title
                  ? source.title
                  : title,
              url: publicUrl(source.url),
              locator:
                typeof source.locator === "string" ? source.locator : locator,
              excerpt,
            }))
          : [{ title, url: publicUrl(item.sourceUrl), locator, excerpt }];
        const existing = references.get(item.evidenceId) ?? [];
        const merged = new Map(
          [...existing, ...sources].map((source) => [
            JSON.stringify([source.title, source.url, source.locator]),
            source,
          ]),
        );
        references.set(item.evidenceId, [...merged.values()]);
      }
    }
  }
  return references;
}

export function HermesAnswer({
  text,
  citations,
}: {
  text: string;
  citations: Citations;
}) {
  const ui = useComputeText();
  return (
    <SafeMarkdown
      text={text}
      links
      math
      renderCitation={(ids, label) => {
        const sources = ids.flatMap((id) => citations.get(id) ?? []);
        if (!ids.every((id) => citations.has(id))) return label;
        const unique = [
          ...new Map(
            sources.map((source) => [JSON.stringify(source), source]),
          ).values(),
        ];
        return (
          <Popover
            trigger="click"
            placement="topLeft"
            content={
              <div className="hermes-citations">
                {unique.map((source) => (
                  <section key={JSON.stringify(source)}>
                    {source.url ? (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {source.title}
                      </a>
                    ) : (
                      <strong>{source.title}</strong>
                    )}
                    {source.locator && <small>{source.locator}</small>}
                    {source.excerpt && <p>{source.excerpt}</p>}
                  </section>
                ))}
              </div>
            }
          >
            <a
              href={unique.find((source) => source.url)?.url ?? "#"}
              onClick={(event) => event.preventDefault()}
              aria-label={`${label} · ${ui("查看来源", "View sources")}`}
              className="hermes-citation"
            >
              {label}
            </a>
          </Popover>
        );
      }}
    />
  );
}

export function HermesResultLinks({
  messages,
  project,
}: {
  messages: HermesMessage[];
  project: string;
}) {
  const ui = useComputeText();
  const links = new Map<string, string>();
  for (const message of messages) {
    if (message.role !== "tool") continue;
    const content = toolPayload(message.content);
    const compute = message.tool_name === "submit_research_compute";
    const identity = compute
      ? content.taskId
      : message.tool_name === "start_business_flow"
        ? content.workflowId
        : undefined;
    if (typeof identity !== "string" || !/^[0-9a-f-]{36}$/.test(identity))
      continue;
    const query = new URLSearchParams({
      [compute ? "task" : "run"]: identity,
      projectTagId: project,
    });
    links.set(
      `${compute ? "/compute" : "/business-flows"}?${query}`,
      compute
        ? ui("查看计算任务", "View compute task")
        : ui("查看业务流运行", "View workflow run"),
    );
  }
  return links.size ? (
    <div className="hermes-result-links">
      {[...links].map(([to, label]) => (
        <Link key={to} to={to}>
          {label}
        </Link>
      ))}
    </div>
  ) : null;
}
