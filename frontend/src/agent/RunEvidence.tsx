import { Collapse, Typography } from "antd";
import { FileSearchOutlined } from "@ant-design/icons";
import { useMemo } from "react";
import type { AgentEvidence } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import { createUuid } from "../utils/uuid";

const operations: Record<string, [string, string]> = {
  search_resources: ["查找数据", "Data search"],
  get_map_data_profile: ["地图资料与类别", "Map data and categories"],
  prepare_map_workspace: ["个人地图已准备", "Personal map prepared"],
  get_platform_link: ["平台页面入口", "Platform page"],
  describe_resource: ["数据概况", "Data overview"],
  read_rows: ["数据样本", "Data sample"],
  summarize_data: ["统计摘要", "Summary statistics"],
  aggregate_data: ["分组统计", "Grouped statistics"],
  compare_summaries: ["统计对比", "Statistics comparison"],
  read_document: ["文档摘录", "Document excerpt"],
  list_compute_algorithms: ["可用算法", "Available algorithms"],
  get_system_info: ["运行环境", "Runtime environment"],
  execute_operator: ["计算任务", "Compute task"],
  import_compute_result: ["结果入库", "Result import"],
  get_compute_task: ["计算实时状态", "Current compute status"],
  list_compute_tasks: ["计算任务列表", "Compute tasks"],
  search_knowledge: ["知识依据", "Knowledge sources"],
  read_knowledge_document: ["知识原文", "Knowledge document"],
  check_knowledge_constraints: ["知识规则检查", "Knowledge checks"],
  web_search: ["网页检索", "Web search"],
  web_fetch: ["网页摘录", "Web excerpt"],
};
const labels: Record<string, [string, string]> = {
  id: ["编号", "ID"],
  name: ["名称", "Name"],
  kind: ["类型", "Type"],
  description: ["说明", "Description"],
  count: ["数量", "Count"],
  total: ["总数", "Total"],
  items: ["条目", "Items"],
  rows: ["记录", "Rows"],
  fields: ["字段", "Fields"],
  groups: ["分组", "Groups"],
  group: ["分组", "Group"],
  value: ["数值", "Value"],
  min: ["最小值", "Minimum"],
  max: ["最大值", "Maximum"],
  mean: ["均值", "Mean"],
  sum: ["合计", "Sum"],
  text: ["内容", "Text"],
  resourceId: ["资源编号", "Resource ID"],
  documentId: ["知识资料编号", "Knowledge document ID"],
  title: ["标题", "Title"],
  sourceUrl: ["来源链接", "Source URL"],
  citation: ["引用编号", "Citation"],
  offset: ["起始位置", "Offset"],
  nextOffset: ["续读位置", "Next offset"],
  unit: ["单位", "Unit"],
  filters: ["筛选条件", "Filters"],
  truncated: ["结果已截取", "Result truncated"],
};

function ResultValue({ value }: { value: unknown }) {
  const ui = useComputeText();
  const entries = useMemo(
    () =>
      Array.isArray(value)
        ? value.map((entry) => ({ id: createUuid(), entry }))
        : [],
    [value],
  );
  if (value === null || value === undefined) return <span>—</span>;
  if (Array.isArray(value)) {
    return value.length ? (
      <ol className="agent-source-list">
        {entries.map(({ id, entry }) => (
          <li key={id}>
            <ResultValue value={entry} />
          </li>
        ))}
      </ol>
    ) : (
      <span>{ui("无", "None")}</span>
    );
  }
  if (typeof value === "object")
    return (
      <dl className="agent-source-fields">
        {Object.entries(value).map(([key, entry]) => (
          <div key={key}>
            <dt>{labels[key] ? ui(...labels[key]) : key}</dt>
            <dd>
              <ResultValue value={entry} />
            </dd>
          </div>
        ))}
      </dl>
    );
  return (
    <span>
      {typeof value === "boolean"
        ? value
          ? ui("是", "Yes")
          : ui("否", "No")
        : String(value)}
    </span>
  );
}

export default function RunEvidence({
  items,
  canManage,
}: {
  items: AgentEvidence[];
  canManage: boolean;
}) {
  const ui = useComputeText();
  if (!items.length) return null;
  return (
    <Collapse
      className="agent-run-sources"
      ghost
      size="small"
      items={[
        {
          key: "sources",
          label: (
            <span className="agent-sources-trigger">
              <FileSearchOutlined />
              <span>{ui("数据来源与分析", "Sources and analysis")}</span>
              <span className="agent-source-count">{items.length}</span>
            </span>
          ),
          children: (
            <>
              <Typography.Paragraph
                type="secondary"
                className="agent-sources-note"
              >
                {ui(
                  "按引用编号查看资料与分析结果。计算进度见任务卡。",
                  "Explore sources and results by citation number. Task cards show live progress.",
                )}
              </Typography.Paragraph>
              <Collapse
                ghost
                className="agent-source-records"
                size="small"
                items={items.map((item) => {
                  const operation = operations[item.tool];
                  const title = operation
                    ? ui(...operation)
                    : ui("分析记录", "Analysis record");
                  return {
                    key: item.id,
                    label: (
                      <span className="agent-source-heading">
                        <span className="agent-source-number">[{item.id}]</span>
                        <span className="agent-source-name">
                          {item.name || title}
                        </span>
                        {item.name && (
                          <span className="agent-source-operation">
                            {title}
                          </span>
                        )}
                      </span>
                    ),
                    children: (
                      <>
                        <div className="agent-source-result">
                          <ResultValue value={item.result} />
                        </div>
                        {canManage && (
                          <Collapse
                            className="agent-source-technical"
                            ghost
                            size="small"
                            items={[
                              {
                                key: "raw",
                                label: ui("工具调用详情", "Tool call details"),
                                children: (
                                  <>
                                    <code>{item.tool}</code>
                                    <pre className="agent-evidence-json">
                                      {JSON.stringify(item.result, null, 2)}
                                    </pre>
                                  </>
                                ),
                              },
                            ]}
                          />
                        )}
                      </>
                    ),
                  };
                })}
              />
            </>
          ),
        },
      ]}
    />
  );
}
