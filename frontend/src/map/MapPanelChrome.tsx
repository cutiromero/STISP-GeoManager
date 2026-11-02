import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import type { KeyboardEvent, PointerEvent } from "react";
import type { MapPanelSide } from "./useMapPanelLayout";

interface Props {
  side: MapPanelSide;
  title: string;
  collapsed: boolean;
  width: number;
  english: boolean;
  onToggle: () => void;
  onResizeStart: (event: PointerEvent) => void;
  onResize: (amount: number) => void;
}

export default function MapPanelChrome(props: Props) {
  const {
    side,
    title,
    collapsed,
    width,
    english,
    onToggle,
    onResizeStart,
    onResize,
  } = props;
  const label = collapsed
    ? english
      ? `Expand ${title}`
      : `展开${title}`
    : english
      ? `Minimize ${title}`
      : `最小化${title}`;
  const pointsLeft = side === "left" ? !collapsed : collapsed;
  const keyboardResize = (event: KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    onResize(
      (event.key === "ArrowRight" ? 20 : -20) * (side === "left" ? 1 : -1),
    );
  };
  return (
    <>
      <div className="map-panel-chrome">
        {!collapsed && <span>{title}</span>}
        <button
          type="button"
          className="map-panel-toggle"
          title={label}
          aria-label={label}
          aria-expanded={!collapsed}
          onClick={onToggle}
        >
          {pointsLeft ? <LeftOutlined /> : <RightOutlined />}
        </button>
      </div>
      {collapsed ? (
        <button
          className="map-panel-restore"
          type="button"
          onClick={onToggle}
          aria-label={label}
        >
          {title}
        </button>
      ) : (
        <div
          className={`map-panel-resizer map-panel-resizer-${side}`}
          role="separator"
          aria-orientation="vertical"
          aria-label={english ? `Resize ${title}` : `调整${title}宽度`}
          aria-valuemin={240}
          aria-valuemax={560}
          aria-valuenow={Math.round(width)}
          tabIndex={0}
          onPointerDown={onResizeStart}
          onKeyDown={keyboardResize}
        />
      )}
    </>
  );
}
