import { Button, Collapse, InputNumber, Select, Space, Switch } from "antd";
import { useTranslation } from "react-i18next";
import {
  panMapBounds,
  suggestedGeographicGridInterval,
  suggestedProjectedGridInterval,
  zoomMapBounds,
  type MapBounds,
  type MapCompositionLayout,
} from "../../map-composition/layout";
import {
  applyPaperPreset,
  restoreStandardCompositionLayout,
} from "../../map-composition/layoutPaper";
import {
  BoundsEditor,
  BoxEditor,
  Field,
  TextEditor,
  Toggle,
} from "./CompositionFieldEditors";

interface Props {
  layout: MapCompositionLayout;
  liveMapBounds: MapBounds;
  onChange: (
    update: (current: MapCompositionLayout) => MapCompositionLayout,
  ) => void;
}

export default function CompositionSettings({
  layout,
  liveMapBounds,
  onChange,
}: Props) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  function patchPage(values: Partial<MapCompositionLayout["page"]>) {
    onChange((current) => ({
      ...current,
      page: { ...current.page, ...values },
    }));
  }
  function patchElement<Key extends keyof MapCompositionLayout>(
    key: Key,
    values: Partial<MapCompositionLayout[Key]>,
  ) {
    onChange((currentLayout) => {
      const current = currentLayout[key] as Record<string, unknown>;
      return {
        ...currentLayout,
        [key]: { ...current, ...values },
      };
    });
  }
  function updateMapBounds(update: (bounds: MapBounds) => MapBounds) {
    onChange((current) => ({
      ...current,
      mapFrame: {
        ...current.mapFrame,
        bounds: update(current.mapFrame.bounds),
      },
    }));
  }

  return (
    <Collapse
      className="composition-settings"
      defaultActiveKey={["page", "map", "elements", "notes"]}
      items={[
        {
          key: "page",
          label: english ? "Page setup" : "页面设置",
          children: (
            <div className="composition-field-grid">
              <Field label={english ? "Paper" : "纸张"}>
                <Select
                  value={layout.page.preset}
                  options={[
                    { label: "A4", value: "A4" },
                    { label: "A3", value: "A3" },
                  ]}
                  onChange={(preset) =>
                    onChange((current) =>
                      applyPaperPreset(
                        current,
                        preset,
                        current.page.orientation,
                      ),
                    )
                  }
                />
              </Field>
              <Field label={english ? "Orientation" : "方向"}>
                <Select
                  value={layout.page.orientation}
                  options={[
                    {
                      label: english ? "Landscape" : "横向",
                      value: "landscape",
                    },
                    { label: english ? "Portrait" : "纵向", value: "portrait" },
                  ]}
                  onChange={(orientation) =>
                    onChange((current) =>
                      applyPaperPreset(
                        current,
                        current.page.preset,
                        orientation,
                      ),
                    )
                  }
                />
              </Field>
              <Field label="DPI">
                <InputNumber
                  min={72}
                  max={600}
                  step={10}
                  value={layout.page.dpi}
                  onChange={(value) =>
                    typeof value === "number" && patchPage({ dpi: value })
                  }
                />
              </Field>
              <Field label={english ? "Background" : "背景"}>
                <input
                  type="color"
                  value={layout.page.backgroundColor}
                  onChange={(event) =>
                    patchPage({ backgroundColor: event.target.value })
                  }
                />
              </Field>
              <div className="composition-standard-layout-action">
                <Button
                  block
                  onClick={() =>
                    onChange((current) =>
                      restoreStandardCompositionLayout(current),
                    )
                  }
                >
                  {english ? "Restore standard layout" : "恢复标准版式"}
                </Button>
                <small>
                  {english
                    ? "Keep the title, map extent, and notes; rearrange all elements on a white page."
                    : "保留标题、地图范围和说明内容，重新整理全部要素并恢复白色纸张。"}
                </small>
              </div>
            </div>
          ),
        },
        {
          key: "map",
          label: english ? "Map frame and extent" : "地图框与范围",
          children: (
            <>
              <BoundsEditor
                value={layout.mapFrame.bounds}
                onChange={(bounds) => patchElement("mapFrame", { bounds })}
              />
              <div className="composition-map-range-actions">
                <Button
                  size="small"
                  onClick={() =>
                    patchElement("mapFrame", { bounds: [...liveMapBounds] })
                  }
                >
                  {english
                    ? "Use current workspace extent"
                    : "使用当前工作台范围"}
                </Button>
                <Space.Compact block>
                  <Button
                    size="small"
                    aria-label={
                      english ? "Pan map extent left" : "地图范围向左平移"
                    }
                    onClick={() =>
                      updateMapBounds((bounds) =>
                        panMapBounds(bounds, -0.12, 0),
                      )
                    }
                  >
                    {english ? "Left" : "左移"}
                  </Button>
                  <Button
                    size="small"
                    aria-label={
                      english ? "Pan map extent right" : "地图范围向右平移"
                    }
                    onClick={() =>
                      updateMapBounds((bounds) => panMapBounds(bounds, 0.12, 0))
                    }
                  >
                    {english ? "Right" : "右移"}
                  </Button>
                  <Button
                    size="small"
                    aria-label={
                      english ? "Pan map extent up" : "地图范围向上平移"
                    }
                    onClick={() =>
                      updateMapBounds((bounds) => panMapBounds(bounds, 0, 0.12))
                    }
                  >
                    {english ? "Up" : "上移"}
                  </Button>
                  <Button
                    size="small"
                    aria-label={
                      english ? "Pan map extent down" : "地图范围向下平移"
                    }
                    onClick={() =>
                      updateMapBounds((bounds) =>
                        panMapBounds(bounds, 0, -0.12),
                      )
                    }
                  >
                    {english ? "Down" : "下移"}
                  </Button>
                  <Button
                    size="small"
                    aria-label={english ? "Zoom in map extent" : "放大地图范围"}
                    onClick={() =>
                      updateMapBounds((bounds) => zoomMapBounds(bounds, 0.8))
                    }
                  >
                    {english ? "Zoom in" : "放大"}
                  </Button>
                  <Button
                    size="small"
                    aria-label={
                      english ? "Zoom out map extent" : "缩小地图范围"
                    }
                    onClick={() =>
                      updateMapBounds((bounds) => zoomMapBounds(bounds, 1.25))
                    }
                  >
                    {english ? "Zoom out" : "缩小"}
                  </Button>
                </Space.Compact>
                <small>
                  {english
                    ? "Pan or zoom the map content; the preview refreshes automatically."
                    : "可平移或缩放地图内容；修改后预览会自动刷新。"}
                </small>
              </div>
              <BoxEditor
                value={layout.mapFrame}
                onChange={(values) => patchElement("mapFrame", values)}
              />
              <div className="composition-field-grid">
                <Field label={english ? "Grid" : "格网"}>
                  <Switch
                    checked={layout.grid.enabled}
                    onChange={(enabled) => patchElement("grid", { enabled })}
                  />
                </Field>
                <Field label={english ? "Type" : "类型"}>
                  <Select
                    disabled={!layout.grid.enabled}
                    value={layout.grid.type}
                    options={[
                      {
                        label: english ? "Geographic graticule" : "经纬网",
                        value: "geographic",
                      },
                      {
                        label: english
                          ? "Web Mercator projected grid"
                          : "Web Mercator 投影格网",
                        value: "projected",
                      },
                    ]}
                    onChange={(type) =>
                      onChange((current) => ({
                        ...current,
                        grid: {
                          ...current.grid,
                          type,
                          interval:
                            type === "projected"
                              ? suggestedProjectedGridInterval(
                                  current.mapFrame.bounds,
                                )
                              : suggestedGeographicGridInterval(
                                  current.mapFrame.bounds,
                                ),
                        },
                      }))
                    }
                  />
                </Field>
                <Field
                  label={
                    layout.grid.type === "projected"
                      ? english
                        ? "Interval (meters)"
                        : "间隔（米）"
                      : english
                        ? "Interval (degrees)"
                        : "间隔（度）"
                  }
                >
                  <InputNumber
                    disabled={!layout.grid.enabled}
                    min={layout.grid.type === "projected" ? 10 : 0.0001}
                    step={layout.grid.type === "projected" ? 100 : 0.001}
                    value={layout.grid.interval}
                    onChange={(interval) =>
                      typeof interval === "number" &&
                      patchElement("grid", { interval })
                    }
                  />
                </Field>
              </div>
            </>
          ),
        },
        {
          key: "elements",
          label: english ? "Map elements" : "地图整饰要素",
          children: (
            <div className="composition-element-settings">
              <TextEditor
                label={english ? "Title" : "标题"}
                value={layout.title}
                onChange={(values) => patchElement("title", values)}
              />
              <TextEditor
                label={english ? "Subtitle" : "副标题"}
                value={layout.subtitle}
                onChange={(values) => patchElement("subtitle", values)}
              />
              <Toggle
                label={english ? "Legend" : "图例"}
                checked={layout.legend.enabled}
                onChange={(enabled) => patchElement("legend", { enabled })}
              />
              <Toggle
                label={english ? "North arrow" : "指北针"}
                checked={layout.northArrow.enabled}
                onChange={(enabled) => patchElement("northArrow", { enabled })}
              />
              <Toggle
                label={english ? "Scale bar" : "比例尺"}
                checked={layout.scaleBar.enabled}
                onChange={(enabled) => patchElement("scaleBar", { enabled })}
              />
              <Toggle
                label={english ? "Overview inset" : "区位副图"}
                checked={layout.overview.enabled}
                onChange={(enabled) => patchElement("overview", { enabled })}
              />
              {layout.overview.enabled ? (
                <>
                  <BoundsEditor
                    value={layout.overview.bounds}
                    onChange={(bounds) => patchElement("overview", { bounds })}
                  />
                  <BoxEditor
                    value={layout.overview}
                    onChange={(values) => patchElement("overview", values)}
                  />
                </>
              ) : null}
            </div>
          ),
        },
        {
          key: "notes",
          label: english
            ? "Data source and cartographic notes"
            : "数据来源与制图说明",
          children: (
            <>
              <TextEditor
                label={english ? "Data source" : "数据来源"}
                value={layout.source}
                multiline
                onChange={(values) => patchElement("source", values)}
              />
              <TextEditor
                label={english ? "Cartographic notes" : "制图说明"}
                value={layout.note}
                multiline
                onChange={(values) => patchElement("note", values)}
              />
            </>
          ),
        },
      ]}
    />
  );
}
