import { Navigate, Outlet } from "react-router-dom";
import { useAppContext } from "./contexts/AppContext";

/** 需要登录才能访问的路由守卫 */
export function RequireAuth() {
  const { user } = useAppContext();
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

/** The shared guest account has no writable personal settings. */
export function RequireAccountSelfService() {
  const { user } = useAppContext();
  const isGuest =
    user?.username === "guest" || Boolean(user?.roles.includes("游客"));
  if (isGuest) {
    return <Navigate to="/map" replace />;
  }
  return <Outlet />;
}

/** 需要至少一项后台运维能力才能访问运行概览和管理页面 */
export function RequireAdminAccess() {
  const { user } = useAppContext();
  if (!user?.permissions.canAccessAdmin) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 后台根路径按权限进入运行概览或个人设置 */
export function AdminIndexRedirect() {
  const { user } = useAppContext();
  return (
    <Navigate
      to={
        user?.permissions.canAccessAdmin ? "/admin/dashboard" : "/admin/profile"
      }
      replace
    />
  );
}

/** 需要数据维护权限才能访问的后台数据管理路由 */
export function RequireDataMaintain() {
  const { user } = useAppContext();
  if (
    !user?.permissions.canChangeDataResources &&
    !user?.permissions.canDeleteDataResources
  ) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 需要存量数据查看、上传或维护权限才能访问资源清单路由 */
export function RequireDataInventory() {
  const { user } = useAppContext();
  if (
    !user?.permissions.canViewDataResources &&
    !user?.permissions.canChangeDataResources &&
    !user?.permissions.canDeleteDataResources &&
    !user?.permissions.canUploadData &&
    !user?.permissions.canExportData
  ) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 需要数据上传或数据维护权限才能访问的后台导入路由 */
export function RequireDataUpload() {
  const { user } = useAppContext();
  if (
    !user?.permissions.canUploadData &&
    !(
      user?.permissions.canViewResultArtifacts &&
      user?.permissions.canImportResultArtifacts &&
      user.permissions.canPublishResultArtifacts
    )
  ) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 需要工程或专题制图相关权限才能访问对应存量管理页面 */
export function RequireWorkspaceInventory() {
  const { user } = useAppContext();
  if (
    !user?.permissions.canViewWorkspaces &&
    !user?.permissions.canChangeWorkspaces &&
    !user?.permissions.canDeleteWorkspaces &&
    !user?.permissions.canViewMapCompositions &&
    !user?.permissions.canChangeMapCompositions &&
    !user?.permissions.canDeleteMapCompositions &&
    !user?.permissions.canPublishMapCompositions &&
    !user?.permissions.canViewResultArtifacts
  ) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 登录用户均可查看自己的操作日志，更高日志范围由后端裁剪 */
export function RequireViewOperationLogs() {
  const { user } = useAppContext();
  if (
    !user?.permissions.canViewOperationLogs &&
    !user?.permissions.canViewOwnOperationLogs
  ) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 需要修改系统设置权限才能访问的路由 */
export function RequireManageSystemSettings() {
  const { user } = useAppContext();
  if (!user?.permissions.canManageSystemSettings) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 需要数据备份权限才能访问的路由 */
export function RequireManageDataBackup() {
  const { user } = useAppContext();
  if (!user?.permissions.canManageDataBackup) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

/** 需要修改认证授权权限才能访问的路由 */
export function RequireManageAuth() {
  const { user } = useAppContext();
  if (!user?.permissions.canManageAuth) {
    return <Navigate to="/admin/profile" replace />;
  }
  return <Outlet />;
}

export function canManageProjects(
  user: ReturnType<typeof useAppContext>["user"],
) {
  return Boolean(user?.isSuperuser || user?.roles.includes("超级管理员"));
}

export function RequireManageProjects() {
  const { user } = useAppContext();
  return canManageProjects(user) ? (
    <Outlet />
  ) : (
    <Navigate to="/admin/profile" replace />
  );
}

/** 已登录用户访问登录页时重定向到首页 */
export function RedirectIfAuth() {
  const { user } = useAppContext();
  if (user) {
    return <Navigate to="/map" replace />;
  }
  return <Outlet />;
}
