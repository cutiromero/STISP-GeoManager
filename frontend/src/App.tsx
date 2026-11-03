import { ProjectProvider } from "./projects/ProjectContext";
import { Alert, Button, Spin } from "antd";
import type { ReactNode } from "react";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import {
  api,
  registerForbiddenHandler,
  unregisterForbiddenHandler,
} from "./api/client";
import { AppContext } from "./contexts/AppContext";
import { applyPlatformDocumentTitle } from "./config/platformBrand";
import {
  AdminIndexRedirect,
  RedirectIfAuth,
  RequireAccountSelfService,
  RequireAdminAccess,
  RequireAuth,
  RequireDataInventory,
  RequireDataUpload,
  RequireManageAuth,
  RequireManageProjects,
  RequireManageDataBackup,
  RequireManageSystemSettings,
  RequireViewOperationLogs,
  RequireWorkspaceInventory,
} from "./router";
import type { Bootstrap, User } from "./types";
import i18n, { type AppLocale } from "./i18n";
import { browserSessionEndedEvent } from "./auth/browserSession";
import { lazyPage as lazy, RouteRecovery } from "./routing/pageRecovery";
import { markSessionExpired } from "./auth/sessionNotice";

const AdminAuthPage = lazy(() => import("./admin/AdminAuthPage"));
const AdminDataBackupPage = lazy(() => import("./admin/AdminDataBackupPage"));
const AdminDashboardPage = lazy(() => import("./admin/AdminDashboardPage"));
const AdminDataImportPage = lazy(() => import("./admin/AdminDataImportPage"));
const AdminDataInventoryPage = lazy(
  () => import("./admin/AdminDataInventoryPage"),
);
const AdminLayout = lazy(() => import("./admin/AdminLayout"));
const AdminOperationLogsPage = lazy(
  () => import("./admin/AdminOperationLogsPage"),
);
const AdminProfilePage = lazy(() => import("./admin/AdminProfilePage"));
const AdminSystemSettingsPage = lazy(
  () => import("./admin/AdminSystemSettingsPage"),
);
const AdminWorkspaceManagementPage = lazy(
  () => import("./admin/AdminWorkspaceManagementPage"),
);
const AdminTopicCompositionManagementPage = lazy(
  () => import("./admin/AdminTopicCompositionManagementPage"),
);
const AboutPage = lazy(() => import("./pages/AboutV2Page"));
const EditorialPage = lazy(() => import("./pages/EditorialPage"));
const KnowledgeBasePage = lazy(() => import("./knowledge/KnowledgePage"));
const ProjectManagementPage = lazy(
  () => import("./pages/ProjectManagementPage"),
);
const LoginPage = lazy(() => import("./pages/LoginPage"));
const DataCatalogPage = lazy(() => import("./pages/DataCatalogPage"));

const MapPage = lazy(() => import("./pages/MapPage"));
const ComputePage = lazy(() => import("./compute/ComputePage"));
const NonGeoPage = lazy(() => import("./pages/NonGeoPage"));
const ResultsPage = lazy(() => import("./pages/ResultsPage"));
const AgentPage = lazy(() => import("./agent/AgentPage"));
const AgentAdmin = lazy(() => import("./agent/AgentAdmin"));
const ResourceLayout = lazy(() => import("./resource/ResourceLayout"));

/** 为路由页面添加淡入过渡效果的包装组件 */
function RouteTransition({ children }: { children: ReactNode }) {
  const location = useLocation();
  return (
    <div className="route-enter" key={location.pathname}>
      {children}
    </div>
  );
}

function RouteLoading() {
  return (
    <div className="boot-screen">
      <Spin size="large" />
    </div>
  );
}

const startupRetryDelaysMs = [300, 700, 1200, 2000];

export default function App({
  locale,
}: {
  locale?: AppLocale;
  languageVersion?: string;
} = {}) {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [user, updateUser] = useState<User | null>(null);
  const signedIn = useRef<User | null>(null);
  signedIn.current = user;
  const authGeneration = useRef(0);
  const setUser = useCallback((value: User | null) => {
    authGeneration.current += 1;
    updateUser(value);
  }, []);
  const [loading, setLoading] = useState(true);
  const [startupFailure, setStartupFailure] = useState("");
  const [startupAttempt, setStartupAttempt] = useState(0);

  useEffect(() => {
    const signedOut = () => {
      if (signedIn.current) markSessionExpired(signedIn.current.id);
      setUser(null);
    };
    window.addEventListener(browserSessionEndedEvent, signedOut);
    return () =>
      window.removeEventListener(browserSessionEndedEvent, signedOut);
  }, [setUser]);

  const handleForbidden = useCallback(async () => {
    const generation = authGeneration.current;
    try {
      const me = await api.me();
      if (generation === authGeneration.current) setUser(me.user);
    } catch (error) {
      if (
        generation === authGeneration.current &&
        (isApiStatus(error, 401) || isApiStatus(error, 403))
      ) {
        if (signedIn.current) markSessionExpired(signedIn.current.id);
        setUser(null);
      }
    }
  }, []);

  useEffect(() => {
    registerForbiddenHandler(handleForbidden);
    return () => {
      unregisterForbiddenHandler();
    };
  }, [handleForbidden]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setStartupFailure("");
    async function boot() {
      try {
        const bootstrapData = await retryTransientStartup(async () => {
          const [data] = await Promise.all([api.bootstrap(), api.csrf()]);
          return data;
        });
        let currentUser: User | null = null;
        try {
          const me = await api.me();
          currentUser = me.user;
        } catch (error) {
          if (!isApiStatus(error, 401)) {
            throw error;
          }
        }
        if (mounted) {
          setBootstrap(bootstrapData);
          setUser(currentUser);
          applyPlatformDocumentTitle(bootstrapData.systemName);
        }
      } catch (error) {
        if (mounted)
          setStartupFailure(
            error instanceof Error
              ? error.message
              : i18n.t("errors.startupFailed"),
          );
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    boot();
    return () => {
      mounted = false;
    };
  }, [startupAttempt]);

  useEffect(() => {
    if (bootstrap) {
      applyPlatformDocumentTitle(bootstrap.systemName, locale);
    }
  }, [bootstrap, locale]);

  if (loading) {
    return (
      <div className="boot-screen">
        <Spin size="large" />
      </div>
    );
  }
  if (!bootstrap) {
    const english = locale === "en-US";
    return (
      <main className="page-recovery-content" role="alert">
        <h1>{english ? "Platform could not be loaded" : "平台暂时未能加载"}</h1>
        <Alert
          type="error"
          title={startupFailure || i18n.t("errors.startupFailed")}
        />
        <p>
          {english
            ? "Check your connection and browser version, then try again."
            : "请检查网络和浏览器版本，然后重新尝试。"}
        </p>
        <Button
          type="primary"
          onClick={() => setStartupAttempt((value) => value + 1)}
        >
          {english ? "Retry connection" : "重新连接"}
        </Button>
      </main>
    );
  }

  return (
    <AppContext.Provider value={{ bootstrap, user, setBootstrap, setUser }}>
      <ProjectProvider>
        <RouteRecovery>
          <Suspense fallback={<RouteLoading />}>
            <Routes>
              <Route
                path="/"
                element={
                  <RouteTransition>
                    <Navigate to="/map" replace />
                  </RouteTransition>
                }
              />

              {/* 已登录用户访问登录页时重定向到首页 */}
              <Route element={<RedirectIfAuth />}>
                <Route
                  path="/login"
                  element={
                    <RouteTransition>
                      <LoginPage />
                    </RouteTransition>
                  }
                />
              </Route>

              <Route path="/map" element={<MapPage />} />
              <Route path="/compute" element={<ComputePage />} />
              <Route
                path="/data"
                element={<Navigate to="/resources/catalog" replace />}
              />
              <Route path="/resources/catalog" element={<DataCatalogPage />} />
              <Route
                path="/knowledge"
                element={<EditorialPage kind="knowledge" />}
              />
              <Route
                path="/knowledge/:articleId"
                element={<EditorialPage kind="knowledge" />}
              />
              <Route path="/news" element={<EditorialPage kind="news" />} />
              <Route
                path="/news/:articleId"
                element={<EditorialPage kind="news" />}
              />
              <Route
                path="/resources"
                element={<Navigate to="/resources/catalog" replace />}
              />

              {/* 需要登录才能访问的页面 */}
              <Route element={<RequireAuth />}>
                <Route path="/knowledge-base" element={<KnowledgeBasePage />} />
                <Route
                  path="/projects/manage"
                  element={<Navigate to="/admin/projects" replace />}
                />

                <Route
                  path="/nongeo"
                  element={
                    <RouteTransition>
                      <NonGeoPage />
                    </RouteTransition>
                  }
                />
                <Route
                  path="/analysis"
                  element={<Navigate to="/nongeo" replace />}
                />
                <Route
                  path="/results"
                  element={
                    <RouteTransition>
                      <ResultsPage />
                    </RouteTransition>
                  }
                />
                <Route
                  path="/warning"
                  element={<Navigate to="/agent/chat" replace />}
                />
                <Route
                  path="/agent"
                  element={<Navigate to="/agent/chat" replace />}
                />
                <Route path="/agent/chat" element={<AgentPage />} />
                <Route path="/agent/workbench" element={<AgentPage />} />

                <Route
                  path="/about"
                  element={<Navigate to="/about/system" replace />}
                />
                <Route
                  path="/about/knowledge"
                  element={<Navigate to="/knowledge" replace />}
                />
                <Route
                  path="/about/:section/:institutionId"
                  element={
                    <RouteTransition>
                      <AboutPage />
                    </RouteTransition>
                  }
                />
                <Route
                  path="/about/:section"
                  element={
                    <RouteTransition>
                      <AboutPage />
                    </RouteTransition>
                  }
                />
                <Route path="/resources" element={<ResourceLayout />}>
                  <Route
                    path="dashboard"
                    element={<AdminDashboardPage scope="data" />}
                  />
                  <Route element={<RequireDataInventory />}>
                    <Route
                      path="data/inventory"
                      element={<AdminDataInventoryPage />}
                    />
                  </Route>
                  <Route element={<RequireWorkspaceInventory />}>
                    <Route
                      path="manage/projects"
                      element={<AdminWorkspaceManagementPage kind="project" />}
                    />
                    <Route
                      path="manage/topics"
                      element={<AdminTopicCompositionManagementPage />}
                    />
                  </Route>
                  <Route element={<RequireDataUpload />}>
                    <Route
                      path="data/import"
                      element={<AdminDataImportPage />}
                    />
                  </Route>
                </Route>
                <Route path="/admin" element={<AdminLayout />}>
                  <Route index element={<AdminIndexRedirect />} />
                  <Route element={<RequireAccountSelfService />}>
                    <Route path="profile" element={<AdminProfilePage />} />
                  </Route>
                  <Route element={<RequireAdminAccess />}>
                    <Route path="compute" element={<ComputePage admin />} />
                    <Route element={<RequireManageProjects />}>
                      <Route path="agent" element={<AgentAdmin />} />
                      <Route
                        path="projects"
                        element={<ProjectManagementPage />}
                      />
                    </Route>
                    <Route
                      path="dashboard"
                      element={<AdminDashboardPage scope="operations" />}
                    />
                    <Route element={<RequireViewOperationLogs />}>
                      <Route path="logs" element={<AdminOperationLogsPage />} />
                    </Route>
                    <Route element={<RequireManageSystemSettings />}>
                      <Route
                        path="settings"
                        element={<AdminSystemSettingsPage />}
                      />
                    </Route>
                    <Route element={<RequireManageDataBackup />}>
                      <Route path="backup" element={<AdminDataBackupPage />} />
                    </Route>
                    <Route element={<RequireManageAuth />}>
                      <Route
                        path="auth"
                        element={<Navigate to="users" replace />}
                      />
                      <Route path="auth/users" element={<AdminAuthPage />} />
                      <Route path="auth/groups" element={<AdminAuthPage />} />
                    </Route>
                  </Route>
                </Route>
              </Route>
            </Routes>
          </Suspense>
        </RouteRecovery>
      </ProjectProvider>
    </AppContext.Provider>
  );
}

function isApiStatus(error: unknown, status: number) {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    error.status === status
  );
}

async function retryTransientStartup<T>(request: () => Promise<T>): Promise<T> {
  let lastError: unknown;
  for (const delayMs of [0, ...startupRetryDelaysMs]) {
    if (delayMs > 0) {
      await delay(delayMs);
    }
    try {
      return await request();
    } catch (error) {
      lastError = error;
      if (!isTransientStartupError(error)) {
        throw error;
      }
    }
  }
  throw lastError;
}

function isTransientStartupError(error: unknown) {
  if (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    typeof error.status === "number"
  ) {
    return error.status === 0 || error.status >= 500;
  }
  const message = error instanceof Error ? error.message : String(error);
  return /ECONNREFUSED|Failed to fetch|NetworkError|network request/i.test(
    message,
  );
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
