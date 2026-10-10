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
import {
  initialViewport,
  layoutComponent,
  packBoxes,
  zoomViewport,
  type Point,
} from "./networkLayout";

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

function crosses(a: Point, b: Point, c: Point, d: Point) {
  const cross = (p: Point, q: Point, r: Point) =>
    (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  return (
    cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0
  );
}

describe("knowledge atlas layout", () => {
  it("keeps genuine relations and domain groups without inventing links between components", () => {
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
    expect(network.regions).toHaveLength(2);
    expect(network.nodes.filter((node) => node.id === "NDVI")).toHaveLength(1);
    expect(buildNetwork([...entries].reverse())).toEqual(network);
  });

  it("balances the overview across all domains and exposes every selected-node relation", () => {
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
    expect(overview).toHaveLength(32);
    for (const domain of domains)
      expect(overview.filter((item) => item.domain === domain)).toHaveLength(8);
    const expanded = networkSummary(entries, "geology-主体");
    expect(
      expanded.filter((item) => item.subject === "geology-主体"),
    ).toHaveLength(40);
    expect(overview.every((item) => entries.includes(item))).toBe(true);
    expect(
      networkSummary(entries.filter((item) => item.domain === "geology")),
    ).toHaveLength(36);
  });

  it("packs unrelated components into non-overlapping regions and keeps nodes within their region on mobile", () => {
    const entries = domains.flatMap((domain, domainIndex) =>
      Array.from({ length: 8 }, (_, index) =>
        entry(
          domainIndex * 8 + index,
          `${domain}-a-${index}`,
          `${domain}-b-${index}`,
          domain,
        ),
      ),
    );
    const network = buildNetwork(entries, 390, 500);
    for (const node of network.nodes) {
      const region = network.regions.find((item) => item.id === node.domain)!;
      expect(node.x).toBeGreaterThanOrEqual(region.x + 6);
      expect(node.x).toBeLessThanOrEqual(region.x + region.width - 6);
      expect(node.y).toBeGreaterThanOrEqual(region.y + 35);
      expect(node.y).toBeLessThanOrEqual(region.y + region.height - 6);
      expect(nodeRadius(node.degree)).toBeLessThanOrEqual(9);
    }
    const boxes = packBoxes([6, 3, 3, 2], {
      x: 0,
      y: 0,
      width: 400,
      height: 300,
    });
    for (let first = 0; first < boxes.length; first += 1) {
      for (let second = first + 1; second < boxes.length; second += 1) {
        const a = boxes[first]!,
          b = boxes[second]!;
        expect(
          Math.min(a.x + a.width, b.x + b.width) <=
            Math.max(a.x, b.x) + 0.001 ||
            Math.min(a.y + a.height, b.y + b.height) <=
              Math.max(a.y, b.y) + 0.001,
        ).toBe(true);
      }
    }
  });

  it("draws a branching tree with no crossing edges and keeps separate chains compact", () => {
    const pairs = [
      ["a", "b"],
      ["a", "c"],
      ["b", "d"],
      ["b", "e"],
      ["c", "f"],
      ["c", "g"],
    ] as const;
    const neighbors = new Map<string, Set<string>>();
    for (const [from, to] of pairs) {
      neighbors.set(from, new Set([...(neighbors.get(from) ?? []), to]));
      neighbors.set(to, new Set([...(neighbors.get(to) ?? []), from]));
    }
    const points = layoutComponent([...neighbors.keys()], neighbors, {
      x: 0,
      y: 0,
      width: 500,
      height: 300,
    });
    for (let first = 0; first < pairs.length; first += 1)
      for (let second = first + 1; second < pairs.length; second += 1) {
        const [a, b] = pairs[first]!,
          [c, d] = pairs[second]!;
        if (a === c || a === d || b === c || b === d) continue;
        expect(
          crosses(
            points.get(a)!,
            points.get(b)!,
            points.get(c)!,
            points.get(d)!,
          ),
        ).toBe(false);
      }
    const chain = buildNetwork([entry(1, "红光", "近红外")]);
    expect(
      Math.hypot(
        chain.nodes[0]!.x - chain.nodes[1]!.x,
        chain.nodes[0]!.y - chain.nodes[1]!.y,
      ),
    ).toBeLessThanOrEqual(64);
  });

  it("shows unclassified optional entries without assigning them a scientific domain", () => {
    const item = { ...entry(1, "待分类甲", "待分类乙"), domain: undefined };
    expect(networkSummary([item])).toEqual([item]);
    expect(buildNetwork([item]).regions[0]!.label).toBe("未分区");
  });

  it("zooms around the chosen point, clamps the range and gives parallel/self links distinct paths", () => {
    const anchor = { x: 170, y: 100 };
    const zoomed = zoomViewport(initialViewport, 2, anchor);
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
