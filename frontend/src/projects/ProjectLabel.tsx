import { useAuditText } from "../i18n/auditUi";
import { Alert, Tag } from "antd";
import { useProjectContext } from "./ProjectContext";

export function ProjectLabel({ id }: { id?: number }) {
  const ui = useAuditText();
  const context = useProjectContext();
  const project = context?.projects.find((item) => item.id === id);
  return (
    <Tag color={id === 1 ? "green" : "blue"}>
      {ui("项目")}：{id === 1 ? ui("公开") : (project?.name ?? `#${id ?? "—"}`)}
    </Tag>
  );
}

export function ProjectNotice() {
  const ui = useAuditText();
  const context = useProjectContext();
  if (!context) return null;
  const project = context.projects.find(
    (item) => String(item.id) === context.current,
  );
  return (
    <Alert
      className="project-scope-notice"
      style={{ marginBottom: 16 }}
      showIcon
      type="info"
      title={`${ui("当前项目标签")}：${project?.isDefault ? ui("公开") : (project?.name ?? context.current)}`}
      description={ui(
        "每次在一个项目内查看和操作数据、地图工程及成果。公开项目所有人可读；其他项目仅获配对应标签的用户及超管可读。",
      )}
    />
  );
}
