import type { ProDescriptionsItemProps } from "@ant-design/pro-components";
import { ProCard, ProDescriptions } from "@ant-design/pro-components";
import { App, Skeleton } from "antd";
import type { Key } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { applyPlatformDocumentTitle } from "../config/platformBrand";
import type { AdminSettings, AdminSettingsUpdate } from "../types";

interface BasicSettingValues {
  systemName: string;
  allowRegistration: boolean;
  defaultCenterLon: number;
  defaultCenterLat: number;
  defaultZoom: number;
  defaultBasemap: AdminSettings["map"]["defaultBasemap"];
  mapboxAccessToken: string;
  tiandituAccessToken: string;
  uploadMaxMb: number;
  queryResultLimit: number;
  maxRasterSidePixels: number;
  symbolizerTimeoutSeconds: number;
}

type BasicSettingDescriptionItem = BasicSettingValues;

export const ADMIN_SETTING_RANGES = {
  uploadMaxMb: { min: 1, max: 1024 },
  queryResultLimit: { min: 100, max: 10_000 },
  maxRasterSidePixels: { min: 1, max: 12_000 },
  symbolizerTimeoutSeconds: { min: 10, max: 600 },
} as const;

function integerRangeRule(
  min: number,
  max: number,
  label: string,
  english = false,
) {
  return {
    type: "number" as const,
    min,
    max,
    message: english
      ? `${label} must be an integer from ${min} to ${max}`
      : `${label}必须是 ${min} 到 ${max} 之间的整数`,
  };
}

function createSettingDescriptionColumns(
  english = false,
): ProDescriptionsItemProps<BasicSettingDescriptionItem>[] {
  const basemapValueEnum = {
    satellite: { text: english ? "Mapbox Satellite" : "Mapbox 卫星实景图" },
    "mapbox-streets": { text: english ? "Mapbox Streets" : "Mapbox 街道图" },
    "tianditu-vector": {
      text: english ? "Tianditu Vector with labels" : "天地图矢量注记图",
    },
    "tianditu-imagery": {
      text: english ? "Tianditu Imagery" : "天地图卫星影像图",
    },
  };
  return [
    {
      title: english ? "System name" : "系统名称",
      dataIndex: "systemName",
      span: 3,
      formItemProps: {
        rules: [
          {
            required: true,
            message: english ? "Enter the system name" : "请输入系统名称",
          },
        ],
      },
    },
    {
      title: english ? "Open registration" : "开放注册",
      dataIndex: "allowRegistration",
      valueType: "switch",
      span: 3,
    },
    {
      title: english ? "Default longitude" : "默认经度",
      dataIndex: "defaultCenterLon",
      valueType: "digit",
      span: 3,
      fieldProps: {
        min: -180,
        max: 180,
      },
    },
    {
      title: english ? "Default latitude" : "默认纬度",
      dataIndex: "defaultCenterLat",
      valueType: "digit",
      span: 3,
      fieldProps: {
        min: -90,
        max: 90,
      },
    },
    {
      title: english ? "Default zoom" : "默认缩放",
      dataIndex: "defaultZoom",
      valueType: "digit",
      span: 3,
      fieldProps: {
        min: 1,
        max: 22,
      },
    },
    {
      title: english ? "Default basemap" : "默认底图",
      dataIndex: "defaultBasemap",
      valueType: "select",
      valueEnum: basemapValueEnum,
      span: 3,
    },
    {
      title: "Mapbox Token",
      dataIndex: "mapboxAccessToken",
      span: 6,
      copyable: true,
      render: (dom) => <span className="admin-token-text">{dom}</span>,
    },
    {
      title: english ? "Tianditu browser key" : "天地图浏览器 Key",
      dataIndex: "tiandituAccessToken",
      span: 6,
      copyable: true,
      tooltip: english
        ? "Use a browser key issued by Tianditu. Allow localhost/127.0.0.1 and the production domain in the console, or requests will return a 403 domain mismatch."
        : "仅填写天地图控制台签发的浏览器端 Key；控制台需同时放行本地 localhost/127.0.0.1 和生产域名，否则会返回 403 域名不匹配",
      render: (dom) => <span className="admin-token-text">{dom}</span>,
    },
    {
      title: english ? "Upload limit (MB)" : "上传上限 MB",
      dataIndex: "uploadMaxMb",
      valueType: "digit",
      span: 2,
      fieldProps: {
        ...ADMIN_SETTING_RANGES.uploadMaxMb,
        precision: 0,
      },
      formItemProps: {
        rules: [
          integerRangeRule(
            ADMIN_SETTING_RANGES.uploadMaxMb.min,
            ADMIN_SETTING_RANGES.uploadMaxMb.max,
            english ? "Upload limit" : "上传上限",
            english,
          ),
        ],
      },
      tooltip: english
        ? "Raster and standalone result files can be set up to 1024 MB. Vector and table imports have lower memory-safety limits; thematic PNG output remains fixed at 128 MB. The application-server body limit is 1152 MiB."
        : "栅格与独立成果文件最高可设置为 1024 MB；矢量和表格受更低的内存安全限制，专题出图 PNG 固定为 128 MB，不随本项变化。应用服务器请求体上限为 1152 MiB。",
    },
    {
      title: english ? "Query result limit" : "查询结果上限",
      dataIndex: "queryResultLimit",
      valueType: "digit",
      span: 2,
      fieldProps: {
        ...ADMIN_SETTING_RANGES.queryResultLimit,
        precision: 0,
      },
      formItemProps: {
        rules: [
          integerRangeRule(
            100,
            10_000,
            english ? "Query result limit" : "查询结果上限",
            english,
          ),
        ],
      },
    },
    {
      title: english ? "Raster side-pixel limit" : "栅格单边像素上限",
      dataIndex: "maxRasterSidePixels",
      valueType: "digit",
      span: 2,
      fieldProps: {
        ...ADMIN_SETTING_RANGES.maxRasterSidePixels,
        precision: 0,
      },
      formItemProps: {
        rules: [
          integerRangeRule(
            1,
            12_000,
            english ? "Raster side-pixel limit" : "栅格单边像素上限",
            english,
          ),
        ],
      },
    },
    {
      title: english ? "Raster timeout (seconds)" : "栅格超时秒数",
      dataIndex: "symbolizerTimeoutSeconds",
      valueType: "digit",
      span: 2,
      fieldProps: {
        ...ADMIN_SETTING_RANGES.symbolizerTimeoutSeconds,
        precision: 0,
      },
      formItemProps: {
        rules: [
          integerRangeRule(
            10,
            600,
            english ? "Raster timeout" : "栅格超时秒数",
            english,
          ),
        ],
      },
    },
  ];
}

export default function AdminSystemSettingsPage() {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const { bootstrap, setBootstrap } = useAppContext();
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function loadSettings() {
      try {
        const data = await api.adminSettings();
        if (!mounted) return;
        setSettings(data);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load system settings"
              : "系统设置加载失败",
        );
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    loadSettings();
    return () => {
      mounted = false;
    };
  }, [english, message]);

  async function handleSave(values: BasicSettingValues): Promise<boolean> {
    try {
      const payload: AdminSettingsUpdate = {
        systemName: values.systemName,
        allowRegistration: values.allowRegistration,
        map: {
          defaultCenter: [values.defaultCenterLon, values.defaultCenterLat],
          defaultZoom: values.defaultZoom,
          defaultBasemap: values.defaultBasemap,
          mapboxAccessToken: values.mapboxAccessToken,
          tiandituAccessToken: values.tiandituAccessToken,
        },
        limits: {
          uploadMaxMb: values.uploadMaxMb,
          queryResultLimit: values.queryResultLimit,
          maxRasterSidePixels: values.maxRasterSidePixels,
        },
        raster: {
          symbolizerTimeoutSeconds: values.symbolizerTimeoutSeconds,
        },
      };
      const updated = await api.updateAdminSettings(payload);
      setSettings(updated);
      setBootstrap({
        ...bootstrap,
        systemName: updated.systemName,
        allowRegistration: updated.allowRegistration,
        map: updated.map,
        limits: updated.limits,
      });
      applyPlatformDocumentTitle(updated.systemName);
      message.success(
        english
          ? "System settings written to runtime configuration"
          : "系统设置已写入运行配置",
      );
      return true;
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to save system settings"
            : "系统设置保存失败",
      );
      return false;
    }
  }

  async function handleDescriptionSave(
    _key: Key | Key[],
    values: BasicSettingDescriptionItem,
  ) {
    if (!settings) return false;
    return handleSave(mergeSettingValues(settings, values));
  }

  if (loading) {
    return (
      <ProCard className="admin-section-card">
        <Skeleton active paragraph={{ rows: 8 }} />
      </ProCard>
    );
  }

  const settingDescriptionData = settings
    ? valuesFromSettings(settings)
    : undefined;

  return (
    <div className="admin-page-stack">
      <ProCard
        title={english ? "Basic configuration" : "基础配置"}
        className="admin-section-card"
      >
        <ProDescriptions<BasicSettingDescriptionItem>
          column={6}
          columns={createSettingDescriptionColumns(english)}
          dataSource={settingDescriptionData}
          editable={
            settings?.editable
              ? {
                  onSave: handleDescriptionSave,
                }
              : undefined
          }
          emptyText={english ? "Not configured" : "未配置"}
        />
      </ProCard>
    </div>
  );
}

export function mergeSettingValues(
  settings: AdminSettings,
  changedValues: Partial<BasicSettingDescriptionItem>,
): BasicSettingValues {
  const definedValues = Object.fromEntries(
    Object.entries(changedValues).filter(([, value]) => value !== undefined),
  ) as Partial<BasicSettingValues>;
  return {
    ...valuesFromSettings(settings),
    ...definedValues,
  };
}

function valuesFromSettings(settings: AdminSettings): BasicSettingValues {
  const [defaultCenterLon = 80, defaultCenterLat = 41.5] =
    settings.map.defaultCenter;
  return {
    systemName: settings.systemName,
    allowRegistration: settings.allowRegistration,
    defaultCenterLon,
    defaultCenterLat,
    defaultZoom: settings.map.defaultZoom,
    defaultBasemap: settings.map.defaultBasemap,
    mapboxAccessToken: settings.map.mapboxAccessToken,
    tiandituAccessToken: settings.map.tiandituAccessToken ?? "",
    uploadMaxMb: settings.limits.uploadMaxMb,
    queryResultLimit: settings.limits.queryResultLimit,
    maxRasterSidePixels: settings.limits.maxRasterSidePixels,
    symbolizerTimeoutSeconds: settings.raster.symbolizerTimeoutSeconds,
  };
}
