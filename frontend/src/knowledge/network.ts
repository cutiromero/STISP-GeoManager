import type { KnowledgeEntry } from "../api/generated/types.gen";

export type NetworkNode = {
  id: string;
  category: string;
  degree: number;
  x: number;
  y: number;
};
export const networkColors = [
  "#65c8c6",
  "#8ab5ec",
  "#d6bd82",
  "#96ccb0",
  "#b6a9dc",
  "#dfb29c",
];

export function buildNetwork(entries: KnowledgeEntry[]) {
  const edges = entries.slice(0, 40);
  const nodes = new Map<string, NetworkNode>();
  for (const entry of edges) {
    for (const id of [entry.subject, entry.object]) {
      const node = nodes.get(id);
      if (node) node.degree += 1;
      else
        nodes.set(id, { id, category: entry.category, degree: 1, x: 0, y: 0 });
    }
  }
  const points = [...nodes.values()].sort(
    (a, b) => b.degree - a.degree || a.id.localeCompare(b.id),
  );
  points.forEach((node, index) => {
    const angle = index * 2.399963;
    const radius = 50 + Math.sqrt(index / Math.max(1, points.length)) * 330;
    node.x = 550 + Math.cos(angle) * radius * 1.25;
    node.y = 250 + Math.sin(angle) * radius * 0.6;
  });
  for (let iteration = 0; iteration < 180; iteration += 1) {
    const cooling = 1 - iteration / 240;
    const offsets = points.map((node) => {
      let dx = (550 - node.x) * 0.012,
        dy = (250 - node.y) * 0.045;
      for (const other of points) {
        if (other === node) continue;
        const x = node.x - other.x,
          y = node.y - other.y;
        const distance = Math.max(100, x * x + y * y);
        dx += (x * 360) / distance;
        dy += (y * 360) / distance;
      }
      for (const edge of edges) {
        const otherId =
          edge.subject === node.id
            ? edge.object
            : edge.object === node.id
              ? edge.subject
              : null;
        if (!otherId || otherId === node.id) continue;
        const other = nodes.get(otherId)!;
        const x = other.x - node.x,
          y = other.y - node.y;
        const distance = Math.max(1, Math.hypot(x, y));
        const spring = ((distance - 150) / distance) * 0.035;
        dx += x * spring;
        dy += y * spring;
      }
      const step = Math.min(1, 8 / Math.max(1, Math.hypot(dx, dy))) * cooling;
      return { x: dx * step, y: dy * step };
    });
    points.forEach((node, index) => {
      const offset = offsets[index]!;
      node.x += offset.x;
      node.y += offset.y;
    });
  }
  if (points.length) {
    // Fit the whole network without accumulating nodes against hard boundaries.
    const minX = Math.min(...points.map((node) => node.x));
    const maxX = Math.max(...points.map((node) => node.x));
    const minY = Math.min(...points.map((node) => node.y));
    const maxY = Math.max(...points.map((node) => node.y));
    const scaleX = Math.min(1.25, 880 / Math.max(1, maxX - minX));
    const scaleY = Math.min(1.25, 300 / Math.max(1, maxY - minY));
    points.forEach((node) => {
      node.x = 550 + (node.x - (minX + maxX) / 2) * scaleX;
      node.y = 235 + (node.y - (minY + maxY) / 2) * scaleY;
    });
  }
  return {
    nodes: points,
    edges,
    categories: [...new Set(edges.map((entry) => entry.category))],
  };
}
