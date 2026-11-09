import { Collapse } from "antd";
import { useEffect, useRef, useState } from "react";
import type { AgentEvent, AgentRun } from "../api/generated/types.gen";
import { runActivity } from "./agentActivity";
import { ActivityMark } from "./LiveActivity";
import ThinkingStream from "./ThinkingStream";

const names: Record<string, string> = {
  search_resources: "查找项目资料",
  describe_resource: "读取字段与元信息",
  get_map_data_profile: "读取地图分类与配色依据",
  prepare_map_workspace: "准备地理工作台",
  search_knowledge: "检索专业知识",
  read_knowledge_document: "阅读知识原文",
  summarize_data: "统计数据",
  aggregate_data: "汇总分析",
  execute_operator: "调用计算算子",
  get_compute_task: "读取计算进度",
  read_compute_output: "读取实际计算结果",
  import_compute_result: "登记计算成果",
  get_platform_link: "准备平台入口",
  present_resource_catalog: "整理资源清单",
  summarize_resource_catalog: "统计项目资源",
};

export default function RunProcess({
  run,
  events = [],
  disconnected,
}: {
  run: AgentRun;
  events?: AgentEvent[];
  disconnected?: string;
}) {
  const working = ["queued", "running"].includes(run.status);
  const [open, setOpen] = useState(
    working && Boolean(run.thinkingText) && !run.answerPreview,
  );
  const touched = useRef(false);
  useEffect(() => {
    if (!touched.current)
      setOpen(
        working &&
          Boolean(run.thinkingText) &&
          !run.answerPreview &&
          !run.answer,
      );
  }, [working, run.thinkingText, run.answerPreview, run.answer]);
  const tools: { id: number; name: string; complete: boolean }[] = [];
  for (const event of events) {
    if (!["tool_started", "tool_completed"].includes(event.kind)) continue;
    const name = event.text.split(/[：:]/, 1)[0] ?? "";
    if (event.kind === "tool_completed") {
      const pending = [...tools]
        .reverse()
        .find((item) => item.name === name && !item.complete);
      if (pending) {
        pending.complete = true;
        continue;
      }
    }
    tools.push({
      id: event.id,
      name,
      complete: event.kind === "tool_completed",
    });
  }
  if (!tools.length) {
    const seen = new Set<string>();
    for (const item of run.evidence) {
      if (seen.has(item.tool)) continue;
      seen.add(item.tool);
      tools.push({ id: item.id, name: item.tool, complete: true });
    }
  }
  if (!working && !run.thinkingText && !tools.length) return null;
  const activity = runActivity(run, events, undefined, disconnected);
  return (
    <Collapse
      className="agent-process-panel"
      size="small"
      activeKey={open ? ["process"] : []}
      onChange={(keys) => {
        touched.current = true;
        setOpen(keys.includes("process"));
      }}
      items={[
        {
          key: "process",
          label: (
            <span className="agent-process-summary">
              <ActivityMark state={activity.state} />
              <span>{working ? activity.label : "思考与处理过程"}</span>
              {tools.length > 0 && (
                <span className="agent-process-count">
                  {tools.length} 项操作
                </span>
              )}
            </span>
          ),
          children: (
            <>
              {(run.thinkingText ||
                (working && run.thinkingMode === "deep")) && (
                <div className="agent-process-thinking">
                  <span className="agent-process-section-label">
                    模型思考过程
                  </span>
                  {run.thinkingText ? (
                    <ThinkingStream
                      text={run.thinkingText}
                      working={
                        working &&
                        !run.answerPreview &&
                        !run.answer &&
                        !disconnected
                      }
                    />
                  ) : (
                    <p className="agent-muted">正在等待模型返回思考内容…</p>
                  )}
                </div>
              )}
              {tools.length > 0 && (
                <ol className="agent-process-tools" aria-label="工具处理记录">
                  {tools.map((item) => (
                    <li key={item.id}>
                      <ActivityMark
                        state={item.complete ? "complete" : "working"}
                      />
                      <span>{names[item.name] ?? "调用平台工具"}</span>
                      <small>{item.complete ? "已完成" : "处理中"}</small>
                    </li>
                  ))}
                </ol>
              )}
              {!run.thinkingText && !tools.length && (
                <p className="agent-muted">
                  正在处理当前请求，结果将持续显示。
                </p>
              )}
            </>
          ),
        },
      ]}
    />
  );
}
