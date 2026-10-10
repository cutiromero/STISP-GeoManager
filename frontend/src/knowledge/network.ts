import type { KnowledgeEntry } from "../api/generated/types.gen";
import { KNOWLEDGE_DOMAINS } from "./domains";
import { layoutNetwork, type Point } from "./networkLayout";

export type NetworkNode = Point & {
  id: string;
  domain: string;
  degree: number;
  color: string;
  primary: boolean;
  representative: boolean;
};
export type NetworkAnchor = Point & {
  id: string;
  domain: string | null;
  label: string;
  color: string;
  radius: number;
};
export type NavigationLink = {
  from: string;
  to: string;
  kind: "library" | "domain";
};

const networkDomains = [
  ...KNOWLEDGE_DOMAINS.map((domain, index) => ({
    ...domain,
    shortLabel: ["遥感基础", "油气管道", "地质填图推理", "干旱区生态治理"][
      index
    ]!,
    color: ["#4489d5", "#dc984f", "#8d79b8", "#43a58c"][index]!,
  })),
  {
    id: "unclassified" as const,
    label: "未分区",
    shortLabel: "未分区",
    color: "#92a2b2",
  },
];
export const nodeRadius = (degree: number) =>
  6 + Math.min(4, Math.sqrt(Math.max(0, degree - 1)) * 1.4);

export function networkSummary(
  entries: KnowledgeEntry[],
  selected: string | null = null,
) {
  const degree = new Map<string, number>();
  const domains = new Map<string, Set<string>>();
  for (const entry of entries) {
    for (const id of [entry.subject, entry.object]) {
      degree.set(id, (degree.get(id) ?? 0) + 1);
      domains.set(
        id,
        new Set([...(domains.get(id) ?? []), entry.domain ?? "unclassified"]),
      );
    }
  }
  const groups = networkDomains
    .map((domain) =>
      entries.filter((entry) => (entry.domain ?? "unclassified") === domain.id),
    )
    .filter((group) => group.length);
  const limit = groups.length > 1 ? Math.floor(48 / groups.length) : 48;
  const rank = (entry: KnowledgeEntry) =>
    degree.get(entry.subject)! +
    degree.get(entry.object)! +
    (domains.get(entry.subject)!.size > 1 || domains.get(entry.object)!.size > 1
      ? 100
      : 0);
  const summary = groups.flatMap((group) =>
    [...group].sort((a, b) => rank(b) - rank(a) || a.id - b.id).slice(0, limit),
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
  height = 580,
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
      count: edges.filter(
        (entry) => (entry.domain ?? "unclassified") === domain.id,
      ).length,
    }))
    .filter((domain) => domain.count);
  // Synthetic identifiers never collide with user-authored subjects or objects.
  const used = new Set(nodes.map((node) => node.id));
  const navigationId = (name: string) => {
    let id = `__navigation:${name}`;
    while (used.has(id)) id += ":";
    used.add(id);
    return id;
  };
  const rootId = navigationId("library");
  const anchors: NetworkAnchor[] = nodes.length
    ? [
        {
          id: rootId,
          domain: null,
          label: "时空知识库",
          color: "#4d78b3",
          radius: 13,
          x: 0,
          y: 0,
        },
        ...groups.map((domain) => ({
          id: navigationId(domain.id),
          domain: domain.id,
          label: domain.shortLabel,
          color: domain.color,
          radius: 10,
          x: 0,
          y: 0,
        })),
      ]
    : [];
  const navigation: NavigationLink[] = anchors
    .slice(1)
    .map((anchor) => ({ from: rootId, to: anchor.id, kind: "library" }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const available = new Set(used);
  const components: NetworkNode[][] = [];
  for (const root of nodes) {
    if (!available.delete(root.id)) continue;
    const component = [root];
    for (let cursor = 0; cursor < component.length; cursor += 1) {
      for (const other of neighbors.get(component[cursor]!.id) ?? []) {
        if (!available.delete(other)) continue;
        component.push(byId.get(other)!);
      }
    }
    components.push(component);
  }
  for (const component of components) {
    const ids = new Set(component.map((node) => node.id));
    for (const group of groups) {
      const relevant = component.filter((node) =>
        votes.get(node.id)!.has(group.id),
      );
      if (!relevant.length) continue;
      const representative = [...relevant].sort(
        (a, b) =>
          b.degree - a.degree ||
          a.id.length - b.id.length ||
          a.id.localeCompare(b.id),
      )[0]!;
      representative.representative = true;
      navigation.push({
        from: anchors.find((anchor) => anchor.domain === group.id)!.id,
        to: representative.id,
        kind: "domain",
      });
    }
    if (ids.size > 2) component[0]!.primary = true;
  }
  const positions = layoutNetwork(
    [
      ...anchors.map((anchor, index) => ({ ...anchor, anchor: index === 0 })),
      ...nodes.map((node) => ({
        id: node.id,
        radius: nodeRadius(node.degree),
      })),
    ],
    [
      ...navigation.map((link) => ({ ...link, navigation: true })),
      ...edges.map((entry) => ({ from: entry.subject, to: entry.object })),
    ],
    width,
    height,
  );
  for (const node of [...anchors, ...nodes])
    Object.assign(node, positions.get(node.id));
  return { nodes, edges, anchors, navigation, domains: groups, width, height };
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
