export type Point = { x: number; y: number };
export type LayoutBox = Point & { width: number; height: number };

/** Pack related components beside one another instead of scattering fragments. */
export function packBoxes(weights: number[], box: LayoutBox): LayoutBox[] {
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  if (!total) return [];
  const areas = weights.map(
    (weight) => (weight / total) * box.width * box.height,
  );
  const result: LayoutBox[] = [];
  let remaining = { ...box };
  let index = 0;
  while (index < areas.length) {
    const side = Math.min(remaining.width, remaining.height);
    const row: number[] = [areas[index++]!];
    const score = (values: number[]) => {
      const sum = values.reduce((value, area) => value + area, 0);
      return Math.max(
        (side * side * Math.max(...values)) / (sum * sum),
        (sum * sum) / (side * side * Math.min(...values)),
      );
    };
    while (index < areas.length && score([...row, areas[index]!]) <= score(row))
      row.push(areas[index++]!);
    const area = row.reduce((value, item) => value + item, 0);
    const vertical = remaining.width >= remaining.height;
    const thickness = area / (vertical ? remaining.height : remaining.width);
    let offset = 0;
    for (const item of row) {
      const length = item / thickness;
      result.push(
        vertical
          ? {
              x: remaining.x,
              y: remaining.y + offset,
              width: thickness,
              height: length,
            }
          : {
              x: remaining.x + offset,
              y: remaining.y,
              width: length,
              height: thickness,
            },
      );
      offset += length;
    }
    remaining = vertical
      ? {
          ...remaining,
          x: remaining.x + thickness,
          width: Math.max(0, remaining.width - thickness),
        }
      : {
          ...remaining,
          y: remaining.y + thickness,
          height: Math.max(0, remaining.height - thickness),
        };
  }
  return result;
}

/** A stable, ordered spanning tree keeps the common chains and stars uncrossed. */
export function layoutComponent(
  ids: string[],
  neighbors: Map<string, Set<string>>,
  box: LayoutBox,
): Map<string, Point> {
  const ordered = [...ids].sort(
    (a, b) =>
      (neighbors.get(b)?.size ?? 0) - (neighbors.get(a)?.size ?? 0) ||
      a.localeCompare(b),
  );
  const root = ordered[0]!;
  const included = new Set(ids);
  const children = new Map<string, string[]>();
  const depth = new Map([[root, 0]]);
  const queue = [root];
  for (let index = 0; index < queue.length; index += 1) {
    const id = queue[index]!;
    const next = [...(neighbors.get(id) ?? [])]
      .filter((other) => included.has(other) && !depth.has(other))
      .sort((a, b) => a.localeCompare(b));
    children.set(id, next);
    for (const child of next) {
      depth.set(child, depth.get(id)! + 1);
      queue.push(child);
    }
  }
  const leafCount = new Map<string, number>();
  for (const id of [...queue].reverse()) {
    const next = children.get(id)!;
    leafCount.set(
      id,
      next.length
        ? next.reduce((sum, child) => sum + leafCount.get(child)!, 0)
        : 1,
    );
  }
  const horizontal = box.width >= box.height;
  const maxDepth = Math.max(...depth.values());
  const padding = 15;
  const along = Math.max(
    0,
    Math.min(
      horizontal ? box.width - padding * 2 : box.height - padding * 2,
      maxDepth * 64,
    ),
  );
  const across = Math.max(
    0,
    Math.min(
      horizontal ? box.height - padding * 2 : box.width - padding * 2,
      leafCount.get(root)! * 44,
    ),
  );
  const points = new Map<string, Point>();
  const place = (id: string, start: number) => {
    const count = leafCount.get(id)!;
    const u = maxDepth ? depth.get(id)! / maxDepth - 0.5 : 0;
    const v = (start + count / 2) / leafCount.get(root)! - 0.5;
    points.set(id, {
      x: box.x + box.width / 2 + (horizontal ? u * along : v * across),
      y: box.y + box.height / 2 + (horizontal ? v * across : u * along),
    });
    let cursor = start;
    for (const child of children.get(id)!) {
      place(child, cursor);
      cursor += leafCount.get(child)!;
    }
  };
  place(root, 0);
  return points;
}

export type NetworkViewport = { zoom: number; x: number; y: number };
export const initialViewport: NetworkViewport = { zoom: 1, x: 0, y: 0 };

/** Zoom around the pointer (or center) so the user's chosen location stays put. */
export function zoomViewport(
  view: NetworkViewport,
  factor: number,
  anchor: Point,
): NetworkViewport {
  const zoom = Math.max(0.55, Math.min(3.5, view.zoom * factor));
  const ratio = zoom / view.zoom;
  return {
    zoom,
    x: anchor.x - (anchor.x - view.x) * ratio,
    y: anchor.y - (anchor.y - view.y) * ratio,
  };
}
