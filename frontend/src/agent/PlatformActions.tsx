import { Button, Space, Typography } from "antd";
import { EnvironmentOutlined, LinkOutlined } from "@ant-design/icons";
import type { AgentPlatformAction } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

const pages = {
  business_flows: "/business-flows",
  map: "/map",
  resources: "/resources/catalog",
  compute: "/compute",
  knowledge: "/resources/knowledge-base",
} as const;

export function platformActionUrl(
  action: AgentPlatformAction,
  projectId: number,
) {
  if (
    !Number.isSafeInteger(action.projectId) ||
    action.projectId <= 0 ||
    action.projectId !== projectId
  )
    return null;
  const query = new URLSearchParams({ projectTagId: String(projectId) });
  if (
    action.kind === "workspace" &&
    Number.isSafeInteger(action.sceneId) &&
    Number(action.sceneId) > 0
  ) {
    query.set("sceneId", String(action.sceneId));
    return `/map?${query}`;
  }
  if (
    action.kind === "page" &&
    action.page &&
    Object.prototype.hasOwnProperty.call(pages, action.page)
  )
    return `${pages[action.page]}?${query}`;
  return null;
}

export default function PlatformActions({
  actions,
  projectId,
}: {
  actions?: AgentPlatformAction[];
  projectId: number;
}) {
  const ui = useComputeText();
  const ready = (actions ?? [])
    .map((action) => ({ action, url: platformActionUrl(action, projectId) }))
    .filter((item) => item.url);
  if (!ready.length) return null;
  return (
    <section
      className="agent-platform-actions"
      aria-label={ui("平台操作结果", "Platform actions")}
    >
      <Space wrap>
        {ready.map(({ action, url }) => (
          <Button
            key={`${action.kind}-${action.sceneId ?? action.page}`}
            type={action.kind === "workspace" ? "primary" : "default"}
            icon={
              action.kind === "workspace" ? (
                <EnvironmentOutlined />
              ) : (
                <LinkOutlined />
              )
            }
            href={url!}
            target="_blank"
            rel="noopener"
          >
            {action.kind === "workspace"
              ? ui("在地理工作台查看", "View in map workspace")
              : action.title}
          </Button>
        ))}
      </Space>
      {ready.some((item) => item.action.kind === "workspace") && (
        <Typography.Paragraph type="secondary">
          {ui(
            "地图已保存到您的个人工程，原始资料未修改。",
            "Saved in your personal projects; source data is unchanged.",
          )}
        </Typography.Paragraph>
      )}
    </section>
  );
}
