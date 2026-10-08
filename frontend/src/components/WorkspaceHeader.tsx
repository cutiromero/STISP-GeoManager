import { ProjectLabel } from "../projects/ProjectLabel";
import { resetProjectSession } from "../projects/session";
import { ProjectSelector } from "../projects/ProjectContext";
import {
  AlertOutlined,
  ApartmentOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { MenuProps, TourProps } from "antd";
import {
  App,
  Avatar,
  Button,
  Dropdown,
  Empty,
  Input,
  Popover,
  Tag,
  Tour,
  Tooltip,
  Typography,
} from "antd";
import type { ComponentPropsWithRef, MouseEvent, ReactNode } from "react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { api } from "../api/client";
import ColumnIcon from "./ColumnIcon";
import stispLogoWhite from "../assets/stisp-logo-white.svg";
import { platformBrand } from "../config/platformBrand";
import { useAppContext } from "../contexts/AppContext";
import { canManageProjects } from "../router";
import { currentLocale } from "../i18n";
import type {
  DataDomainType,
  DataSchemaCatalogNode,
  DataSchemaSummary,
  MapComposition,
  ResourceListItem,
  WorkspaceSceneSummary,
} from "../types";
import {
  resourceCategoryName,
  resourceFormatLabel,
  resourceProvider,
} from "../utils/resources";
import { clearCachedLayerGroups } from "../utils/layerWorkspaceStorage";
import { taxonomyTree } from "../utils/taxonomy";
import { aboutNavigationSections } from "../about/aboutSections";
import { useAgentBootstrap } from "../agent/useAgentBootstrap";
import LanguageSwitcher from "./LanguageSwitcher";

export type WorkspaceTab =
  | "home"
  | "map"
  | "nongeo"
  | "results"
  | "warning"
  | "resources"
  | "compute"
  | "admin"
  | "news"
  | "knowledge"
  | "knowledgeBase"
  | "about";

const platformChineseName = platformBrand.chineseName;
const searchOpenDelayMs = 400;

function NavigationButton(props: ComponentPropsWithRef<typeof Button>) {
  return (
    <Tooltip
      title={props.title}
      trigger={["hover", "focus"]}
      mouseEnterDelay={0.1}
      mouseLeaveDelay={0}
    >
      <Button {...props} />
    </Tooltip>
  );
}

function AgentNavigationButton({
  className,
  onNavigate,
  title,
}: {
  className: string;
  onNavigate: (path: string) => void;
  title: string;
}) {
  const access = useAgentBootstrap();
  if (!access?.canChat && !access?.canAgent) return null;
  return (
    <NavigationButton
      type="text"
      className={className}
      onClick={() =>
        onNavigate(access.canChat ? "/agent/chat" : "/agent/workbench")
      }
      title={title}
    >
      <AlertOutlined aria-hidden="true" style={{ fontSize: 16 }} />
      <span className="tab-text">{title}</span>
    </NavigationButton>
  );
}

interface WorkspaceHeaderProps {
  activeTab: WorkspaceTab;
  canBrowseData: boolean;
  resources?: ResourceListItem[];
  workspaceScenes?: WorkspaceSceneSummary[];
  mapCompositions?: MapComposition[];
  dataSchema?: DataSchemaSummary | null;
  searchKeyword?: string;
  onGlobalSearch?: (keyword: string) => void;
  onQuickLoadResource?: (resource: ResourceListItem) => Promise<void> | void;
  onLoadWorkspaceScene?: (scene: WorkspaceSceneSummary) => void;
  onLoadMapComposition?: (composition: MapComposition) => void;
  onSearchFocus?: () => void;
}

export default function WorkspaceHeader({
  activeTab,
  canBrowseData,
  resources,
  workspaceScenes,
  mapCompositions,
  dataSchema,
  searchKeyword = "",
  onGlobalSearch,
  onQuickLoadResource,
  onLoadWorkspaceScene,
  onLoadMapComposition,
  onSearchFocus,
}: WorkspaceHeaderProps) {
  const { user, setUser } = useAppContext();
  const { message } = App.useApp();
  const { t, i18n: translationI18n } = useTranslation();
  const platformDisplayName =
    currentLocale() === "en-US"
      ? platformBrand.englishName
      : platformChineseName;
  const navigate = useNavigate();
  const [searchText, setSearchText] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [quickLoadingResourceId, setQuickLoadingResourceId] = useState<
    ResourceListItem["id"] | null
  >(null);
  const [localResources, setLocalResources] = useState<ResourceListItem[]>([]);
  const [localWorkspaceScenes, setLocalWorkspaceScenes] = useState<
    WorkspaceSceneSummary[]
  >([]);
  const [localMapCompositions, setLocalMapCompositions] = useState<
    MapComposition[]
  >([]);
  const [localDataSchema, setLocalDataSchema] =
    useState<DataSchemaSummary | null>(null);
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [searchCompact, setSearchCompact] = useState(false);
  const [navCompressed, setNavCompressed] = useState(false);
  const [navMeasured, setNavMeasured] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [userPopoverOpen, setUserPopoverOpen] = useState(false);
  const [searchPopoverWidth, setSearchPopoverWidth] = useState<
    number | undefined
  >();
  const searchNavRef = useRef<HTMLDivElement | null>(null);
  const searchContainerRef = useRef<HTMLElement | null>(null);
  const primaryNavRef = useRef<HTMLElement | null>(null);
  const mapTabRef = useRef<HTMLButtonElement | null>(null);
  const nonGeoTabRef = useRef<HTMLButtonElement | null>(null);
  const resourcesTabRef = useRef<HTMLButtonElement | null>(null);
  const adminTabRef = useRef<HTMLButtonElement | null>(null);
  const aboutTabRef = useRef<HTMLButtonElement | null>(null);
  const userButtonRef = useRef<HTMLButtonElement | null>(null);
  const searchOpenTimerRef = useRef<number | null>(null);
  const navMeasureTimerRef = useRef<number | null>(null);
  const layoutMeasureFrameRef = useRef<number | null>(null);
  const fullPrimaryNavWidthRef = useRef(0);
  const lastMeasuredLanguageRef = useRef(translationI18n.resolvedLanguage);
  useEffect(() => {
    if (!user?.permissions.canViewWorkspaces || !searchText.trim()) return;
    let active = true;
    const timer = setTimeout(() => {
      void api
        .workspaces({ q: searchText.trim(), limit: 100 })
        .then((result) => {
          if (active) setLocalWorkspaceScenes(result.items);
        })
        .catch(() => {});
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [searchText, user?.permissions.canViewWorkspaces]);
  const effectiveResources = resources ?? localResources;
  const effectiveWorkspaceScenes = searchText.trim()
    ? localWorkspaceScenes
    : (workspaceScenes ?? localWorkspaceScenes);
  const effectiveMapCompositions = mapCompositions ?? localMapCompositions;
  const effectiveDataSchema = dataSchema ?? localDataSchema;
  const domainTypeLabelByValue = useMemo(
    () => domainTypeLabels(effectiveDataSchema, t),
    [effectiveDataSchema, t],
  );
  const isGuestUser =
    user?.username === "guest" || Boolean(user?.roles.includes("游客"));
  const userDisplayLabel = isGuestUser
    ? t("common.guestUser")
    : localizedBuiltInDisplayName(
        user?.displayName || user?.username || t("common.currentUser"),
        t,
      );
  const showAdminTab =
    Boolean(user?.permissions.canAccessAdmin) && !isGuestUser;
  const showProjectManagement = canManageProjects(user);
  const showResourceCenter = true;
  const showDataImportShortcut = Boolean(
    user?.permissions.canUploadData ||
    (user?.permissions.canViewResultArtifacts &&
      user.permissions.canImportResultArtifacts &&
      user.permissions.canPublishResultArtifacts),
  );

  useEffect(() => {
    setSearchText(searchKeyword);
  }, [searchKeyword]);

  useEffect(() => {
    const shouldLoadResources = resources === undefined && canBrowseData;
    const shouldLoadWorkspaceScenes =
      workspaceScenes === undefined &&
      Boolean(user?.permissions.canViewWorkspaces);
    const shouldLoadMapCompositions =
      mapCompositions === undefined &&
      Boolean(user?.permissions.canViewMapCompositions);
    if (
      !shouldLoadResources &&
      !shouldLoadWorkspaceScenes &&
      !shouldLoadMapCompositions
    ) {
      return;
    }
    let mounted = true;
    async function loadGlobalSearchItems() {
      const [resourceResult, sceneResult, compositionResult] =
        await Promise.allSettled([
          shouldLoadResources ? api.resources({}) : null,
          shouldLoadWorkspaceScenes ? api.workspaces() : null,
          shouldLoadMapCompositions ? api.mapCompositions() : null,
        ]);
      if (!mounted) {
        return;
      }
      if (resourceResult.status === "fulfilled" && resourceResult.value) {
        setLocalResources(resourceResult.value.items);
      }
      if (sceneResult.status === "fulfilled" && sceneResult.value) {
        setLocalWorkspaceScenes(sceneResult.value.items);
      }
      if (compositionResult.status === "fulfilled" && compositionResult.value) {
        setLocalMapCompositions(compositionResult.value.items);
      }
      const failedResult = [
        resourceResult,
        sceneResult,
        compositionResult,
      ].find((result) => result.status === "rejected");
      if (failedResult?.status === "rejected") {
        message.warning(
          failedResult.reason instanceof Error
            ? failedResult.reason.message
            : t("navigation.globalSearchLoadFailed"),
        );
      }
    }
    void loadGlobalSearchItems();
    return () => {
      mounted = false;
    };
  }, [
    canBrowseData,
    mapCompositions,
    message,
    resources,
    t,
    user?.permissions.canViewMapCompositions,
    user?.permissions.canViewWorkspaces,
    workspaceScenes,
  ]);

  useEffect(() => {
    if (!canBrowseData || dataSchema !== undefined) {
      return;
    }
    const loadSchema = (
      api as { dataSchemaSummary?: typeof api.dataSchemaSummary }
    ).dataSchemaSummary;
    if (!loadSchema) {
      return;
    }
    let mounted = true;
    loadSchema()
      .then((result) => {
        if (mounted) {
          setLocalDataSchema(result);
        }
      })
      .catch(() => {
        if (mounted) {
          setLocalDataSchema(null);
        }
      });
    return () => {
      mounted = false;
    };
  }, [canBrowseData, dataSchema]);

  useEffect(() => {
    navMeasureTimerRef.current = window.setTimeout(() => {
      setNavMeasured(true);
      navMeasureTimerRef.current = null;
    }, 120);
    return () => {
      if (navMeasureTimerRef.current !== null) {
        window.clearTimeout(navMeasureTimerRef.current);
        navMeasureTimerRef.current = null;
      }
    };
  }, []);

  const syncSearchPopoverWidth = useCallback(() => {
    const width = searchContainerRef.current?.getBoundingClientRect().width;
    if (width && Number.isFinite(width)) {
      setSearchPopoverWidth(Math.round(width));
    }
  }, []);

  const measureNavFit = useCallback(() => {
    const nav = searchNavRef.current;
    const search = searchContainerRef.current;
    const primaryNav = primaryNavRef.current;
    if (!nav || !search || !primaryNav) return;

    const primaryNavWidth = primaryNav.scrollWidth;
    if (!navCompressed || !searchExpanded) {
      fullPrimaryNavWidthRef.current = Math.max(
        fullPrimaryNavWidthRef.current,
        primaryNavWidth,
      );
    }

    const navStyle = window.getComputedStyle(nav);
    const navGap =
      Number.parseFloat(navStyle.columnGap || navStyle.gap || "0") || 0;
    const rootFontSize =
      Number.parseFloat(
        window.getComputedStyle(document.documentElement).fontSize,
      ) || 16;
    const navWidth = nav.clientWidth;
    const searchMinWidth = clampNumber(
      3.75 * rootFontSize,
      0.08 * navWidth,
      5 * rootFontSize,
    );
    const searchCollapsedWidth = clampNumber(
      searchMinWidth,
      0.22 * navWidth,
      11 * rootFontSize,
    );
    const searchMaxWidth = clampNumber(
      searchCollapsedWidth * 2,
      0.44 * navWidth,
      22 * rootFontSize,
    );
    const fullTabsWidth = fullPrimaryNavWidthRef.current;
    const expandedFits =
      fullTabsWidth + searchMaxWidth + navGap <= navWidth + 1;
    const compactFits = fullTabsWidth + searchMinWidth + navGap <= navWidth + 1;
    const shouldCompactSearch = !searchExpanded && !expandedFits;
    const shouldCompressTabs = searchExpanded ? !expandedFits : !compactFits;

    setSearchCompact((current) =>
      current === shouldCompactSearch ? current : shouldCompactSearch,
    );
    setNavCompressed((current) =>
      current === shouldCompressTabs ? current : shouldCompressTabs,
    );
  }, [navCompressed, searchExpanded]);

  const scheduleLayoutMeasure = useCallback(() => {
    if (layoutMeasureFrameRef.current !== null) {
      return;
    }
    layoutMeasureFrameRef.current = window.requestAnimationFrame(() => {
      layoutMeasureFrameRef.current = null;
      syncSearchPopoverWidth();
      measureNavFit();
    });
  }, [measureNavFit, syncSearchPopoverWidth]);

  const expandSearch = useCallback(() => {
    setSearchExpanded(true);
    scheduleLayoutMeasure();
  }, [scheduleLayoutMeasure]);

  const scheduleSearchOpen = useCallback(
    (delay = 0) => {
      if (searchOpenTimerRef.current !== null) {
        window.clearTimeout(searchOpenTimerRef.current);
      }
      searchOpenTimerRef.current = window.setTimeout(() => {
        syncSearchPopoverWidth();
        setSearchOpen(true);
        searchOpenTimerRef.current = null;
      }, delay);
    },
    [syncSearchPopoverWidth],
  );

  const openSearchPanel = useCallback(
    (delay = 0) => {
      expandSearch();
      onSearchFocus?.();
      scheduleSearchOpen(delay);
    },
    [expandSearch, onSearchFocus, scheduleSearchOpen],
  );

  const closeSearchPanel = useCallback(() => {
    if (searchOpenTimerRef.current !== null) {
      window.clearTimeout(searchOpenTimerRef.current);
      searchOpenTimerRef.current = null;
    }
    setSearchOpen(false);
    setSearchExpanded(false);
    scheduleLayoutMeasure();
  }, [scheduleLayoutMeasure]);

  useLayoutEffect(() => {
    const container = searchContainerRef.current;
    if (!container) return;
    scheduleLayoutMeasure();
    const observer = new ResizeObserver(scheduleLayoutMeasure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [scheduleLayoutMeasure]);

  useLayoutEffect(() => {
    const nav = searchNavRef.current;
    const search = searchContainerRef.current;
    const primaryNav = primaryNavRef.current;
    if (!nav || !search || !primaryNav) return;

    scheduleLayoutMeasure();
    const observer = new ResizeObserver(scheduleLayoutMeasure);
    observer.observe(nav);
    observer.observe(search);
    observer.observe(primaryNav);
    return () => observer.disconnect();
  }, [scheduleLayoutMeasure]);

  useLayoutEffect(() => {
    scheduleLayoutMeasure();
  }, [scheduleLayoutMeasure]);

  useLayoutEffect(() => {
    if (lastMeasuredLanguageRef.current === translationI18n.resolvedLanguage) {
      return;
    }
    lastMeasuredLanguageRef.current = translationI18n.resolvedLanguage;
    fullPrimaryNavWidthRef.current = 0;
    setNavCompressed(false);
    setSearchCompact(false);
    const frame = window.requestAnimationFrame(() => {
      scheduleLayoutMeasure();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [scheduleLayoutMeasure, translationI18n.resolvedLanguage]);

  useEffect(() => {
    return () => {
      if (searchOpenTimerRef.current !== null) {
        window.clearTimeout(searchOpenTimerRef.current);
      }
      if (navMeasureTimerRef.current !== null) {
        window.clearTimeout(navMeasureTimerRef.current);
      }
      if (layoutMeasureFrameRef.current !== null) {
        window.cancelAnimationFrame(layoutMeasureFrameRef.current);
        layoutMeasureFrameRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      const targetNode = event.target instanceof Node ? event.target : null;
      const targetElement =
        event.target instanceof Element ? event.target : null;
      if (
        (targetNode && searchContainerRef.current?.contains(targetNode)) ||
        targetElement?.closest(".workspace-search-popover")
      ) {
        return;
      }
      closeSearchPanel();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [closeSearchPanel]);

  const searchQuery = searchText.trim().toLocaleLowerCase("zh-CN");
  const filteredResources = useMemo(
    () =>
      effectiveResources.filter((resource) =>
        searchQuery
          ? resourceMatches(resource, searchQuery, domainTypeLabelByValue)
          : true,
      ),
    [domainTypeLabelByValue, effectiveResources, searchQuery],
  );
  const filteredWorkspaceScenes = useMemo(
    () =>
      effectiveWorkspaceScenes.filter((scene) =>
        searchQuery ? sceneMatches(scene, searchQuery) : true,
      ),
    [effectiveWorkspaceScenes, searchQuery],
  );
  const filteredProjectScenes = useMemo(
    () => filteredWorkspaceScenes,
    [filteredWorkspaceScenes],
  );
  const filteredTopicScenes = useMemo(
    () =>
      effectiveMapCompositions.filter((composition) =>
        searchQuery ? compositionMatches(composition, searchQuery) : true,
      ),
    [effectiveMapCompositions, searchQuery],
  );

  async function handleLogout() {
    try {
      await api.logout();
    } catch (error) {
      message.warning(
        error instanceof Error ? error.message : t("navigation.logoutFallback"),
      );
    } finally {
      try {
        await clearCachedLayerGroups();
      } catch (error) {
        console.warn("清理本地图层缓存失败", error);
      }
      resetProjectSession();
      if (user) sessionStorage.removeItem(`project:${user.id}`);
      setUser(null);
      navigate("/login", { replace: true });
    }
  }

  function handleSearchTextChange(value: string) {
    setSearchText(value);
    if (searchOpen) {
      openSearchPanel(0);
    } else {
      expandSearch();
    }
    onGlobalSearch?.(value.trim());
  }

  function handleSearchClick() {
    const currentWidth =
      searchContainerRef.current?.getBoundingClientRect().width;
    const visuallyExpanded = currentWidth ? currentWidth > 220 : false;
    openSearchPanel(searchExpanded || visuallyExpanded ? 0 : searchOpenDelayMs);
  }

  function handleMobileSearchClick(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    openSearchPanel(0);
    window.requestAnimationFrame(() => {
      searchContainerRef.current?.querySelector("input")?.focus();
    });
  }

  function commitSearch(value: string) {
    const keyword = value.trim();
    const query = keyword ? `?resourceQ=${encodeURIComponent(keyword)}` : "";
    navigate(`/map${query}`);
    onGlobalSearch?.(keyword);
    closeSearchPanel();
  }

  async function quickLoadResource(resource: ResourceListItem) {
    if (onQuickLoadResource) {
      setQuickLoadingResourceId(resource.id);
      try {
        await onQuickLoadResource(resource);
        closeSearchPanel();
      } finally {
        setQuickLoadingResourceId((current) =>
          current === resource.id ? null : current,
        );
      }
      return;
    }
    navigate(`/map?resourceQ=${encodeURIComponent(resource.name)}`);
    onGlobalSearch?.(resource.name);
    closeSearchPanel();
  }

  function openWorkspaceScene(scene: WorkspaceSceneSummary) {
    if (onLoadWorkspaceScene) {
      onLoadWorkspaceScene(scene);
    } else {
      navigate(`/map?sceneId=${scene.id}`);
    }
    setSearchOpen(false);
    closeSearchPanel();
  }

  function openMapComposition(composition: MapComposition) {
    if (onLoadMapComposition) {
      onLoadMapComposition(composition);
    } else {
      navigate(`/map?compositionId=${composition.id}`);
    }
    setSearchOpen(false);
    closeSearchPanel();
  }

  const dismissSearchForNavigation = useCallback(() => {
    closeSearchPanel();
    const activeElement = document.activeElement;
    if (
      activeElement instanceof HTMLElement &&
      searchContainerRef.current?.contains(activeElement)
    ) {
      activeElement.blur();
    }
  }, [closeSearchPanel]);

  const navigateFromHeader = useCallback(
    (path: string) => {
      dismissSearchForNavigation();
      navigate(path);
    },
    [dismissSearchForNavigation, navigate],
  );

  function handleResourceCenter() {
    if (!showResourceCenter) {
      message.warning(t("navigation.noResourceBrowsePermission"));
      return;
    }
    navigateFromHeader("/resources/catalog");
  }

  const mapCategoryMenuItems = useMemo<MenuProps["items"]>(
    () =>
      workspaceCategoryMenuItems(
        taxonomyTree(effectiveDataSchema),
        "/map",
        navigateFromHeader,
        t,
      ),
    [effectiveDataSchema, navigateFromHeader, t],
  );
  const analysisCategoryMenuItems = useMemo<MenuProps["items"]>(
    () =>
      workspaceCategoryMenuItems(
        taxonomyTree(effectiveDataSchema),
        "/nongeo",
        navigateFromHeader,
        t,
      ),
    [effectiveDataSchema, navigateFromHeader, t],
  );

  const dataManagementMenuItems = useMemo<MenuProps["items"]>(() => {
    const items: NonNullable<MenuProps["items"]> = [
      {
        key: "resources-dashboard",
        label: t("navigation.resourceOverview"),
        onClick: () => navigateFromHeader("/resources/catalog"),
      },
    ];
    if (
      user?.permissions.canViewDataResources ||
      user?.permissions.canChangeDataResources ||
      user?.permissions.canDeleteDataResources ||
      user?.permissions.canUploadData ||
      user?.permissions.canExportData
    ) {
      items.push({
        key: "resources-inventory",
        label: t("navigation.dataInventory"),
        onClick: () => navigateFromHeader("/resources/data/inventory"),
      });
    }
    if (
      user?.permissions.canViewWorkspaces ||
      user?.permissions.canChangeWorkspaces ||
      user?.permissions.canDeleteWorkspaces
    ) {
      items.push({
        key: "resources-projects",
        label: t("navigation.workspaceProjects"),
        onClick: () => navigateFromHeader("/resources/manage/projects"),
      });
    }
    if (
      user?.permissions.canViewMapCompositions ||
      user?.permissions.canChangeMapCompositions ||
      user?.permissions.canDeleteMapCompositions ||
      user?.permissions.canPublishMapCompositions ||
      user?.permissions.canViewResultArtifacts
    ) {
      items.push({
        key: "resources-results",
        label: t("navigation.topicManagement"),
        onClick: () => navigateFromHeader("/resources/manage/topics"),
      });
    }
    if (
      user?.permissions.canUploadData ||
      (user?.permissions.canViewResultArtifacts &&
        user.permissions.canImportResultArtifacts &&
        user.permissions.canPublishResultArtifacts)
    ) {
      items.push({
        key: "resources-import",
        label: t("navigation.dataAndResultImport"),
        onClick: () => navigateFromHeader("/resources/data/import"),
      });
    }
    return items;
  }, [
    navigateFromHeader,
    t,
    user?.permissions.canExportData,
    user?.permissions.canChangeDataResources,
    user?.permissions.canChangeMapCompositions,
    user?.permissions.canChangeWorkspaces,
    user?.permissions.canDeleteDataResources,
    user?.permissions.canDeleteMapCompositions,
    user?.permissions.canDeleteResultArtifacts,
    user?.permissions.canDeleteWorkspaces,
    user?.permissions.canImportResultArtifacts,
    user?.permissions.canPublishMapCompositions,
    user?.permissions.canPublishResultArtifacts,
    user?.permissions.canUploadData,
    user?.permissions.canViewDataResources,
    user?.permissions.canViewMapCompositions,
    user?.permissions.canViewResultArtifacts,
    user?.permissions.canViewWorkspaces,
  ]);

  const adminMenuItems = useMemo<MenuProps["items"]>(() => {
    const items: NonNullable<MenuProps["items"]> = [
      {
        key: "admin-dashboard",
        label: t("navigation.runningOverview"),
        onClick: () => navigateFromHeader("/admin/dashboard"),
      },
      {
        key: "admin-profile",
        label: t("navigation.userSettings"),
        onClick: () => navigateFromHeader("/admin/profile"),
      },
    ];
    if (
      user?.permissions.canViewOperationLogs ||
      user?.permissions.canViewOwnOperationLogs
    ) {
      items.push({
        key: "admin-logs",
        label: t("navigation.logManagement"),
        onClick: () => navigateFromHeader("/admin/logs"),
      });
    }
    if (user?.permissions.canManageSystemSettings) {
      items.push({
        key: "admin-settings",
        label: t("navigation.systemSettings"),
        onClick: () => navigateFromHeader("/admin/settings"),
      });
    }
    if (user?.permissions.canManageDataBackup) {
      items.push({
        key: "admin-backup",
        label: t("navigation.dataBackup"),
        onClick: () => navigateFromHeader("/admin/backup"),
      });
    }
    if (user?.permissions.canManageAuth) {
      items.push(
        {
          key: "admin-users",
          label: t("navigation.userManagement"),
          onClick: () => navigateFromHeader("/admin/auth/users"),
        },
        {
          key: "admin-groups",
          label: t("navigation.rolePermissions"),
          onClick: () => navigateFromHeader("/admin/auth/groups"),
        },
      );
    }
    if (showProjectManagement) {
      items.push({
        key: "admin-agent",
        label: t("navigation.agentManagement"),
        onClick: () => navigateFromHeader("/admin/agent"),
      });
      items.push({
        key: "admin-projects",
        label: t("navigation.projectManagement"),
        onClick: () => navigateFromHeader("/admin/projects"),
      });
    }
    if (user?.permissions.canAccessAdmin) {
      items.push({
        key: "admin-compute",
        label: t("navigation.computeManagement"),
        onClick: () => navigateFromHeader("/admin/compute"),
      });
    }
    return items;
  }, [
    navigateFromHeader,
    showProjectManagement,
    t,
    user?.permissions.canManageAuth,
    user?.permissions.canManageDataBackup,
    user?.permissions.canManageSystemSettings,
    user?.permissions.canViewOperationLogs,
    user?.permissions.canViewOwnOperationLogs,
    user?.permissions.canAccessAdmin,
  ]);

  const aboutMenuItems = useMemo<MenuProps["items"]>(
    () =>
      aboutNavigationSections.map((section) => ({
        key: section.key,
        label: t(
          section.key === "system"
            ? "navigation.aboutSystem"
            : section.key === "team"
              ? "navigation.aboutTeam"
              : section.key === "contact"
                ? "navigation.aboutContact"
                : "navigation.aboutDocs",
        ),
        onClick: () => navigateFromHeader(section.path),
      })),
    [navigateFromHeader, t],
  );

  const finishTour = useCallback(() => {
    setTourOpen(false);
  }, []);

  const showWorkspaceTour = useCallback(() => {
    setUserPopoverOpen(false);
    closeSearchPanel();
    setTourOpen(true);
  }, [closeSearchPanel]);

  const tourSteps = useMemo<TourProps["steps"]>(() => {
    const steps: NonNullable<TourProps["steps"]> = [
      {
        title: t("navigation.tourWelcomeTitle"),
        description: t("navigation.tourWelcomeDescription", {
          platform: platformDisplayName,
        }),
        target: null,
      },
      {
        title: t("navigation.openSearch"),
        description: t("navigation.tourSearchDescription"),
        target: () => searchContainerRef.current ?? document.body,
        placement: "bottom",
      },
      {
        title: t("navigation.mapWorkspace"),
        description: t("navigation.tourMapDescription"),
        target: () => mapTabRef.current ?? document.body,
        placement: "bottom",
      },
      {
        title: t("navigation.analytics"),
        description: t("navigation.tourAnalyticsDescription"),
        target: () => nonGeoTabRef.current ?? document.body,
        placement: "bottom",
      },
    ];

    if (showResourceCenter) {
      steps.push({
        title: t("navigation.dataResources"),
        description: t("navigation.tourResourcesDescription"),
        target: () => resourcesTabRef.current ?? document.body,
        placement: "bottom",
      });
    }

    if (showAdminTab) {
      steps.push({
        title: t("navigation.administration"),
        description: t("navigation.tourAdminDescription"),
        target: () => adminTabRef.current ?? document.body,
        placement: "bottom",
      });
    }

    steps.push(
      {
        title: t("navigation.results"),
        description: t("navigation.tourResultsDescription"),
        target: () =>
          document.querySelector('[data-nav-key="results"]') ?? document.body,
        placement: "bottom",
      },
      {
        title: t("navigation.about"),
        description: t("navigation.tourAboutDescription"),
        target: () => aboutTabRef.current ?? document.body,
        placement: "bottom",
      },
      {
        title: t("navigation.tourUserTitle"),
        description: isGuestUser
          ? t("navigation.tourGuestDescription")
          : t("navigation.tourUserDescription"),
        target: () => userButtonRef.current ?? document.body,
        placement: "bottomRight",
      },
    );

    return steps;
  }, [isGuestUser, platformDisplayName, showAdminTab, showResourceCenter, t]);

  const dataButton = (
    <Dropdown
      menu={{ items: dataManagementMenuItems }}
      trigger={["hover"]}
      placement="bottom"
      classNames={{ root: "workspace-management-dropdown" }}
    >
      <NavigationButton
        ref={resourcesTabRef}
        type="text"
        className={`${tabClass(activeTab === "resources")} workspace-switch-card-data-management`}
        onClick={handleResourceCenter}
        title={t("navigation.dataResources")}
      >
        <ColumnIcon name="data" style={{ fontSize: 16 }} />
        <span className="tab-text">{t("navigation.dataResources")}</span>
      </NavigationButton>
    </Dropdown>
  );

  const userContent = (
    <div className="user-popover-content">
      <div className="user-popover-head">
        <Avatar
          size={42}
          src={user?.avatarUrl || undefined}
          icon={<UserOutlined />}
        />
        <span>
          <strong>{userDisplayLabel}</strong>
          <small>{user?.username}</small>
        </span>
      </div>
      <div className="user-popover-meta">
        {user?.department && (
          <span>
            {t("common.department")}: {user.department}
          </span>
        )}
        {user?.email && (
          <span>
            {t("common.email")}: {user.email}
          </span>
        )}
      </div>
      <div className="user-popover-actions">
        <Button
          size="small"
          icon={<QuestionCircleOutlined />}
          onClick={showWorkspaceTour}
        >
          {t("navigation.showTour")}
        </Button>
        {!isGuestUser && (
          <Button size="small" onClick={() => navigate("/admin/profile")}>
            {t("navigation.personalInformation")}
          </Button>
        )}
        <Button size="small" icon={<LogoutOutlined />} onClick={handleLogout}>
          {t("navigation.logout")}
        </Button>
      </div>
    </div>
  );

  const searchContent = (
    <section
      className="workspace-search-results"
      aria-label={t("navigation.globalSearchResults")}
    >
      <SearchResultSection
        title={t("navigation.searchData")}
        icon={<ColumnIcon name="data" style={{ fontSize: 15 }} />}
        emptyText={t("navigation.noMatchingData")}
      >
        {filteredResources.map((resource) => (
          <div className="workspace-search-row" key={`resource-${resource.id}`}>
            <span className="workspace-search-row-main">
              <strong>{resource.name}</strong>
              <small>
                {resourceDomainCategoryName(resource, domainTypeLabelByValue) ??
                  t("common.uncategorized")}{" "}
                · {resourceFormatLabel(resource)}
              </small>
            </span>
            <Button
              size="small"
              type="primary"
              ghost
              disabled={!resource.isQueryable && !resource.isRenderable}
              loading={quickLoadingResourceId === resource.id}
              onClick={() => void quickLoadResource(resource)}
            >
              {t("map.quickLoad")}
            </Button>
          </div>
        ))}
      </SearchResultSection>

      <SearchResultSection
        title={t("navigation.searchProjects")}
        icon={<FolderOpenOutlined style={{ fontSize: 15 }} />}
        emptyText={t("navigation.noMatchingProjects")}
      >
        {filteredProjectScenes.map((scene) => (
          <div className="workspace-search-row" key={`scene-${scene.id}`}>
            <span className="workspace-search-row-main">
              <strong>{scene.name}</strong>
              <ProjectLabel id={scene.projectTagId} />
              <small>{scene.description || formatSceneUpdatedAt(scene)}</small>
            </span>
            <Button
              size="small"
              type="primary"
              ghost
              onClick={() => openWorkspaceScene(scene)}
            >
              {t("map.load")}
            </Button>
          </div>
        ))}
      </SearchResultSection>

      <SearchResultSection
        title={t("navigation.searchTopics")}
        icon={<ColumnIcon name="project" style={{ fontSize: 15 }} />}
        emptyText={t("navigation.noMatchingResults")}
      >
        {filteredTopicScenes.map((composition) => (
          <div
            className="workspace-search-row"
            key={`composition-${composition.id}`}
          >
            <span className="workspace-search-row-main">
              <strong>{composition.name}</strong>
              <ProjectLabel id={composition.projectTagId} />
              <small>
                {composition.projectName} · {formatSceneUpdatedAt(composition)}
              </small>
            </span>
            <Button
              size="small"
              type="primary"
              ghost
              onClick={() => openMapComposition(composition)}
            >
              {t("map.load")}
            </Button>
          </div>
        ))}
      </SearchResultSection>
    </section>
  );

  return (
    <header
      className={`workspace-header${navMeasured ? " workspace-header-nav-measured" : " workspace-header-nav-measuring"}${searchExpanded ? " workspace-header-search-active" : ""}${searchCompact ? " workspace-header-search-compact" : ""}${navCompressed ? " workspace-header-nav-compressed" : ""}`}
    >
      <button
        type="button"
        className="brand-block"
        onClick={() => navigateFromHeader("/map")}
        aria-label={t("navigation.returnToCatalog")}
        title={t("navigation.returnToCatalog")}
      >
        <span className="brand-logo-frame">
          <img
            src={stispLogoWhite}
            alt={`${platformDisplayName} Logo`}
            width={40}
            height={40}
          />
        </span>
        <div className="brand-copy">
          <strong>{platformBrand.shortName}</strong>
          <Typography.Title level={4}>{platformDisplayName}</Typography.Title>
        </div>
      </button>

      <div
        ref={searchNavRef}
        className={`workspace-search-nav${navCompressed ? " workspace-search-nav-compressed" : ""}`}
      >
        <Button
          type="text"
          className="workspace-mobile-search-trigger"
          aria-label={t("navigation.openSearch")}
          icon={<SearchOutlined />}
          onClick={handleMobileSearchClick}
        />
        <Popover
          trigger="click"
          placement="bottomLeft"
          open={searchOpen}
          styles={{
            content: {
              width: searchPopoverWidth,
            },
          }}
          classNames={{ root: "workspace-search-popover" }}
          content={searchContent}
        >
          <search ref={searchContainerRef} className="workspace-global-search">
            <Input
              className="workspace-global-input"
              allowClear
              prefix={<SearchOutlined style={{ fontSize: 15 }} />}
              value={searchText}
              placeholder={t("navigation.searchPlaceholder")}
              onFocus={expandSearch}
              onClick={handleSearchClick}
              onChange={(event) => handleSearchTextChange(event.target.value)}
              onPressEnter={(event) => commitSearch(event.currentTarget.value)}
            />
          </search>
        </Popover>

        <nav
          ref={primaryNavRef}
          className="header-primary-actions"
          aria-label={t("navigation.mainNavigation")}
        >
          <Dropdown
            menu={{ items: mapCategoryMenuItems }}
            trigger={["hover"]}
            placement="bottom"
            classNames={{ root: "workspace-management-dropdown" }}
          >
            <NavigationButton
              ref={mapTabRef}
              type="text"
              className={tabClass(activeTab === "map")}
              onClick={() => navigateFromHeader("/map")}
              title={t("navigation.mapWorkspace")}
            >
              <ColumnIcon
                name="map"
                aria-hidden="true"
                style={{ fontSize: 16 }}
              />
              <span className="tab-text">{t("navigation.mapWorkspace")}</span>
            </NavigationButton>
          </Dropdown>
          {dataButton}
          <NavigationButton
            type="text"
            data-nav-key="compute"
            className={tabClass(activeTab === "compute")}
            onClick={() => navigateFromHeader("/compute")}
            title={t("navigation.compute")}
          >
            <ColumnIcon
              name="compute"
              aria-hidden="true"
              style={{ fontSize: 16 }}
            />
            <span className="tab-text">{t("navigation.compute")}</span>
          </NavigationButton>
          <Dropdown
            menu={{ items: analysisCategoryMenuItems }}
            trigger={["hover"]}
            placement="bottom"
            classNames={{ root: "workspace-management-dropdown" }}
          >
            <NavigationButton
              ref={nonGeoTabRef}
              type="text"
              className={tabClass(activeTab === "nongeo")}
              onClick={() => navigateFromHeader("/nongeo")}
              title={t("navigation.analytics")}
            >
              <ColumnIcon
                name="analysis"
                aria-hidden="true"
                style={{ fontSize: 16 }}
              />
              <span className="tab-text">{t("navigation.analytics")}</span>
            </NavigationButton>
          </Dropdown>
          <NavigationButton
            type="text"
            data-nav-key="results"
            className={tabClass(activeTab === "results")}
            onClick={() => navigateFromHeader("/results")}
            title={t("navigation.results")}
          >
            <ColumnIcon
              name="results"
              aria-hidden="true"
              style={{ fontSize: 16 }}
            />
            <span className="tab-text">{t("navigation.results")}</span>
          </NavigationButton>
          <AgentNavigationButton
            className={tabClass(activeTab === "warning")}
            onNavigate={navigateFromHeader}
            title={t("navigation.warning")}
          />
          <NavigationButton
            type="text"
            data-nav-key="knowledgeBase"
            className={tabClass(activeTab === "knowledgeBase")}
            onClick={() => navigateFromHeader("/knowledge-base")}
            title={t("navigation.knowledgeBase")}
          >
            <ApartmentOutlined style={{ fontSize: 16 }} />
            <span className="tab-text">{t("navigation.knowledgeBase")}</span>
          </NavigationButton>
          {showAdminTab && (
            <Dropdown
              menu={{ items: adminMenuItems }}
              trigger={["hover"]}
              placement="bottom"
              classNames={{ root: "workspace-management-dropdown" }}
            >
              <NavigationButton
                ref={adminTabRef}
                type="text"
                className={tabClass(activeTab === "admin")}
                onClick={() => navigateFromHeader("/admin")}
                title={t("navigation.administration")}
              >
                <ColumnIcon
                  name="admin"
                  aria-hidden="true"
                  style={{ fontSize: 16 }}
                />
                <span className="tab-text">
                  {t("navigation.administration")}
                </span>
              </NavigationButton>
            </Dropdown>
          )}
          <NavigationButton
            type="text"
            className={tabClass(activeTab === "knowledge")}
            onClick={() => navigateFromHeader("/knowledge")}
            title={t("navigation.knowledge")}
          >
            <ColumnIcon
              name="knowledge"
              aria-hidden="true"
              style={{ fontSize: 16 }}
            />
            <span className="tab-text">{t("navigation.knowledge")}</span>
          </NavigationButton>
          <NavigationButton
            type="text"
            data-nav-key="news"
            className={tabClass(activeTab === "news")}
            onClick={() => navigateFromHeader("/news")}
            title={t("navigation.news")}
          >
            <ColumnIcon name="news" />
            <span className="tab-text">{t("navigation.news")}</span>
          </NavigationButton>
          <Dropdown
            menu={{ items: aboutMenuItems }}
            trigger={["hover"]}
            placement="bottom"
            classNames={{ root: "workspace-management-dropdown" }}
          >
            <NavigationButton
              ref={aboutTabRef}
              type="text"
              className={tabClass(activeTab === "about")}
              onClick={() => navigateFromHeader("/about/system")}
              title={t("navigation.about")}
            >
              <ColumnIcon
                name="about"
                aria-hidden="true"
                style={{ fontSize: 16 }}
              />
              <span className="tab-text">{t("navigation.about")}</span>
            </NavigationButton>
          </Dropdown>
        </nav>
      </div>

      <div className="header-account-actions">
        <ProjectSelector />
        {showDataImportShortcut && (
          <Button
            type="text"
            aria-label={t("navigation.dataImport")}
            className="data-import-shortcut"
            icon={<ColumnIcon name="upload" />}
            onClick={() => navigateFromHeader("/resources/data/import")}
            title={t("navigation.dataImport")}
          >
            <span className="data-import-shortcut-text">
              {t("navigation.dataImport")}
            </span>
          </Button>
        )}
        <LanguageSwitcher compact className="header-language-switcher" />
        <Popover
          trigger="click"
          placement="bottomRight"
          content={userContent}
          open={userPopoverOpen}
          onOpenChange={setUserPopoverOpen}
          classNames={{ root: "workspace-info-popover" }}
        >
          <Button
            ref={userButtonRef}
            aria-label={t("navigation.userInformation")}
            className="user-button"
          >
            <span className="user-button-content">
              <Avatar
                size={24}
                src={user?.avatarUrl || undefined}
                icon={<UserOutlined />}
              />
              <span className="user-button-name">{userDisplayLabel}</span>
            </span>
          </Button>
        </Popover>
      </div>
      <Tour
        open={tourOpen}
        steps={tourSteps}
        onClose={finishTour}
        onFinish={finishTour}
        mask={{ color: "rgba(6, 18, 24, 0.52)" }}
      />
    </header>
  );
}

const fallbackCatalogTree: DataSchemaCatalogNode[] = [
  {
    code: "geo",
    name: "地理数据",
    categoryCode: "geo",
    selectable: false,
    description: "兼容地图工作台入口",
    path: ["地理数据"],
    domainType: null,
    spatialClass: "spatial",
    children: [
      domainNode("geo-germplasm", "种质数据", "germplasm"),
      domainNode("geo-individual", "个体数据", "individual"),
      domainNode("geo-community", "群落数据", "community"),
      domainNode("geo-population", "种群数据", "population"),
      domainNode("geo-field-survey", "野外调查数据", "field_survey"),
      domainNode("geo-remote-sensing", "遥感影像数据", "remote_sensing"),
    ],
  },
  {
    code: "nongeo",
    name: "非地理数据",
    categoryCode: "nongeo",
    selectable: false,
    description: "兼容数据分析入口",
    path: ["非地理数据"],
    domainType: null,
    spatialClass: "non_spatial",
    children: [
      domainNode("nongeo-molecular", "分子数据", "molecular"),
      domainNode("nongeo-genome", "基因组数据", "genome"),
    ],
  },
];

function domainNode(
  code: string,
  name: string,
  domainType: DataDomainType,
): DataSchemaCatalogNode {
  return {
    code,
    name,
    categoryCode: code,
    selectable: true,
    description: "兼容业务标签",
    path: [name],
    domainType,
    spatialClass: null,
    children: [],
  };
}

function workspaceCategoryMenuItems(
  nodes: DataSchemaCatalogNode[],
  targetPath: "/map" | "/nongeo",
  onNavigate: (path: string) => void,
  t: TFunction,
): MenuProps["items"] {
  const keyPrefix = targetPath.slice(1);
  return [
    {
      key: `${keyPrefix}-all-categories`,
      label: t("navigation.allBusinessCategories"),
      onClick: () => onNavigate(targetPath),
    },
    { type: "divider" },
    ...nodes.map((root) => ({
      key: `${keyPrefix}-${root.categoryCode}`,
      label: root.name,
      children: root.children.length
        ? root.children.map((child) => ({
            key: `${keyPrefix}-${child.categoryCode}`,
            label: child.name,
            onClick: () =>
              onNavigate(
                `${targetPath}?categoryCode=${encodeURIComponent(child.categoryCode)}`,
              ),
          }))
        : [
            {
              key: `${keyPrefix}-${root.categoryCode}-empty`,
              label: t("navigation.noSubcategories"),
              disabled: true,
            },
          ],
    })),
  ];
}

function tabClass(active: boolean) {
  return ["workspace-switch-card", active ? "workspace-switch-card-active" : ""]
    .filter(Boolean)
    .join(" ");
}

function localizedBuiltInDisplayName(value: string, t: TFunction) {
  switch (value) {
    case "超级管理员":
      return t("common.superAdministrator");
    case "平台管理员":
      return t("common.platformAdministrator");
    case "科研用户":
      return t("common.researchUser");
    case "普通用户":
      return t("common.standardUser");
    default:
      return value;
  }
}

function clampNumber(min: number, value: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function SearchResultSection({
  title,
  icon,
  emptyText,
  children,
}: {
  title: string;
  icon: ReactNode;
  emptyText: string;
  children: ReactNode[];
}) {
  const items = children.filter(Boolean);
  return (
    <section className="workspace-search-section">
      <div className="workspace-search-section-title">
        <span>
          {icon}
          <Typography.Text strong>{title}</Typography.Text>
        </span>
        <Tag>{items.length}</Tag>
      </div>
      {items.length > 0 ? (
        <div className="workspace-search-list">{items}</div>
      ) : (
        <Empty
          className="workspace-search-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={emptyText}
        />
      )}
    </section>
  );
}

function domainTypeLabels(
  schema: DataSchemaSummary | null | undefined,
  t: TFunction,
) {
  const labels = new Map<DataDomainType, string>();
  const domainTypes: DataDomainType[] = [
    "germplasm",
    "genome",
    "individual",
    "community",
    "population",
    "field_survey",
    "remote_sensing",
    "molecular",
    "vector",
    "other",
  ];
  domainTypes.forEach((domainType) =>
    labels.set(domainType, t(`dataDomain.${domainType}`)),
  );
  collectDomainLabels(fallbackCatalogTree, labels);
  collectDomainLabels(schema?.catalogTree ?? [], labels);
  return labels;
}

function collectDomainLabels(
  nodes: DataSchemaCatalogNode[],
  labels: Map<DataDomainType, string>,
) {
  nodes.forEach((node) => {
    if (node.domainType && !labels.has(node.domainType)) {
      labels.set(node.domainType, node.name);
    }
    collectDomainLabels(node.children, labels);
  });
}

function resourceDomainCategoryName(
  resource: ResourceListItem,
  domainTypeLabelByValue: Map<DataDomainType, string>,
) {
  if (resource.domainType) {
    return (
      domainTypeLabelByValue.get(resource.domainType) ??
      resourceCategoryName(resource)
    );
  }
  return resourceCategoryName(resource);
}

function resourceMatches(
  resource: ResourceListItem,
  query: string,
  domainTypeLabelByValue: Map<DataDomainType, string>,
) {
  return [
    resource.name,
    resource.code,
    resource.source,
    resourceProvider(resource),
    "description" in resource ? resource.description : "",
    resourceDomainCategoryName(resource, domainTypeLabelByValue),
    resourceFormatLabel(resource),
  ].some((value) => textMatches(value, query));
}

function sceneMatches(scene: WorkspaceSceneSummary, query: string) {
  return [
    scene.name,
    scene.description,
    "工程",
    scene.owner.displayName,
    scene.owner.username,
  ].some((value) => textMatches(value, query));
}

function compositionMatches(composition: MapComposition, query: string) {
  return [
    composition.name,
    composition.description,
    composition.projectName,
    "专题",
    composition.owner.displayName,
    composition.owner.username,
  ].some((value) => textMatches(value, query));
}

function textMatches(value: unknown, query: string) {
  return String(value ?? "")
    .toLocaleLowerCase("zh-CN")
    .includes(query);
}

function formatSceneUpdatedAt(scene: Pick<WorkspaceSceneSummary, "updatedAt">) {
  return new Date(scene.updatedAt).toLocaleString("zh-CN", { hour12: false });
}
