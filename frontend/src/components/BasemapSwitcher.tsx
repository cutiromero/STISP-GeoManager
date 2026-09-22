import {
  CheckOutlined,
  GlobalOutlined,
  LoadingOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Button, Popover } from "antd";
import { useTranslation } from "react-i18next";
import type {
  BasemapDefinition,
  BasemapId,
  BasemapProvider,
} from "../map/basemapCatalog";

export interface BasemapSwitcherProps {
  basemaps: readonly BasemapDefinition[];
  activeId: BasemapId;
  switching?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onSelect: (id: BasemapId) => void;
  className?: string;
}

export default function BasemapSwitcher({
  basemaps,
  activeId,
  switching = false,
  disabled = false,
  disabledReason,
  onSelect,
  className,
}: BasemapSwitcherProps) {
  const { t } = useTranslation();
  const selectableBasemaps = basemaps.filter((basemap) => basemap.selectable);
  const activeBasemap = basemaps.find((basemap) => basemap.id === activeId);
  const triggerLabel = switching
    ? t("map.switchingBasemap")
    : t("map.switchCurrentBasemap", {
        name: activeBasemap?.label ?? t("map.unknownBasemap"),
      });
  const content = (
    <div
      className="basemap-switcher-panel"
      role="dialog"
      aria-label={t("map.selectBasemap")}
    >
      <div className="basemap-switcher-heading">
        <div>
          <strong>{t("map.selectBasemap")}</strong>
          <span>{t("map.preserveViewOnSwitch")}</span>
        </div>
        {switching ? (
          <span className="basemap-switcher-progress" role="status">
            <LoadingOutlined spin />
            {t("map.switching")}
          </span>
        ) : null}
      </div>
      <div className="basemap-switcher-options">
        {selectableBasemaps.map((basemap) => {
          const selected = basemap.id === activeId;
          const unavailable = !basemap.credentials.available;
          const optionDisabled = disabled || switching || unavailable;
          const statusText = unavailable
            ? (basemap.credentials.reason ?? t("map.unavailable"))
            : basemap.credentials.degraded
              ? (basemap.credentials.warning ?? t("map.limited"))
              : selected
                ? t("map.current")
                : t("map.available");
          return (
            <button
              key={basemap.id}
              type="button"
              className="basemap-switcher-option"
              aria-label={t("map.optionStatus", {
                name: basemap.label,
                status: statusText,
              })}
              aria-pressed={selected}
              disabled={optionDisabled}
              title={unavailable ? statusText : undefined}
              onClick={() => {
                if (!optionDisabled && basemap.id !== activeId) {
                  onSelect(basemap.id);
                }
              }}
            >
              <span
                className={`basemap-switcher-preview basemap-switcher-preview-${basemap.visual}`}
                aria-hidden="true"
              />
              <span className="basemap-switcher-option-copy">
                <span className="basemap-switcher-option-title">
                  <span>{basemap.label}</span>
                  {switching && selected ? (
                    <LoadingOutlined spin aria-hidden="true" />
                  ) : selected ? (
                    <CheckOutlined aria-hidden="true" />
                  ) : null}
                </span>
                <span className="basemap-switcher-option-description">
                  {basemap.description}
                </span>
                <span
                  className={`basemap-switcher-option-status ${
                    unavailable
                      ? "is-error"
                      : basemap.credentials.degraded
                        ? "is-warning"
                        : "is-ready"
                  }`}
                >
                  {unavailable || basemap.credentials.degraded ? (
                    <WarningOutlined aria-hidden="true" />
                  ) : null}
                  {statusText}
                </span>
                <span className="basemap-switcher-provider">
                  {t("map.serviceProvider", {
                    provider: providerLabel(basemap.provider, t),
                  })}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );

  return (
    <span
      className={["basemap-switcher", className].filter(Boolean).join(" ")}
      title={disabled ? disabledReason : undefined}
    >
      <Popover content={content} placement="topLeft" trigger="click">
        <Button
          className="basemap-switcher-trigger"
          icon={switching ? <LoadingOutlined spin /> : <GlobalOutlined />}
          disabled={disabled || switching}
          aria-label={
            disabled && disabledReason
              ? t("map.triggerStatus", {
                  label: triggerLabel,
                  reason: disabledReason,
                })
              : triggerLabel
          }
          aria-busy={switching}
        >
          {activeBasemap?.label ?? t("map.selectBasemap")}
        </Button>
      </Popover>
    </span>
  );
}

function providerLabel(provider: BasemapProvider, t: (key: string) => string) {
  if (provider === "mapbox") return "Mapbox";
  if (provider === "tianditu") return t("map.tiandituProvider");
  return "OpenStreetMap";
}
