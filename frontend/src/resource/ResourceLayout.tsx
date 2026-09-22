import {
  DashboardOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  ImportOutlined,
  TrophyOutlined,
} from "@ant-design/icons";
import type { MenuDataItem } from "@ant-design/pro-components";
import { PageContainer, ProLayout } from "@ant-design/pro-components";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Link,
  Navigate,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import type { User } from "../types";

function resourceRouteFor(user: User | null, t: (key: string) => string) {
  const routes: MenuDataItem[] = [
    {
      path: "/resources/dashboard",
      name: t("navigation.resourceOverview"),
      icon: <DashboardOutlined />,
    },
  ];
  if (
    user?.permissions.canViewDataResources ||
    user?.permissions.canChangeDataResources ||
    user?.permissions.canDeleteDataResources ||
    user?.permissions.canUploadData ||
    user?.permissions.canExportData
  ) {
    routes.push({
      path: "/resources/data/inventory",
      name: t("navigation.dataInventory"),
      icon: <DatabaseOutlined />,
    });
  }
  const canManageWorkspaces =
    user?.permissions.canViewWorkspaces ||
    user?.permissions.canChangeWorkspaces ||
    user?.permissions.canDeleteWorkspaces;
  const canManageTopics =
    canManageWorkspaces ||
    user?.permissions.canViewMapCompositions ||
    user?.permissions.canChangeMapCompositions ||
    user?.permissions.canDeleteMapCompositions ||
    user?.permissions.canPublishMapCompositions ||
    user?.permissions.canViewResultArtifacts;
  if (canManageWorkspaces) {
    routes.push({
      path: "/resources/manage/projects",
      name: t("navigation.workspaceProjects"),
      icon: <FolderOpenOutlined />,
    });
  }
  if (canManageTopics) {
    routes.push({
      path: "/resources/manage/topics",
      name: t("navigation.topicManagement"),
      icon: <TrophyOutlined />,
    });
  }
  if (
    user?.permissions.canUploadData ||
    (user?.permissions.canViewResultArtifacts &&
      user.permissions.canImportResultArtifacts &&
      user.permissions.canPublishResultArtifacts)
  ) {
    routes.push({
      path: "/resources/data/import",
      name: t("navigation.dataAndResultImport"),
      icon: <ImportOutlined />,
    });
  }
  return {
    path: "/resources",
    routes,
  };
}

export default function ResourceLayout() {
  const { user } = useAppContext();
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const defaultPageMeta = {
    title: t("navigation.resourceOverview"),
    subTitle: t("admin.resourceOverviewSubtitle"),
  };
  const pageMeta: Record<string, { title: string; subTitle: string }> = {
    "/resources/dashboard": defaultPageMeta,
    "/resources/data/import": {
      title: t("navigation.dataAndResultImport"),
      subTitle: t("admin.importSubtitle"),
    },
    "/resources/data/inventory": {
      title: t("admin.inventoryTitle"),
      subTitle: t("admin.inventorySubtitle"),
    },
    "/resources/manage/projects": {
      title: t("navigation.workspaceProjects"),
      subTitle: t("admin.projectsSubtitle"),
    },
    "/resources/manage/topics": {
      title: t("navigation.topicManagement"),
      subTitle: t("admin.resultsSubtitle"),
    },
  };
  const meta = pageMeta[location.pathname] ?? defaultPageMeta;
  const resourceRoute = useMemo(() => resourceRouteFor(user, t), [t, user]);

  if (user?.username === "guest") {
    return <Navigate to="/data" replace />;
  }

  return (
    <div className="admin-workspace-shell resource-workspace-shell">
      <WorkspaceHeader
        activeTab="resources"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <ProLayout
        className="admin-pro-layout"
        title={false}
        route={resourceRoute}
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
