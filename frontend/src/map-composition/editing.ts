import type { LayoutBox, MapCompositionLayout, TextElement } from "./layout";

export const elementNames: Record<string, string> = {
  mapFrame: "主地图",
  overview: "鹰眼图",
  title: "标题",
  subtitle: "副标题",
  legend: "图例",
  source: "数据来源",
  note: "制图说明",
  northArrow: "指北针",
  scaleBar: "比例尺",
};
export const builtinOrder = Object.keys(elementNames);
export function elementOrder(layout: MapCompositionLayout): string[] {
  const keys = [...builtinOrder, ...layout.extraTexts.map((t) => t.id)];
  return [...new Set([...layout.editor.order, ...keys])].filter((k) =>
    keys.includes(k),
  );
}
export function elementBox(
  layout: MapCompositionLayout,
  id: string,
): LayoutBox & { enabled?: boolean; text?: string } {
  return (
    builtinOrder.includes(id)
      ? layout[id]
      : layout.extraTexts.find((t) => t.id === id)
  ) as LayoutBox & { enabled?: boolean; text?: string };
}
export function patchElement(
  layout: MapCompositionLayout,
  id: string,
  patch: Partial<LayoutBox & TextElement>,
): MapCompositionLayout {
  if (builtinOrder.includes(id))
    return { ...layout, [id]: { ...elementBox(layout, id), ...patch } };
  return {
    ...layout,
    extraTexts: layout.extraTexts.map((t) =>
      t.id === id ? { ...t, ...patch } : t,
    ),
  };
}
export function translateElements(
  layout: MapCompositionLayout,
  ids: string[],
  dx: number,
  dy: number,
): MapCompositionLayout {
  const movable = ids.filter((id) => !layout.editor.locked.includes(id));
  const boxes = movable.map((id) => elementBox(layout, id)).filter(Boolean);
  if (!boxes.length) return layout;
  dx = Math.max(
    -Math.min(...boxes.map((b) => b.xMm)),
    Math.min(
      dx,
      layout.page.widthMm - Math.max(...boxes.map((b) => b.xMm + b.widthMm)),
    ),
  );
  dy = Math.max(
    -Math.min(...boxes.map((b) => b.yMm)),
    Math.min(
      dy,
      layout.page.heightMm - Math.max(...boxes.map((b) => b.yMm + b.heightMm)),
    ),
  );
  return movable.reduce((next, id) => {
    const b = elementBox(layout, id);
    return patchElement(next, id, { xMm: b.xMm + dx, yMm: b.yMm + dy });
  }, layout);
}

export function distributeElements(
  layout: MapCompositionLayout,
  ids: string[],
  vertical = false,
) {
  const coordinate = vertical ? "yMm" : "xMm";
  const extent = vertical ? "heightMm" : "widthMm";
  const sorted = ids
    .filter((id) => !layout.editor.locked.includes(id))
    .sort(
      (a, b) =>
        elementBox(layout, a)[coordinate] - elementBox(layout, b)[coordinate],
    );
  if (sorted.length < 3) return layout;
  const boxes = sorted.map((id) => elementBox(layout, id));
  const first = boxes[0]![coordinate];
  const last = boxes[boxes.length - 1]!;
  const gap =
    (last[coordinate] +
      last[extent] -
      first -
      boxes.reduce((sum, b) => sum + b[extent], 0)) /
    (boxes.length - 1);
  let position = first;
  return sorted.reduce((next, id) => {
    const result = patchElement(next, id, { [coordinate]: position });
    position += elementBox(layout, id)[extent] + gap;
    return result;
  }, layout);
}
