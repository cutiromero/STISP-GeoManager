export type Point = { x: number; y: number };
export type LayoutNode = { id: string; radius: number; anchor?: boolean };
export type LayoutLink = { from: string; to: string; navigation?: boolean };

/** A deterministic force layout lets real cross-domain links bring topics together. */
export function layoutNetwork(
  nodes: LayoutNode[],
  links: LayoutLink[],
  width: number,
  height: number,
): Map<string, Point> {
  if (!nodes.length) return new Map();
  const indices = new Map(nodes.map((node, index) => [node.id, index]));
  const springs = links.flatMap((link) => {
    const from = indices.get(link.from),
      to = indices.get(link.to);
    if (from === undefined || to === undefined || from === to) return [];
    return [{ from, to, navigation: link.navigation }];
  });
  const root = nodes.findIndex((node) => node.anchor);
  const origin = root < 0 ? 0 : root;
  const points = nodes.map((_, index) => {
    const angle = index * 2.399963229728653;
    const radius = index === origin ? 0 : 60 + Math.sqrt(index) * 27;
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  });
  for (let iteration = 0; iteration < 240; iteration += 1) {
    const offsets = points.map((point, index) => ({
      x: -point.x * (index === origin ? 0.016 : 0.01),
      y: -point.y * (index === origin ? 0.016 : 0.01),
    }));
    for (let first = 0; first < points.length; first += 1) {
      for (let second = first + 1; second < points.length; second += 1) {
        const a = points[first]!,
          b = points[second]!;
        let dx = a.x - b.x,
          dy = a.y - b.y;
        if (Math.abs(dx) + Math.abs(dy) < 0.001) dx = 0.01;
        const squared = Math.max(16, dx * dx + dy * dy);
        const distance = Math.sqrt(squared);
        const separation = nodes[first]!.radius + nodes[second]!.radius + 18;
        const force =
          950 / squared +
          (Math.max(0, separation - distance) / distance) * 0.25;
        offsets[first]!.x += dx * force;
        offsets[first]!.y += dy * force;
        offsets[second]!.x -= dx * force;
        offsets[second]!.y -= dy * force;
      }
    }
    for (const spring of springs) {
      const a = points[spring.from]!,
        b = points[spring.to]!;
      const dx = b.x - a.x,
        dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const target = spring.navigation ? 80 : 60;
      const force =
        ((distance - target) / distance) * (spring.navigation ? 0.028 : 0.065);
      offsets[spring.from]!.x += dx * force;
      offsets[spring.from]!.y += dy * force;
      offsets[spring.to]!.x -= dx * force;
      offsets[spring.to]!.y -= dy * force;
    }
    const cooling = 1 - iteration / 310;
    points.forEach((point, index) => {
      const offset = offsets[index]!;
      const step =
        Math.min(1, 10 / Math.max(1, Math.hypot(offset.x, offset.y))) * cooling;
      point.x += offset.x * step;
      point.y += offset.y * step;
    });
  }
  const minX = Math.min(...points.map((point) => point.x)),
    maxX = Math.max(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y)),
    maxY = Math.max(...points.map((point) => point.y));
  const paddingX = width < 650 ? 30 : 65,
    paddingY = 58;
  const scaleX = Math.min(
    1.4,
    (width - paddingX * 2) / Math.max(1, maxX - minX),
  );
  const scaleY = Math.min(
    1.25,
    (height - paddingY * 2) / Math.max(1, maxY - minY),
  );
  points.forEach((point) => {
    point.x = width / 2 + (point.x - (minX + maxX) / 2) * scaleX;
    point.y = height / 2 + (point.y - (minY + maxY) / 2) * scaleY;
  });
  // Resolve the small overlaps introduced by fitting a narrow screen.
  for (let iteration = 0; iteration < 32; iteration += 1) {
    for (let first = 0; first < points.length; first += 1) {
      for (let second = first + 1; second < points.length; second += 1) {
        const a = points[first]!,
          b = points[second]!;
        const dx = b.x - a.x,
          dy = b.y - a.y;
        const distance = Math.max(0.01, Math.hypot(dx, dy));
        const minimum = nodes[first]!.radius + nodes[second]!.radius + 5;
        if (distance >= minimum) continue;
        const shift = ((minimum - distance) / distance) * 0.5;
        a.x -= dx * shift;
        a.y -= dy * shift;
        b.x += dx * shift;
        b.y += dy * shift;
      }
    }
    points.forEach((point) => {
      point.x = Math.max(paddingX, Math.min(width - paddingX, point.x));
      point.y = Math.max(paddingY, Math.min(height - paddingY, point.y));
    });
  }
  return new Map(nodes.map((node, index) => [node.id, points[index]!]));
}

export type NetworkViewport = { zoom: number; x: number; y: number };
export const initialViewport: NetworkViewport = { zoom: 1, x: 0, y: 0 };

/** Keep the user's chosen location under the pointer while zooming. */
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
