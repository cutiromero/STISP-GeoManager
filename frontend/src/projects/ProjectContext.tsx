import ColumnIcon from "../components/ColumnIcon";
import { useAuditText } from "../i18n/auditUi";
import { Alert, App, Button, Select, Space, Spin, Tag } from "antd";
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
import { useLocation } from "react-router-dom";
import { useAppContext } from "../contexts/AppContext";
import { authorizationIdentity } from "../auth/authorizationIdentity";
import { browserSessionSignal } from "../auth/browserSession";
import { downloadPageDiagnostics } from "../routing/pageDiagnostics";
import {
  getActiveProject,
  setActiveProject,
  normalizeProjectSelection,
  projectSignal,
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
  const loginPage = useLocation().pathname === "/login";
  const { message, modal } = App.useApp();
  const [current, setCurrent] = useState(getActiveProject);
  const [projects, setProjects] = useState<ProjectTag[]>([]);
  const [assignableProjects, setAssignableProjects] = useState<ProjectTag[]>(
    [],
  );
  const [canManage, setCanManage] = useState(false);
  const [canAssign, setCanAssign] = useState(false);
  const [resolvedIdentity, setResolvedIdentity] = useState<string>();
  const authKey = authorizationIdentity(user);
  const [loadError, setLoadError] = useState("");
  const requestSequence = useRef(0);
  const currentRef = useRef(current);
  currentRef.current = current;
  const identity = useRef(user?.id);
  identity.current = user?.id;
  const authorization = useRef(authKey);
  authorization.current = authKey;
  const onLoginPage = useRef(loginPage);
  onLoginPage.current = loginPage;
  const refresh = useCallback(async () => {
    if (onLoginPage.current) return;
    const sequence = ++requestSequence.current;
    const userId = identity.current;
    const authorized = authorization.current;
    const signal = projectSignal();
    const authSignal = browserSessionSignal();
    const isCurrent = () =>
      sequence === requestSequence.current &&
      userId === identity.current &&
      authorized === authorization.current &&
      !onLoginPage.current;
    let data;
    try {
      data = await platformApi.projects();
    } catch (error) {
      if (
        !isCurrent() ||
        signal.aborted ||
        authSignal.aborted ||
        ((error instanceof Error || error instanceof DOMException) &&
          error.name === "AbortError" &&
          signal.aborted)
      )
        return;
      setLoadError(
        error instanceof Error && error.name === "AbortError"
          ? "项目列表更新超时，请重试。"
          : error instanceof Error
            ? error.message
            : "项目列表暂时无法更新",
      );
      throw error;
    }
    if (!isCurrent() || signal.aborted) return;
    setProjects(data.items);
    setAssignableProjects(data.assignableItems ?? data.items);
    setCanManage(data.canManage);
    setCanAssign(data.canAssign);
    if (
      !data.items.some((p) => p.isActive && String(p.id) === currentRef.current)
    ) {
      const active = data.items.filter((p) => p.isActive);
      const fallback =
        active.find((p) => p.id === data.defaultProjectId)?.id ?? active[0]?.id;
      if (fallback !== undefined && fallback !== null) {
        const selected = String(fallback);
        setActiveProject(selected);
        setCurrent(selected);
        if (userId) sessionStorage.setItem(`project:${userId}`, selected);
      } else if (userId) {
        sessionStorage.removeItem(`project:${userId}`);
      }
    }
    setLoadError(
      data.items.some((p) => p.isActive)
        ? ""
        : "当前账号没有可访问的启用项目，请联系管理员。",
    );
    setResolvedIdentity(authorized);
  }, []);
  useEffect(() => {
    // A new tab has no stored choice; links such as the workbench comparison
    // carry projectTagId, and refresh() falls back if it is not accessible.
    const linked = new URLSearchParams(window.location.search).get(
      "projectTagId",
    );
    const preferred = normalizeProjectSelection(
      user
        ? (sessionStorage.getItem(`project:${user.id}`) ?? linked ?? "1")
        : "1",
    );
    if (user) sessionStorage.setItem(`project:${user.id}`, preferred);
    setActiveProject(preferred);
    setCurrent(preferred);
  }, [user?.id]);
  useEffect(() => {
    setLoadError("");
    if (loginPage) return;
    let active = true;
    void refresh().catch((error) => {
      if (active) {
        message.error(error.message);
      }
    });
    return () => {
      active = false;
      requestSequence.current += 1;
    };
  }, [refresh, authKey, message, loginPage]);
  useEffect(() => {
    const revalidate = () => {
      if (document.visibilityState === "visible")
        void refresh().catch(() => {});
    };
    window.addEventListener("focus", revalidate);
    return () => window.removeEventListener("focus", revalidate);
  }, [refresh]);
  const choose: ProjectContextValue["choose"] = (id, afterChoose, options) => {
    if (
      !projects.some((project) => project.isActive && String(project.id) === id)
    ) {
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
      <div key={`${authKey}:${current}`} style={{ height: "100%" }}>
        {loginPage ? (
          children
        ) : resolvedIdentity === authKey &&
          projects.some((p) => p.isActive && String(p.id) === current) ? (
          <>
            {loadError && (
              <Alert
                type="warning"
                showIcon
                title={ui("项目列表暂时无法更新，当前页面已保留")}
                description={loadError}
                style={{
                  position: "fixed",
                  top: 72,
                  right: 20,
                  maxWidth: 460,
                  zIndex: 1050,
                }}
                action={
                  <Space orientation="vertical">
                    <Button onClick={() => void refresh().catch(() => {})}>
                      {ui("重试更新项目")}
                    </Button>
                    <Button onClick={() => downloadPageDiagnostics()}>
                      {ui("导出诊断")}
                    </Button>
                  </Space>
                }
              />
            )}
            {children}
          </>
        ) : loadError ? (
          <Alert
            type="error"
            title={ui("项目访问范围加载失败")}
            description={loadError}
            action={
              <Button
                onClick={() =>
                  void refresh().catch((error) => setLoadError(error.message))
                }
              >
                {ui("重新加载")}
              </Button>
            }
          />
        ) : (
          <Spin description={ui("正在加载项目")} fullscreen />
        )}
      </div>
    </ProjectContext.Provider>
  );
}

export function ProjectSelector() {
  const ui = useAuditText();
  const value = useProjectContext();
  if (!value) return null;
  const projectLabel = (p: (typeof value.projects)[number]) =>
    `${p.isDefault ? ui("公开") : p.name}${p.isActive ? "" : ui("（停用）")}`;
  const currentProject = value.projects.find(
    (project) => String(project.id) === value.current,
  );
  const currentLabel = currentProject
    ? projectLabel(currentProject)
    : undefined;
  return (
    <Space size={6} className="project-selector">
      <Tag color="blue" icon={<ColumnIcon name="project" />}>
        {ui("项目")}
      </Tag>
      <Select
        aria-label={ui("当前项目标签")}
        value={
          value.projects.some((project) => String(project.id) === value.current)
            ? value.current
            : undefined
        }
        placeholder={ui("暂无可访问项目")}
        disabled={value.projects.length === 0}
        onChange={(id) => value.choose(id)}
        title={currentLabel}
        style={{ width: 168 }}
        // Long project names are shown in full in the list rather than cut off.
        popupMatchSelectWidth={false}
        options={value.projects.map((p) => ({
          value: String(p.id),
          disabled: !p.isActive,
          label: projectLabel(p),
          title: projectLabel(p),
        }))}
      />
    </Space>
  );
}
