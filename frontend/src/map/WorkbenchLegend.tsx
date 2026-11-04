import {
  DownOutlined,
  UnorderedListOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { useMemo, useState } from "react";
import type { LoadedLayer } from "../types";
import { workbenchLegends } from "./liveLegendData";

const legendStorageKey = "workbench-legend";

// Open on wide screens; on narrower ones the legend starts as a button so it does
// not cover the map. A choice the user made is remembered.
function initialLegendExpanded() {
  try {
    const saved = localStorage.getItem(legendStorageKey);
    if (saved) return saved === "open";
  } catch {
    // Fall back to the width rule.
  }
  return window.innerWidth >= 1280;
}

export default function WorkbenchLegend({
  layers,
  english,
  mobileHidden,
}: {
  layers: LoadedLayer[];
  english: boolean;
  mobileHidden: boolean;
}) {
  const legends = useMemo(
    () => workbenchLegends(layers, english),
    [layers, english],
  );
  const [expanded, setExpandedState] = useState(initialLegendExpanded);
  const setExpanded = (value: boolean) => {
    setExpandedState(value);
    try {
      localStorage.setItem(legendStorageKey, value ? "open" : "closed");
    } catch {
      // The choice simply is not remembered.
    }
  };
  if (legends.length === 0) return null;
  return (
    <section
      className={`workbench-live-legend ${mobileHidden ? "legend-mobile-hidden" : ""} ${expanded ? "is-expanded" : "is-collapsed"}`}
      aria-label={english ? "Live map legend" : "实时地图图例"}
    >
      <button
        className="workbench-legend-heading"
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls="workbench-live-legend-content"
      >
        <UnorderedListOutlined />
        <strong>{english ? "Legend" : "图例"}</strong>
        <span>{legends.length}</span>
        {expanded ? <UpOutlined /> : <DownOutlined />}
      </button>
      {expanded && (
        <div
          className="workbench-legend-content"
          id="workbench-live-legend-content"
        >
          {legends.map((legend) => (
            <details key={legend.id} open className="workbench-legend-layer">
              <summary title={legend.title}>{legend.title}</summary>
              {legend.updating && (
                <p className="workbench-legend-status">
                  {english
                    ? "Rendering; showing current colors"
                    : "渲染中，图例保留当前配色"}
                </p>
              )}
              {legend.note && (
                <p className="workbench-legend-note">{legend.note}</p>
              )}
              {legend.gradient && (
                <div className="workbench-legend-gradient">
                  <div
                    style={{
                      background: `linear-gradient(90deg, ${legend.gradient.colors.join(", ")})`,
                      opacity: legend.opacity,
                    }}
                  />
                  <span>{legend.gradient.low}</span>
                  <span>{legend.gradient.high}</span>
                </div>
              )}
              <ul>
                {legend.entries.map((entry) => (
                  <li key={entry.id}>
                    <span
                      className={`workbench-legend-swatch is-${entry.shape}`}
                      style={{
                        backgroundColor: entry.color,
                        opacity: legend.opacity,
                      }}
                      aria-hidden="true"
                    />
                    <span>{entry.label}</span>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
