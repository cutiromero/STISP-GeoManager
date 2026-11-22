import { MenuOutlined } from "@ant-design/icons";
import { Button, Drawer, Layout, Tag } from "antd";
import { useRef, type ReactNode, type RefObject } from "react";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useComputeText } from "../compute/ui";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import AgentResizeHandle from "./AgentResizeHandle";
import type useAgentLayout from "./useAgentLayout";
import "./agent.css";

type LayoutPreferences = ReturnType<typeof useAgentLayout>;

export function conversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const time = date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return date.toDateString() === today.toDateString()
    ? `今天 ${time}`
    : `${date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })} ${time}`;
}

export function AgentComposerFrame({
  layout,
  children,
}: {
  layout: LayoutPreferences;
  children: ReactNode;
}) {
  const ui = useComputeText();
  return (
    <div className="agent-composer">
      <AgentResizeHandle
        orientation="horizontal"
        label={ui("调整输入框高度", "Resize message input")}
        hint={ui(
          "上下拖动或按方向键调整，双击恢复",
          "Drag or use arrow keys to resize; double-click to reset",
        )}
        controls="agent-message-input"
        value={layout.input}
        min={layout.inputMin}
        max={layout.inputMax}
        defaultValue={layout.defaults.input}
        onChange={layout.setInput}
      />
      <div className="agent-composer-content">{children}</div>
    </div>
  );
}

export default function AgentWorkspaceLayout({
  layout,
  sidebar,
  historyOpen,
  onHistoryOpen,
  historyCloseButton,
  modeLabel,
  title,
  preparing,
  actions,
  sidePanel,
  overlay,
  children,
}: {
  layout: LayoutPreferences;
  sidebar: ReactNode;
  historyOpen: boolean;
  onHistoryOpen: (open: boolean) => void;
  historyCloseButton: RefObject<HTMLButtonElement | null>;
  modeLabel: string;
  title?: string;
  preparing?: boolean;
  actions?: ReactNode;
  sidePanel?: ReactNode;
  overlay?: ReactNode;
  children: ReactNode;
}) {
  const ui = useComputeText();
  const { user } = useAppContext();
  const project = useProjectContext();
  const historyButton = useRef<HTMLButtonElement>(null);
  return (
    <Layout className="agent-shell">
      <WorkspaceHeader
        activeTab="warning"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="agent-workspace">
        {layout.narrow ? (
          <Drawer
            placement="left"
            open={historyOpen}
            onClose={() => onHistoryOpen(false)}
            closable={false}
            size="default"
            styles={{
              wrapper: { width: "min(320px, calc(100vw - 44px))" },
              body: { padding: 16 },
            }}
            classNames={{ root: "agent-history-drawer" }}
            aria-label={ui("会话侧栏", "Conversation sidebar")}
            afterOpenChange={(open) => {
              if (open) historyCloseButton.current?.focus();
              else historyButton.current?.focus();
            }}
          >
            {sidebar}
          </Drawer>
        ) : (
          <>
            {sidebar}
            <AgentResizeHandle
              orientation="vertical"
              label={ui("调整会话侧栏宽度", "Resize conversation sidebar")}
              hint={ui(
                "左右拖动或按方向键调整，双击恢复",
                "Drag or use arrow keys to resize; double-click to reset",
              )}
              controls="agent-conversation-sidebar"
              value={layout.sidebar}
              min={layout.sidebarMin}
              max={layout.sidebarMax}
              defaultValue={layout.defaults.sidebar}
              onChange={layout.setSidebar}
            />
          </>
        )}
        <main
          className={`agent-main${preparing ? " is-preparing-flow" : ""}`}
          inert={historyOpen && layout.narrow}
        >
          <div className="agent-toolbar">
            <div className="agent-toolbar-heading">
              <Button
                ref={historyButton}
                className="agent-history-toggle"
                type="text"
                icon={<MenuOutlined />}
                aria-label={ui("会话", "Conversations")}
                aria-expanded={historyOpen}
                aria-controls="agent-conversation-sidebar"
                onClick={() => onHistoryOpen(!historyOpen)}
              >
                {ui("会话", "History")}
              </Button>
              <div className="agent-conversation-heading">
                <span>{modeLabel}</span>
                <strong title={title}>{title ?? modeLabel}</strong>
              </div>
            </div>
            {actions}
            <Tag className="agent-project-badge">
              {project?.projects.find(
                (item) => String(item.id) === project.current,
              )?.name ?? ui("当前项目", "Current project")}
            </Tag>
          </div>
          {children}
        </main>
        {sidePanel}
      </div>
      {overlay}
    </Layout>
  );
}
