import type { KnowledgeEntry } from "../api/generated/types.gen";
import { KNOWLEDGE_DOMAINS } from "./domains";
import {
  layoutComponent,
  packBoxes,
  type LayoutBox,
  type Point,
} from "./networkLayout";

export type NetworkNode = Point & {
  id: string;
  domain: string;
  degree: number;
  color: string;
  primary: boolean;
  representative: boolean;
};

const networkDomains = [
  ...KNOWLEDGE_DOMAINS.map((domain, index) => ({
    ...domain,
    color: ["#7dc7ff", "#a8bce9", "#b5c1ef", "#79cad6"][index]!,
  })),
  { id: "unclassified" as const, label: "未分区", color: "#a0afbd" },
];

export function nodeRadius(degree: number) {
  return 5 + Math.min(4, Math.sqrt(Math.max(0, degree - 1)) * 1.6);
}

export function networkSummary(
  entries: KnowledgeEntry[],
  selected: string | null = null,
) {
  const degree = new Map<string, number>();
  for (const entry of entries) {
    for (const id of [entry.subject, entry.object])
      degree.set(id, (degree.get(id) ?? 0) + 1);
  }
  const groups = networkDomains
    .map((domain) =>
      entries.filter((entry) => (entry.domain ?? "unclassified") === domain.id),
    )
    .filter((group) => group.length);
  const limit = groups.length > 1 ? Math.floor(32 / groups.length) : 36;
  const summary = groups.flatMap((group) =>
    [...group]
      .sort(
        (a, b) =>
          degree.get(b.subject)! +
            degree.get(b.object)! -
            (degree.get(a.subject)! + degree.get(a.object)!) || a.id - b.id,
      )
      .slice(0, limit),
  );
  if (selected) {
    for (const entry of entries) {
      if (
        (entry.subject === selected || entry.object === selected) &&
        !summary.some((item) => item.id === entry.id)
      )
        summary.push(entry);
    }
  }
  return summary.sort((a, b) => a.id - b.id);
}

export function buildNetwork(
  entries: KnowledgeEntry[],
  width = 1100,
  height = 520,
) {
  const edges = [...entries].sort((a, b) => a.id - b.id);
  const votes = new Map<string, Map<string, number>>();
  const neighbors = new Map<string, Set<string>>();
  for (const entry of edges) {
    for (const [id, other] of [
      [entry.subject, entry.object],
      [entry.object, entry.subject],
    ] as const) {
      const domains = votes.get(id) ?? new Map<string, number>();
      const domain = entry.domain ?? "unclassified";
      domains.set(domain, (domains.get(domain) ?? 0) + 1);
      votes.set(id, domains);
      const adjacent = neighbors.get(id) ?? new Set<string>();
      if (id !== other) adjacent.add(other);
      neighbors.set(id, adjacent);
    }
  }
  const nodes = [...votes]
    .map(([id, domains]): NetworkNode => {
      const domain = [...domains].sort(
        (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
      )[0]![0];
      return {
        id,
        domain,
        degree: [...domains.values()].reduce((sum, count) => sum + count, 0),
        color: networkDomains.find((item) => item.id === domain)!.color,
        x: 0,
        y: 0,
        primary: false,
        representative: false,
      };
    })
    .sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id));
  const groups = networkDomains
    .map((domain) => ({
      ...domain,
      nodes: nodes.filter((node) => node.domain === domain.id),
      count: entries.filter(
        (entry) => (entry.domain ?? "unclassified") === domain.id,
      ).length,
    }))
    .filter((group) => group.nodes.length);
  const padding = width < 650 ? 12 : 24;
  const boxes = packBoxes(
    groups.map((group) => Math.sqrt(group.nodes.length) + 2),
    {
      x: padding,
      y: padding,
      width: width - padding * 2,
      height: height - padding * 2,
    },
  );
  const regions = groups.map((group, index) => {
    const region = boxes[index]!;
    const margin = width < 650 ? 7 : 12;
    const box = {
      x: region.x + margin,
      y: region.y + margin,
      width: region.width - margin * 2,
      height: region.height - margin * 2,
    };
    const components: NetworkNode[][] = [];
    const available = new Set(group.nodes.map((node) => node.id));
    const byId = new Map(group.nodes.map((node) => [node.id, node]));
    for (const root of group.nodes) {
      if (!available.has(root.id)) continue;
      const component = [root];
      available.delete(root.id);
      for (let cursor = 0; cursor < component.length; cursor += 1) {
        for (const other of neighbors.get(component[cursor]!.id) ?? []) {
          if (!available.delete(other)) continue;
          component.push(byId.get(other)!);
        }
      }
      components.push(component);
    }
    components.sort(
      (a, b) => b.length - a.length || a[0]!.id.localeCompare(b[0]!.id),
    );
    const inner: LayoutBox = {
      x: box.x + 7,
      y: box.y + 42,
      width: box.width - 14,
      height: box.height - 56,
    };
    const cells = packBoxes(
      components.map((component) => component.length + 1),
      inner,
    );
    components.forEach((component, componentIndex) => {
      const points = layoutComponent(
        component.map((node) => node.id),
        neighbors,
        cells[componentIndex]!,
      );
      component[0]!.representative = true;
      for (const node of component) Object.assign(node, points.get(node.id));
    });
    group.nodes
      .slice(0, Math.min(3, Math.ceil(group.nodes.length / 8)))
      .forEach((node) => {
        node.primary = true;
      });
    return {
      ...box,
      id: group.id,
      label: group.label,
      color: group.color,
      count: group.count,
    };
  });
  return { nodes, edges, regions, width, height };
}

/** Offset parallel relations and self-relations without introducing new edges. */
export function relationPath(from: Point, to: Point, lane = 0) {
  const dx = to.x - from.x,
    dy = to.y - from.y;
  const length = Math.hypot(dx, dy);
  if (length < 0.001)
    return `M ${from.x - 4} ${from.y - 4} C ${from.x - 30} ${from.y - 42}, ${from.x + 30} ${from.y - 42}, ${from.x + 4} ${from.y - 4}`;
  const offset = lane * 16;
  return `M ${from.x} ${from.y} Q ${(from.x + to.x) / 2 - (dy / length) * offset} ${(from.y + to.y) / 2 + (dx / length) * offset} ${to.x} ${to.y}`;
}
