import { describe, expect, it } from "vitest";
import type {
  KnowledgeDomain,
  KnowledgeEntry,
} from "../api/generated/types.gen";
import {
  buildNetwork,
  networkSummary,
  nodeRadius,
  relationPath,
} from "./network";
import { initialViewport, zoomViewport } from "./networkLayout";
import { realKnowledgeEntries } from "./network.test-fixture";

function entry(
  id: number,
  subject: string,
  object: string,
  domain: KnowledgeDomain = "remote_sensing",
): KnowledgeEntry {
  return {
    id,
    subject,
    object,
    domain,
    predicate: "关联",
    title: `${subject}与${object}`,
    category: "基础",
    projectTagId: 1,
    revision: 1,
    updatedAt: "2026-10-10T00:00:00Z",
    statement: "有来源的真实关系",
    explanation: "",
    conditions: [],
    exceptions: [],
    aliases: [],
    sources: [],
    status: "published",
    ruleKind: "none",
    ruleConfig: {},
  };
}
const domains: KnowledgeDomain[] = [
  "remote_sensing",
  "pipelines",
  "geology",
  "arid_ecology",
];
function connected(network: ReturnType<typeof buildNetwork>) {
  const all = [...network.nodes, ...network.anchors];
  const links = [
    ...network.navigation,
    ...network.edges.map((item) => ({ from: item.subject, to: item.object })),
  ];
  const reached = new Set([all[0]!.id]);
  for (let pass = 0; pass < all.length; pass += 1) {
    for (const link of links) {
      if (reached.has(link.from)) reached.add(link.to);
      if (reached.has(link.to)) reached.add(link.from);
    }
  }
  return reached.size === all.length;
}

describe("knowledge network layout", () => {
  it("connects sparse components with explicitly separate domain navigation, preserving every real relation", () => {
    const entries = [
      entry(1, "NDVI", "植被"),
      entry(2, "DEM", "高程"),
      entry(3, "NDVI", "干旱", "arid_ecology"),
    ];
    const network = buildNetwork(entries);
    expect(network.edges.map((item) => item.id)).toEqual([1, 2, 3]);
    expect(network.nodes.map((node) => node.id).sort()).toEqual(
      ["DEM", "NDVI", "干旱", "植被", "高程"].sort(),
    );
    expect(network.anchors).toHaveLength(3);
    expect(
      network.navigation.filter((link) => link.kind === "library"),
    ).toHaveLength(2);
    expect(
      network.navigation.filter((link) => link.kind === "domain"),
    ).toHaveLength(3);
    expect(network.nodes.filter((node) => node.id === "NDVI")).toHaveLength(1);
    expect(connected(network)).toBe(true);
    expect(buildNetwork([...entries].reverse())).toEqual(network);
  });

  it("balances domains, prioritizes genuine shared concepts and exposes selected-node relations", () => {
    const entries = domains.flatMap((domain, domainIndex) =>
      Array.from({ length: 40 }, (_, index) =>
        entry(
          domainIndex * 40 + index,
          `${domain}-主体`,
          `${domain}-${index}`,
          domain,
        ),
      ),
    );
    const overview = networkSummary(entries);
    expect(overview).toHaveLength(48);
    for (const domain of domains)
      expect(overview.filter((item) => item.domain === domain)).toHaveLength(
        12,
      );
    expect(
      networkSummary(entries, "geology-主体").filter(
        (item) => item.subject === "geology-主体",
      ),
    ).toHaveLength(40);
    const shared = [
      entry(500, "NDMI", "短波红外"),
      entry(501, "植被水分", "NDMI", "arid_ecology"),
    ];
    const withShared = networkSummary([...entries, ...shared]);
    expect(withShared.filter((item) => item.id >= 500)).toEqual(shared);
    expect(overview.every((item) => entries.includes(item))).toBe(true);
  });

  it("fits the real 90-entry seed collection at desktop and mobile widths without isolated fragments or overlapping circles", () => {
    expect(realKnowledgeEntries).toHaveLength(90);
    const summary = networkSummary(realKnowledgeEntries);
    for (const width of [1100, 358]) {
      const network = buildNetwork(summary, width, 580);
      expect(connected(network)).toBe(true);
      expect(
        network.navigation.filter((link) => link.kind === "library"),
      ).toHaveLength(4);
      const points = [
        ...network.nodes.map((node) => ({
          ...node,
          radius: nodeRadius(node.degree),
        })),
        ...network.anchors,
      ];
      for (const node of points) {
        expect(Number.isFinite(node.x) && Number.isFinite(node.y)).toBe(true);
        expect(node.x - node.radius).toBeGreaterThanOrEqual(0);
        expect(node.x + node.radius).toBeLessThan(width);
        expect(node.y - node.radius).toBeGreaterThanOrEqual(0);
        expect(node.y + node.radius).toBeLessThan(580);
      }
      for (let first = 0; first < points.length; first += 1) {
        for (let second = first + 1; second < points.length; second += 1) {
          const a = points[first]!,
            b = points[second]!;
          expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(
            a.radius + b.radius + 3,
          );
        }
      }
    }
  });

  it("handles self-relations, navigation-name collisions and empty/unclassified data", () => {
    expect(buildNetwork([]).anchors).toEqual([]);
    const entries = [
      entry(1, "__navigation:library", "__navigation:library"),
      { ...entry(2, "待分类甲", "待分类乙"), domain: undefined },
    ];
    const network = buildNetwork(entries);
    expect(
      new Set([...network.nodes, ...network.anchors].map((node) => node.id))
        .size,
    ).toBe(network.nodes.length + network.anchors.length);
    expect(connected(network)).toBe(true);
    expect(network.domains.some((domain) => domain.label === "未分区")).toBe(
      true,
    );
  });

  it("zooms around a chosen point and separates parallel/self relations", () => {
    const anchor = { x: 170, y: 100 },
      zoomed = zoomViewport(initialViewport, 2, anchor);
    expect((anchor.x - zoomed.x) / zoomed.zoom).toBe(anchor.x);
    expect((anchor.y - zoomed.y) / zoomed.zoom).toBe(anchor.y);
    expect(zoomViewport(zoomed, 100, anchor).zoom).toBe(3.5);
    expect(zoomViewport(zoomed, 0.001, anchor).zoom).toBe(0.55);
    expect(relationPath({ x: 0, y: 0 }, { x: 80, y: 0 }, -1)).not.toBe(
      relationPath({ x: 0, y: 0 }, { x: 80, y: 0 }, 1),
    );
    expect(relationPath(anchor, anchor)).toContain(" C ");
  });
});
