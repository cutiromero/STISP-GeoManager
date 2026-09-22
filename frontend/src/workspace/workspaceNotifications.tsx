import { App, Space, Spin, Typography } from "antd";
import type { GeoJsonValidationWarning } from "../types";
import type { WorkspaceRestoreIssue } from "./workspaceRestore";

export type AppNotification = ReturnType<typeof App.useApp>["notification"];

export function openWorkspaceProgressNotification(
  notification: AppNotification,
  options: {
    key: string;
    title: string;
    percent: number;
    status: "active" | "success" | "exception";
    detail: string;
  },
) {
  notification.open({
    key: options.key,
    message: options.title,
    description: (
      <Space orientation="vertical" size={6} style={{ width: "100%" }}>
        <Space size={8}>
          <Spin spinning={options.status === "active"} size="small" />
          <Typography.Text type="secondary">{options.detail}</Typography.Text>
        </Space>
      </Space>
    ),
    duration: options.status === "active" ? 0 : 5,
    showProgress: options.status !== "active",
    pauseOnHover: false,
  });
}

export function showGeojsonWarnings(
  notification: AppNotification,
  warnings?: GeoJsonValidationWarning[],
) {
  if (!warnings?.length) {
    return;
  }
  notification.warning({
    key: `geojson-warning-${warnings
      .map((warning) => warning.code)
      .sort()
      .join("-")}`,
    message: "地理坐标数据警告",
    description: (
      <div className="geojson-warning-list">
        {warnings.map((warning) => (
          <div key={`${warning.code}-${warning.message}`}>
            {warning.message}
          </div>
        ))}
      </div>
    ),
    placement: "topRight",
    duration: 8,
  });
}

export function showWorkspaceRestoreIssues(
  notification: AppNotification,
  issues: WorkspaceRestoreIssue[],
) {
  if (issues.length === 0) {
    return;
  }
  notification.warning({
    message: "部分图层未按原始数据恢复",
    description: (
      <div className="geojson-warning-list">
        {issues.slice(0, 6).map((issue) => (
          <div key={`${issue.layerName}-${issue.reason}`}>
            {issue.layerName}：{issue.reason}
            {issue.action === "restored-with-warning"
              ? "，已保留快照中的图层引用"
              : "，已跳过"}
          </div>
        ))}
        {issues.length > 6 ? (
          <div>另有 {issues.length - 6} 个图层异常</div>
        ) : null}
      </div>
    ),
    placement: "topRight",
    duration: 10,
  });
}

export function showWorkspaceRestoreEmptyResult(
  notification: AppNotification,
  options: {
    key: string;
    label: string;
    issues: WorkspaceRestoreIssue[];
  },
) {
  openWorkspaceProgressNotification(notification, {
    key: options.key,
    title: `${options.label}加载失败`,
    percent: 100,
    status: "exception",
    detail:
      options.issues.length > 0
        ? "原始数据不可用，未恢复任何图层"
        : "该工作区快照没有可恢复的图层",
  });
  showWorkspaceRestoreIssues(notification, options.issues);
}
