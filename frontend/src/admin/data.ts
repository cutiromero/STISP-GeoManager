import type { AdminOperationLog } from "../types";

export function operationLogsToCsv(rows: AdminOperationLog[]) {
  const headers = [
    "时间",
    "操作用户",
    "模块",
    "动作",
    "结果",
    "IP 地址",
    "摘要",
  ];
  const body = rows.map((row) =>
    [
      row.occurredAt,
      row.operator,
      row.module,
      row.action,
      resultText(row.result),
      row.ipAddress,
      row.summary,
    ].map(escapeCsvCell),
  );
  return [headers, ...body].map((line) => line.join(",")).join("\n");
}

function resultText(result: AdminOperationLog["result"]) {
  if (result === "success") return "成功";
  if (result === "warning") return "告警";
  return "失败";
}

function escapeCsvCell(value: string | number) {
  const text = String(value);
  if (/["\n,]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}
