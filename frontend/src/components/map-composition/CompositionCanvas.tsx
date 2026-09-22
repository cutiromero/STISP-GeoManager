import { Button, Checkbox, Input, Select, Space, Switch } from "antd";
import { useRef, useState, type PointerEvent } from "react";
import {
  panMapBounds,
  type MapCompositionLayout,
} from "../../map-composition/layout";
import {
  distributeElements,
  elementBox,
  elementNames,
  elementOrder,
  patchElement,
  translateElements,
} from "../../map-composition/editing";
import { createUuid } from "../../utils/uuid";
import { BoxEditor } from "./CompositionFieldEditors";
import "../../styles/composition-canvas.css";

type Props = {
  layout: MapCompositionLayout;
  previewUrl: string;
  onChange: (
    update: (layout: MapCompositionLayout) => MapCompositionLayout,
  ) => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
};
export default function CompositionCanvas({
  layout,
  previewUrl,
  onChange,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [draft, setDraft] = useState<MapCompositionLayout | null>(null);
  const [snap, setSnap] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [mapContentMode, setMapContentMode] = useState(false);
  const page = useRef<HTMLDivElement>(null);
  const gesture = useRef<{
    x: number;
    y: number;
    scaleX: number;
    scaleY: number;
    layout: MapCompositionLayout;
    ids: string[];
    resize: boolean;
    next: MapCompositionLayout;
  } | null>(null);
  const current = draft ?? layout;
  const order = elementOrder(current);
  const active = selected[0] ? elementBox(current, selected[0]) : undefined;
  const locked = selected.some((id) => layout.editor.locked.includes(id));

  function begin(event: PointerEvent<HTMLElement>, id: string, resize = false) {
    event.stopPropagation();
    if (event.button !== 0) return;
    const ids = event.shiftKey
      ? selected.includes(id)
        ? selected.filter((k) => k !== id)
        : [...selected, id]
      : selected.includes(id)
        ? selected
        : [id];
    setSelected(ids);
    event.currentTarget.focus();
    if (layout.editor.locked.includes(id) || !ids.length) return;
    const rect = page.current!.getBoundingClientRect();
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = {
      x: event.clientX,
      y: event.clientY,
      scaleX: layout.page.widthMm / rect.width,
      scaleY: layout.page.heightMm / rect.height,
      layout,
      ids,
      resize,
      next: layout,
    };
  }
  function move(event: PointerEvent<HTMLElement>) {
    const g = gesture.current;
    if (!g) return;
    const round = (n: number) => (snap ? Math.round(n / 2) * 2 : n);
    const dx = round((event.clientX - g.x) * g.scaleX);
    const dy = round((event.clientY - g.y) * g.scaleY);
    if (g.resize) {
      const id = g.ids[0]!;
      const b = elementBox(g.layout, id);
      g.next = patchElement(g.layout, id, {
        widthMm: Math.max(
          2,
          Math.min(g.layout.page.widthMm - b.xMm, b.widthMm + dx),
        ),
        heightMm: Math.max(
          2,
          Math.min(g.layout.page.heightMm - b.yMm, b.heightMm + dy),
        ),
      });
    } else if (
      mapContentMode &&
      g.ids.length === 1 &&
      g.ids[0] === "mapFrame"
    ) {
      g.next = {
        ...g.layout,
        mapFrame: {
          ...g.layout.mapFrame,
          bounds: panMapBounds(
            g.layout.mapFrame.bounds,
            -dx / g.layout.mapFrame.widthMm,
            dy / g.layout.mapFrame.heightMm,
          ),
        },
      };
    } else g.next = translateElements(g.layout, g.ids, dx, dy);
    setDraft(g.next);
  }
  function end(cancel = false) {
    const g = gesture.current;
    gesture.current = null;
    setDraft(null);
    if (g && !cancel && g.next !== g.layout) onChange(() => g.next);
  }
  function text(copy = false) {
    const source = active && "fontSizePt" in active ? active : layout.note;
    const id = `text-${createUuid()}`;
    onChange((l) => ({
      ...l,
      extraTexts: [
        ...l.extraTexts,
        {
          ...l.note,
          ...source,
          id,
          enabled: true,
          text: copy ? (source.text ?? "文字") : "双击选中文字后，在下方编辑",
          xMm: Math.min(l.page.widthMm - 62, (source.xMm ?? 20) + 5),
          yMm: Math.min(l.page.heightMm - 15, (source.yMm ?? 20) + 5),
          widthMm: 60,
          heightMm: 12,
          fontSizePt: 10,
          align: "left",
        },
      ],
    }));
    setSelected([id]);
  }
  function visibility() {
    onChange((l) =>
      selected.reduce(
        (n, id) =>
          id === "mapFrame" || l.editor.locked.includes(id)
            ? n
            : patchElement(n, id, { enabled: false }),
        l,
      ),
    );
    setSelected([]);
  }
  return (
    <div
      className="composition-canvas"
      onKeyDown={(event) => {
        if (
          (event.target as HTMLElement).matches("input,textarea,select") ||
          (event.target as HTMLElement).closest(".ant-select")
        )
          return;
        if (event.key === "Escape") {
          end(true);
          setSelected([]);
          return;
        }
        if (
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "z"
        ) {
          event.preventDefault();
          if (event.shiftKey) onRedo();
          else onUndo();
        }
        if (
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "y"
        ) {
          event.preventDefault();
          onRedo();
        }
        if (event.key === "Delete") {
          event.preventDefault();
          visibility();
        }
        const offset = {
          ArrowLeft: [-1, 0],
          ArrowRight: [1, 0],
          ArrowUp: [0, -1],
          ArrowDown: [0, 1],
        }[event.key];
        if (offset && selected.length) {
          event.preventDefault();
          onChange((l) =>
            translateElements(
              l,
              selected,
              offset[0]! * (event.shiftKey ? 10 : 1),
              offset[1]! * (event.shiftKey ? 10 : 1),
            ),
          );
        }
      }}
    >
      <Space wrap className="composition-canvas-tools">
        <Button disabled={!canUndo} onClick={onUndo}>
          撤销
        </Button>
        <Button disabled={!canRedo} onClick={onRedo}>
          重做
        </Button>
        <Button onClick={() => text()}>添加文字</Button>
        <Button disabled={!active?.text || locked} onClick={() => text(true)}>
          复制文字
        </Button>
        <Button
          disabled={!selected.length}
          onClick={() =>
            onChange((l) => ({
              ...l,
              editor: {
                ...l.editor,
                locked: locked
                  ? l.editor.locked.filter((id) => !selected.includes(id))
                  : [...new Set([...l.editor.locked, ...selected])],
              },
            }))
          }
        >
          {locked ? "解锁" : "锁定"}
        </Button>
        <Button disabled={!selected.length || locked} onClick={visibility}>
          隐藏
        </Button>
        <Button
          disabled={!selected.length || locked}
          onClick={() =>
            onChange((l) => ({
              ...l,
              editor: {
                ...l.editor,
                order: [
                  ...elementOrder(l).filter((id) => !selected.includes(id)),
                  ...selected,
                ],
              },
            }))
          }
        >
          置顶
        </Button>
        <Button
          disabled={!selected.length || locked}
          onClick={() =>
            onChange((l) => ({
              ...l,
              editor: {
                ...l.editor,
                order: [
                  ...selected,
                  ...elementOrder(l).filter((id) => !selected.includes(id)),
                ],
              },
            }))
          }
        >
          置底
        </Button>
        <Select
          aria-label="对齐选中要素"
          placeholder="对齐"
          value={null}
          style={{ width: 110 }}
          disabled={!active || locked}
          options={[
            { value: "left", label: "左对齐" },
            { value: "top", label: "顶对齐" },
            { value: "center", label: "水平居中" },
          ]}
          onChange={(value) =>
            onChange((l) =>
              selected.reduce(
                (n, id) =>
                  patchElement(
                    n,
                    id,
                    value === "top"
                      ? { yMm: active!.yMm }
                      : {
                          xMm:
                            value === "left"
                              ? active!.xMm
                              : (l.page.widthMm - elementBox(l, id).widthMm) /
                                2,
                        },
                  ),
                l,
              ),
            )
          }
        />
        <Checkbox checked={snap} onChange={(e) => setSnap(e.target.checked)}>
          2 mm 吸附
        </Checkbox>
        <Checkbox
          checked={mapContentMode}
          onChange={(e) => setMapContentMode(e.target.checked)}
        >
          平移地图内容
        </Checkbox>
        <Button
          disabled={selected.length < 3 || locked}
          onClick={() => onChange((l) => distributeElements(l, selected))}
        >
          水平分布
        </Button>
        <Button
          disabled={selected.length < 3 || locked}
          onClick={() => onChange((l) => distributeElements(l, selected, true))}
        >
          垂直分布
        </Button>
        <Select
          aria-label="画布缩放"
          value={zoom}
          onChange={setZoom}
          options={[50, 75, 100, 125, 150, 200].map((value) => ({
            value,
            label: `${value}%`,
          }))}
        />
      </Space>
      <div className="composition-canvas-scroll">
        <div
          ref={page}
          className="composition-editable-paper"
          style={{
            width: `${zoom}%`,
            aspectRatio: `${layout.page.widthMm}/${layout.page.heightMm}`,
            backgroundColor: layout.page.backgroundColor,
          }}
          onPointerDown={() => setSelected([])}
        >
          {previewUrl && (
            <img
              draggable={false}
              src={previewUrl}
              alt="专题图预览"
              className="composition-canvas-image"
            />
          )}
          {order.map((id) => {
            const b = elementBox(current, id);
            if (!b || b.enabled === false) return null;
            const isSelected = selected.includes(id);
            return (
              <div
                key={id}
                role="button"
                tabIndex={0}
                aria-label={`制图要素：${elementNames[id] ?? b.text ?? "文字"}`}
                aria-pressed={isSelected}
                className={`composition-element ${isSelected ? "selected" : ""} ${current.editor.locked.includes(id) ? "locked" : ""}`}
                style={{
                  left: `${(b.xMm / layout.page.widthMm) * 100}%`,
                  top: `${(b.yMm / layout.page.heightMm) * 100}%`,
                  width: `${(b.widthMm / layout.page.widthMm) * 100}%`,
                  height: `${(b.heightMm / layout.page.heightMm) * 100}%`,
                }}
                onPointerDown={(e) => begin(e, id)}
                onPointerMove={move}
                onPointerUp={() => end()}
                onPointerCancel={() => end(true)}
                onClick={(e) => e.stopPropagation()}
              >
                {(isSelected || !previewUrl) && (
                  <span className="composition-element-name">
                    {elementNames[id] ?? "文字"}
                    {current.editor.locked.includes(id) ? " · 已锁定" : ""}
                  </span>
                )}
                {isSelected && selected.length === 1 && !locked && (
                  <span
                    role="button"
                    aria-label="缩放选中要素"
                    className="composition-resize-handle"
                    onPointerDown={(e) => begin(e, id, true)}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="composition-selection-properties">
        <Select
          aria-label="选择制图要素"
          mode="multiple"
          value={selected}
          onChange={setSelected}
          placeholder="选择要素；Shift 点选可多选"
          style={{ width: "100%" }}
          options={order.map((id) => ({
            value: id,
            label: `${elementNames[id] ?? elementBox(layout, id)?.text ?? "文字"}${elementBox(layout, id)?.enabled === false ? "（隐藏）" : ""}`,
          }))}
        />
        {active && selected.length === 1 && (
          <fieldset disabled={locked}>
            <BoxEditor
              value={active}
              onChange={(patch) =>
                !locked && onChange((l) => patchElement(l, selected[0]!, patch))
              }
            />
            {active.enabled !== undefined && (
              <label>
                显示{" "}
                <Switch
                  checked={active.enabled}
                  disabled={locked}
                  onChange={(enabled) =>
                    onChange((l) => patchElement(l, selected[0]!, { enabled }))
                  }
                />
              </label>
            )}
            {typeof active.text === "string" && (
              <Input.TextArea
                aria-label="选中要素文字"
                disabled={locked}
                rows={2}
                value={active.text}
                onChange={(e) =>
                  onChange((l) =>
                    patchElement(l, selected[0]!, { text: e.target.value }),
                  )
                }
              />
            )}
          </fieldset>
        )}
        <small>
          拖动要素移动；右下角缩放；方向键微调，Shift 加速；Ctrl/Cmd+Z
          撤销。松开鼠标后更新出图预览。
        </small>
      </div>
    </div>
  );
}
