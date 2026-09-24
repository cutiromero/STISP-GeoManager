import { Button, Select, Slider, Space, Switch, Typography } from "antd";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { LayerContext } from "../hooks/LayerContext";
import type { RasterSymbolization } from "../symbolization";
import type { LoadedRasterLayer } from "../types";

export default function RasterRenderingControls({
  layer,
  value,
  bands,
}: {
  layer: LoadedRasterLayer | null;
  value: RasterSymbolization;
  bands: { band: number; label: string }[];
}) {
  const context = useContext(LayerContext);
  const { i18n } = useTranslation();
  const english = i18n.resolvedLanguage?.startsWith("en") ?? false;
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [layer?.id, value]);
  const group = context?.groups.find((item) =>
    item.children.some((child) => child.id === layer?.id),
  );
  const editable = Boolean(
    layer && group && context?.canUseCustomSymbolization,
  );
  const busy =
    layer?.renderStatus === "queued" || layer?.renderStatus === "running";
  const validBands = draft.bands.every((band) =>
    bands.some((item) => item.band === band),
  );
  const label = (zh: string, en: string) => (english ? en : zh);
  function update(next: Partial<RasterSymbolization>) {
    setDraft((current) => ({ ...current, ...next }));
  }
  function apply() {
    if (!editable || !layer || !group || !context || !validBands || busy)
      return;
    context.setLayerSymbolization(group.id, layer.id, draft);
    context.startRasterRender(
      group.id,
      layer.id,
      draft,
      { ...layer, symbolization: draft },
      "custom",
    );
  }
  return (
    <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
      <label>
        {label("渲染方案", "Rendering mode")}
        <Select
          aria-label={label("渲染方案", "Rendering mode")}
          style={{ width: "100%" }}
          disabled={!editable}
          value={draft.mode}
          options={[
            { value: "gray", label: label("单波段灰度", "Grayscale") },
            {
              value: "pseudocolor",
              label: label("单波段伪彩色", "Pseudocolor"),
            },
            {
              value: "rgb",
              label: label("RGB多波段合成", "RGB composite"),
              disabled: bands.length < 3,
            },
            ...(draft.mode === "unique"
              ? [
                  {
                    value: "unique",
                    label: label("唯一值分类", "Unique values"),
                  },
                ]
              : []),
          ]}
          onChange={(mode: RasterSymbolization["mode"]) =>
            update({
              mode,
              bands:
                mode === "rgb"
                  ? bands.slice(0, 3).map((band) => band.band)
                  : [draft.bands[0] ?? bands[0]?.band ?? 1],
            })
          }
        />
      </label>
      {draft.mode === "pseudocolor" && (
        <label>
          {label("配色", "Palette")}
          <Select
            aria-label={label("配色", "Palette")}
            style={{ width: "100%" }}
            disabled={!editable}
            value={draft.palette}
            options={[
              { value: "poplar", label: label("生态绿", "Ecological green") },
              { value: "viridis", label: label("紫黄渐变", "Viridis") },
              { value: "terrain", label: label("地形", "Terrain") },
              { value: "thermal", label: label("热力", "Thermal") },
            ]}
            onChange={(palette: RasterSymbolization["palette"]) =>
              update({ palette })
            }
          />
          <div
            className={`raster-palette-strip raster-palette-${draft.palette}`}
            style={{ marginTop: 8 }}
            aria-label={label("所选色带预览", "Selected palette preview")}
            role="img"
          />
        </label>
      )}
      {(draft.mode === "rgb" ? [0, 1, 2] : [0]).map((index) => (
        <label key={index}>
          {draft.mode === "rgb"
            ? ["R", "G", "B"][index]
            : label("输出波段", "Output band")}
          <Select
            aria-label={
              draft.mode === "rgb"
                ? `${["R", "G", "B"][index]} ${label("波段", "band")}`
                : label("输出波段", "Output band")
            }
            style={{ width: "100%" }}
            disabled={!editable || draft.mode === "unique"}
            value={draft.bands[index]}
            options={bands.map((band) => ({
              value: band.band,
              label: `B${band.band} · ${band.label}`,
            }))}
            onChange={(band: number) => {
              const next = [...draft.bands];
              next[index] = band;
              update({ bands: next });
            }}
          />
        </label>
      ))}
      <label>
        {label("图层不透明度", "Layer opacity")} {draft.opacity}%
        <Slider
          ariaLabelForHandle={label("图层不透明度", "Layer opacity")}
          min={0}
          max={100}
          value={draft.opacity}
          disabled={!editable}
          onChange={(opacity) => update({ opacity })}
        />
      </label>
      <Space wrap>
        <span>
          {label("Min–Max拉伸", "Min–Max stretch")}{" "}
          <Switch
            aria-label={label("Min–Max拉伸", "Min–Max stretch")}
            disabled={!editable || draft.mode === "unique"}
            checked={draft.stretch.enabled}
            onChange={(enabled) =>
              update({ stretch: { ...draft.stretch, enabled } })
            }
          />
        </span>
        <span>
          {label("NoData透明", "Transparent NoData")}{" "}
          <Switch
            aria-label={label("NoData透明", "Transparent NoData")}
            disabled={!editable}
            checked={draft.nodata.enabled}
            onChange={(enabled) =>
              update({ nodata: { ...draft.nodata, enabled } })
            }
          />
        </span>
      </Space>
      <Button
        type="primary"
        onClick={apply}
        disabled={!editable || !validBands || busy}
      >
        {busy
          ? label("正在渲染", "Rendering")
          : label("应用渲染方案", "Apply rendering")}
      </Button>
      {!editable && (
        <Typography.Text type="secondary">
          {!layer
            ? label(
                "将资源加载到地图后，可在此调整配色与显示参数。",
                "Load this resource onto the map to adjust its rendering.",
              )
            : label(
                "当前账号没有自定义渲染权限。",
                "Your account cannot customize rendering.",
              )}
        </Typography.Text>
      )}
    </div>
  );
}
