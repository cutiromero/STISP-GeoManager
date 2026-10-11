import ColumnIcon from "../components/ColumnIcon";
import { useAuditText } from "../i18n/auditUi";
import { App, Select, Space, Tag } from "antd";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  useRef,
  type ReactNode,
} from "react";
import { platformApi, type ProjectTag } from "../api/platform";
import { useAppContext } from "../contexts/AppContext";
import {
  getActiveProject,
  setActiveProject,
  normalizeProjectSelection,
} from "./session";

type ProjectContextValue = {
  current: string;
  projects: ProjectTag[];
  assignableProjects: ProjectTag[];
  canManage: boolean;
  canAssign: boolean;
  refresh: () => Promise<void>;
  choose: (
    id: string,
    afterChoose?: () => void,
    options?: { confirm?: boolean },
  ) => void;
};
const ProjectContext = createContext<ProjectContextValue | null>(null);
export const useProjectContext = () => useContext(ProjectContext);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const ui = useAuditText();
  const { user } = useAppContext();
  const { message, modal } = App.useApp();
  const [current, setCurrent] = useState(getActiveProject);
  const [projects, setProjects] = useState<ProjectTag[]>([]);
  const [assignableProjects, setAssignableProjects] = useState<ProjectTag[]>(
    [],
  );
  const [canManage, setCanManage] = useState(false);
  const [canAssign, setCanAssign] = useState(false);
  const requestSequence = useRef(0);
  const identity = useRef(user?.id);
  identity.current = user?.id;
  const refresh = useCallback(async () => {
    const sequence = ++requestSequence.current;
    const userId = identity.current;
    const data = await platformApi.projects();
    if (sequence !== requestSequence.current || userId !== identity.current)
      return;
    setProjects(data.items);
    setAssignableProjects(data.assignableItems ?? data.items);
    setCanManage(data.canManage);
    setCanAssign(data.canAssign);
    if (!data.items.some((p) => String(p.id) === current)) {
      setActiveProject("1");
      setCurrent("1");
      if (userId) sessionStorage.setItem(`project:${userId}`, "1");
    }
  }, [current]);
  useEffect(() => {
    const preferred = normalizeProjectSelection(
      user ? (sessionStorage.getItem(`project:${user.id}`) ?? "1") : "1",
    );
    if (user) sessionStorage.setItem(`project:${user.id}`, preferred);
    setActiveProject(preferred);
    setCurrent(preferred);
  }, [user?.id]);
  useEffect(() => {
    let active = true;
    void refresh().catch((error) => {
      if (active) message.error(error.message);
    });
    return () => {
      active = false;
    };
  }, [refresh, user?.id, message]);
  useEffect(() => {
    const revalidate = () => {
      if (document.visibilityState === "visible")
        void refresh().catch(() => {});
    };
    window.addEventListener("focus", revalidate);
    return () => window.removeEventListener("focus", revalidate);
  }, [refresh]);
  const choose: ProjectContextValue["choose"] = (id, afterChoose, options) => {
    if (!projects.some((project) => String(project.id) === id)) {
      message.error(ui("请选择一个可访问的项目"));
      return;
    }
    if (id === current) {
      afterChoose?.();
      return;
    }
    const apply = () => {
      if (user) sessionStorage.setItem(`project:${user.id}`, id);
      setActiveProject(id);
      setCurrent(id);
      afterChoose?.();
    };
    if (options?.confirm === false) {
      apply();
      return;
    }
    modal.confirm({
      title: ui("切换项目标签"),
      content: ui(
        "切换会关闭当前工作台并清除已加载图层，请先保存未保存的编辑。",
      ),
      okText: ui("切换项目"),
      cancelText: ui("保留当前项目"),
      onOk: apply,
    });
  };
  return (
    <ProjectContext.Provider
      value={{
        current,
        projects,
        assignableProjects,
        canManage,
        canAssign,
        refresh,
        choose,
      }}
    >
      <div
        key={`${user?.id ?? "public"}:${current}`}
        style={{ height: "100%" }}
      >
        {children}
      </div>
    </ProjectContext.Provider>
  );
}

export function ProjectSelector() {
  const ui = useAuditText();
  const value = useProjectContext();
  if (!value) return null;
  return (
    <Space size={6} className="project-selector">
      <Tag color="blue" icon={<ColumnIcon name="project" />}>
        {ui("项目")}
      </Tag>
      <Select
        aria-label={ui("当前项目标签")}
        value={value.current}
        onChange={(id) => value.choose(id)}
        style={{ width: 150 }}
        popupMatchSelectWidth={230}
        options={value.projects.map((p) => ({
          value: String(p.id),
          label: `${p.isDefault ? ui("公开") : p.name}${p.isActive ? "" : ui("（停用）")}`,
        }))}
      />
    </Space>
  );
}
