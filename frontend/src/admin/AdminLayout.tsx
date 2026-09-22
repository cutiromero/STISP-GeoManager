import {
  AuditOutlined,
  CloudUploadOutlined,
  CalculatorOutlined,
  DashboardOutlined,
  SettingOutlined,
  TeamOutlined,
  ProjectOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { MenuDataItem } from "@ant-design/pro-components";
import { PageContainer, ProLayout } from "@ant-design/pro-components";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import type { User } from "../types";
import { canManageProjects } from "../router";

function adminRouteFor(user: User | null, t: (key: string) => string) {
  const profileRoute: MenuDataItem = {
    path: "/admin/profile",
    name: t("navigation.userSettings"),
    icon: <UserOutlined />,
  };
  const routes: MenuDataItem[] = user?.permissions.canAccessAdmin
    ? [
        {
          path: "/admin/dashboard",
          name: t("navigation.runningOverview"),
          icon: <DashboardOutlined />,
        },
        profileRoute,
      ]
    : [profileRoute];
  if (
    user?.permissions.canViewOperationLogs ||
    user?.permissions.canViewOwnOperationLogs
  ) {
    routes.push({
      path: "/admin/logs",
      name: t("navigation.logManagement"),
      icon: <AuditOutlined />,
    });
  }
  if (user?.permissions.canManageSystemSettings) {
    routes.push({
      path: "/admin/settings",
      name: t("navigation.systemSettings"),
      icon: <SettingOutlined />,
    });
  }
  if (user?.permissions.canManageDataBackup) {
    routes.push({
      path: "/admin/backup",
      name: t("navigation.dataBackup"),
      icon: <CloudUploadOutlined />,
    });
  }
  if (user?.permissions.canManageAuth) {
    routes.push({
      path: "/admin/auth",
      name: t("admin.authorization"),
      icon: <TeamOutlined />,
      children: [
        {
          path: "/admin/auth/users",
          name: t("navigation.userManagement"),
        },
        {
          path: "/admin/auth/groups",
          name: t("navigation.rolePermissions"),
        },
      ],
    });
  }
  if (canManageProjects(user)) {
    routes.push({
      path: "/admin/agent",
      name: t("navigation.agentManagement"),
      icon: <SettingOutlined />,
    });
    routes.push({
      path: "/admin/projects",
      name: t("navigation.projectManagement"),
      icon: <ProjectOutlined />,
    });
  }
  if (user?.permissions.canAccessAdmin) {
    routes.push({
      path: "/admin/compute",
      name: t("navigation.computeManagement"),
      icon: <CalculatorOutlined />,
    });
  }
  return {
    path: "/admin",
    routes,
  };
}

export default function AdminLayout() {
  const { user } = useAppContext();
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const defaultPageMeta = {
    title: t("navigation.runningOverview"),
    subTitle: t("admin.operationsSubtitle"),
  };
  const pageMeta: Record<string, { title: string; subTitle: string }> = {
    "/admin/agent": {
      title: t("navigation.agentManagement"),
      subTitle: t("navigation.agentManagement"),
    },
    "/admin/compute": {
      title: t("navigation.computeManagement"),
      subTitle: t("navigation.computeManagement"),
    },
    "/admin/dashboard": defaultPageMeta,
    "/admin/projects": {
      title: t("navigation.projectManagement"),
      subTitle: t("admin.projectManagementSubtitle"),
    },
    "/admin/profile": {
      title: t("navigation.userSettings"),
      subTitle: t("admin.profileSubtitle"),
    },
    "/admin/logs": {
      title: t("navigation.logManagement"),
      subTitle: t("admin.logsSubtitle"),
    },
    "/admin/settings": {
      title: t("navigation.systemSettings"),
      subTitle: t("admin.settingsSubtitle"),
    },
    "/admin/backup": {
      title: t("navigation.dataBackup"),
      subTitle: t("admin.backupSubtitle"),
    },
    "/admin/auth": {
      title: t("admin.authorization"),
      subTitle: t("admin.authorizationSubtitle"),
    },
    "/admin/auth/users": {
      title: t("admin.authorization"),
      subTitle: t("admin.authorizationSubtitle"),
    },
    "/admin/auth/groups": {
      title: t("admin.authorization"),
      subTitle: t("admin.authorizationSubtitle"),
    },
  };
  const meta = pageMeta[location.pathname] ?? defaultPageMeta;
  const adminRoute = useMemo(() => adminRouteFor(user, t), [t, user]);

  return (
    <div className="admin-workspace-shell">
      <WorkspaceHeader
        activeTab="admin"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <ProLayout
        className="admin-pro-layout"
        title={false}
        route={adminRoute}
        location={{ pathname: location.pathname }}
        layout="mix"
        headerRender={false}
        fixSiderbar
        contentWidth="Fluid"
        colorPrimary="#2f7d62"
        menuItemRender={(item: MenuDataItem, dom) =>
          item.path ? <Link to={item.path}>{dom}</Link> : dom
        }
        onMenuHeaderClick={() => navigate("/map")}
        token={{
          header: {
            heightLayoutHeader: 90,
          },
          sider: {
            colorMenuBackground: "#fbfdfb",
            colorTextMenu: "#31423d",
            colorTextMenuSelected: "#173f39",
            colorBgMenuItemSelected: "rgba(47, 125, 98, 0.1)",
          },
        }}
        pageTitleRender={false}
      >
        <PageContainer
          title={meta.title}
          subTitle={meta.subTitle}
          className="admin-page-container"
        >
          <Outlet />
        </PageContainer>
      </ProLayout>
    </div>
  );
}
