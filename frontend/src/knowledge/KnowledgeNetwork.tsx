import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Select, Space } from "antd";
import { MinusOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
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
  zoomViewport,
  type NetworkViewport,
  type Point,
} from "./networkLayout";

export default function KnowledgeNetwork({
  entries,
  selected,
  onSelect,
  onOpen,
  onDomainSelect,
}: {
  entries: KnowledgeEntry[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  onOpen: (entry: KnowledgeEntry) => void;
  domain?: string;
  onDomainSelect?: (domain: KnowledgeDomain | undefined) => void;
}) {
  const section = useRef<HTMLElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const canvas = useRef<SVGRectElement>(null);
  const [size, setSize] = useState({ width: 1100, height: 580 });
  const summary = useMemo(() => networkSummary(entries), [entries]);
  const network = useMemo(
    () => buildNetwork(summary, size.width, size.height),
    [summary, size],
  );
  const [positions, setPositions] = useState<Record<string, Point>>({});
  const [view, setView] = useState<NetworkViewport>(initialViewport);
  const viewRef = useRef(view);
  viewRef.current = view;
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    key: number;
    kind: "node" | "edge" | "canvas";
    x: number;
    y: number;
    radius: number;
  } | null>(null);
  const feedbackSequence = useRef(0);
  const drag = useRef<{
    id: string | null;
    pointer: number;
    client: Point;
    start: Point;
    position: Point;
    view: NetworkViewport;
    moved: boolean;
  } | null>(null);
  const entryKey = entries
    .map((entry) => `${entry.id}:${entry.revision}`)
    .join(",");
  useEffect(() => {
    const element = section.current;
    if (!element) return;
    const update = () => {
      const width = Math.max(
        320,
        Math.round(element.getBoundingClientRect().width),
      );
      const height = width < 650 ? 520 : 580;
      setSize((current) =>
        current.width === width && current.height === height
          ? current
          : { width, height },
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setPositions({});
    setView(initialViewport);
    setSelectedEdge(null);
    setFeedback(null);
  }, [entryKey, size]);
  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(null), 800);
    return () => window.clearTimeout(timer);
  }, [feedback]);
  useEffect(() => {
    const element = svg.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const anchor = localPoint(event.clientX, event.clientY);
      setView((current) =>
        zoomViewport(
          current,
          Math.exp(-Math.max(-100, Math.min(100, event.deltaY)) * 0.002),
          anchor,
        ),
      );
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [network.nodes.length]);
  const points = new Map(
    network.nodes.map((node) => [node.id, { ...node, ...positions[node.id] }]),
  );
  const allPoints = new Map<string, Point>([
    ...points,
    ...network.anchors.map((anchor) => [anchor.id, anchor] as const),
  ]);
  const neighbors = new Set(
    summary.flatMap((entry) =>
      entry.subject === selected
        ? [entry.object]
        : entry.object === selected
          ? [entry.subject]
          : [],
    ),
  );
  function localPoint(clientX: number, clientY: number): Point {
    const transform = svg.current?.getScreenCTM();
    if (!transform) return { x: size.width / 2, y: size.height / 2 };
    return new DOMPoint(clientX, clientY).matrixTransform(transform.inverse());
  }
  function coordinate(clientX: number, clientY: number): Point {
    const local = localPoint(clientX, clientY),
      current = viewRef.current;
    return {
      x: (local.x - current.x) / current.zoom,
      y: (local.y - current.y) / current.zoom,
    };
  }
  function showFeedback(
    kind: "node" | "edge" | "canvas",
    point: Point,
    radius: number,
  ) {
    setFeedback({ key: ++feedbackSequence.current, kind, ...point, radius });
  }
  function selectNode(id: string) {
    const node = points.get(id)!;
    showFeedback("node", node, nodeRadius(node.degree) + 12);
    onSelect(selected === id ? null : id);
  }
  function locateNode(id: string) {
    const node = points.get(id);
    if (!node) return;
    onSelect(id);
    const zoom = Math.max(1.45, viewRef.current.zoom);
    setView({
      zoom,
      x: size.width / 2 - node.x * zoom,
      y: size.height / 2 - node.y * zoom,
    });
    showFeedback("node", node, nodeRadius(node.degree) + 12);
  }
  function openRelation(entry: KnowledgeEntry) {
    const from = points.get(entry.subject)!,
      to = points.get(entry.object)!;
    showFeedback(
      "edge",
      { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 },
      19,
    );
    setSelectedEdge(entry.id);
    onOpen(entry);
  }
  function startDrag(id: string | null, event: React.PointerEvent<SVGElement>) {
    if (event.button !== 0 || drag.current) return;
    event.preventDefault();
    const start = localPoint(event.clientX, event.clientY);
    drag.current = {
      id,
      pointer: event.pointerId,
      client: { x: event.clientX, y: event.clientY },
      start,
      position: id ? points.get(id)! : { x: 0, y: 0 },
      view: { ...viewRef.current },
      moved: false,
    };
    svg.current?.setPointerCapture(event.pointerId);
  }
  function reset() {
    setPositions({});
    setView(initialViewport);
    setSelectedEdge(null);
    setFeedback(null);
    onSelect(null);
  }
  const pairCounts = new Map<string, number>();
  const pairLanes = new Map<number, number>();
  for (const entry of summary) {
    const key = [entry.subject, entry.object].sort().join("\0");
    pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
  }
  const pairIndices = new Map<string, number>();
  for (const entry of summary) {
    const key = [entry.subject, entry.object].sort().join("\0");
    const index = pairIndices.get(key) ?? 0;
    pairLanes.set(
      entry.id,
      (index - (pairCounts.get(key)! - 1) / 2) *
        (entry.subject < entry.object ? 1 : -1),
    );
    pairIndices.set(key, index + 1);
  }
  const labelBoxes: { x: number; y: number; width: number; height: number }[] =
    [];
  const anchorLabels = new Map<string, Point>();
  const circles = [
    ...network.anchors.map((anchor) => ({
      ...anchor,
      radius: anchor.radius + 4,
    })),
    ...points.values(),
  ].map((node) => ({
    x: node.x,
    y: node.y,
    radius: "radius" in node ? node.radius : nodeRadius(node.degree) + 3,
  }));
  const intersects = (
    a: { x: number; y: number; width: number; height: number },
    b: { x: number; y: number; width: number; height: number },
  ) =>
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y;
  for (const anchor of network.anchors) {
    const width = anchor.label.length * 11;
    const gap = anchor.radius + 18;
    const candidates = [
      { x: 0, y: gap },
      { x: 0, y: -gap + 4 },
      { x: -anchor.radius - width / 2 - 9, y: 4 },
      { x: anchor.radius + width / 2 + 9, y: 4 },
      { x: -width / 2, y: gap },
      { x: width / 2, y: -gap + 4 },
    ]
      .map((point, index) => {
        const box = {
          x: anchor.x + point.x - width / 2,
          y: anchor.y + point.y - 12,
          width,
          height: 16,
        };
        const score =
          index * 0.05 +
          labelBoxes.filter((other) =>
            intersects(box, {
              ...other,
              x: other.x - 5,
              width: other.width + 10,
              height: other.height + 3,
            }),
          ).length *
            10 +
          circles.filter((circle) =>
            intersects(box, {
              x: circle.x - circle.radius,
              y: circle.y - circle.radius,
              width: circle.radius * 2,
              height: circle.radius * 2,
            }),
          ).length *
            3 +
          (box.x < 12 || box.x + box.width > size.width - 12 ? 30 : 0);
        return { point, box, score };
      })
      .sort((a, b) => a.score - b.score);
    anchorLabels.set(anchor.id, candidates[0]!.point);
    labelBoxes.push(candidates[0]!.box);
  }
  const overviewLabels = new Set<string>();
  const nodeLabels = new Map<string, Point>();
  const labelBudget = view.zoom >= 1.6 ? 20 : size.width < 650 ? 4 : 9;
  const candidates = [...points.values()].sort(
    (a, b) =>
      b.degree - a.degree ||
      Number(b.representative) - Number(a.representative) ||
      a.id.length - b.id.length ||
      a.id.localeCompare(b.id),
  );
  for (const node of candidates) {
    if (overviewLabels.size >= labelBudget || view.zoom < 0.85) break;
    const width = Math.min(node.id.length, 12) * 10;
    const radius = nodeRadius(node.degree);
    const placement = [
      { x: 0, y: radius + 17 },
      { x: 0, y: -radius - 8 },
      { x: -radius - width / 2 - 6, y: 4 },
      { x: radius + width / 2 + 6, y: 4 },
    ]
      .map((point) => ({
        point,
        box: {
          x: node.x + point.x - width / 2,
          y: node.y + point.y - 11,
          width,
          height: 16,
        },
      }))
      .find(
        ({ box }) =>
          box.x >= 8 &&
          box.x + box.width <= size.width - 8 &&
          !labelBoxes.some((other) =>
            intersects(box, {
              ...other,
              x: other.x - 5,
              width: other.width + 10,
              height: other.height + 6,
            }),
          ) &&
          !circles.some((circle) =>
            intersects(box, {
              x: circle.x - circle.radius,
              y: circle.y - circle.radius,
              width: circle.radius * 2,
              height: circle.radius * 2,
            }),
          ),
      );
    if (!placement) continue;
    overviewLabels.add(node.id);
    nodeLabels.set(node.id, placement.point);
    labelBoxes.push(placement.box);
  }
  return (
    <section
      ref={section}
      className="knowledge-network knowledge-atlas"
      aria-label="知识关系网络"
    >
      <div className="knowledge-network-heading">
        <div>
          <span className="knowledge-section-index">知识图谱</span>
          <h2>让知识连成线</h2>
          <p>从一个概念出发，探索相连的知识与依据。</p>
        </div>
        <Select
          className="knowledge-network-search"
          classNames={{ popup: { root: "knowledge-network-search-popup" } }}
          aria-label="查找图中节点"
          placeholder="搜索图中节点"
          allowClear
          showSearch={{ optionFilterProp: "label" }}
          value={selected && points.has(selected) ? selected : undefined}
          options={network.nodes.map((node) => ({
            value: node.id,
            label: node.id,
          }))}
          onChange={(id: string | undefined) =>
            id ? locateNode(id) : onSelect(null)
          }
        />
      </div>
      <div className="knowledge-network-stage">
        <Space size={6} className="knowledge-network-controls">
          <Button
            aria-label="缩小知识网络"
            icon={<MinusOutlined />}
            disabled={view.zoom <= 0.55}
            onClick={() =>
              setView((current) =>
                zoomViewport(current, 1 / 1.2, {
                  x: size.width / 2,
                  y: size.height / 2,
                }),
              )
            }
          />
          <output
            className="knowledge-network-scale"
            aria-label="知识网络缩放比例"
          >
            {Math.round(view.zoom * 100)}%
          </output>
          <Button
            aria-label="放大知识网络"
            icon={<PlusOutlined />}
            disabled={view.zoom >= 3.5}
            onClick={() =>
              setView((current) =>
                zoomViewport(current, 1.2, {
                  x: size.width / 2,
                  y: size.height / 2,
                }),
              )
            }
          />
          <Button
            aria-label="重置知识网络"
            icon={<ReloadOutlined />}
            onClick={reset}
          >
            适应屏幕
          </Button>
        </Space>
        {network.nodes.length ? (
          <svg
            ref={svg}
            className={`knowledge-network-svg ${view.zoom < 0.8 ? "is-zoomed-out" : ""}`}
            viewBox={`0 0 ${size.width} ${size.height}`}
            aria-label="可交互知识图谱"
            onPointerDown={(event) => {
              if (
                event.target === canvas.current ||
                event.target === svg.current ||
                (event.target as Element).classList.contains(
                  "knowledge-network-decoration",
                )
              )
                startDrag(null, event);
            }}
            onPointerMove={(event) => {
              const start = drag.current;
              if (start?.pointer !== event.pointerId) return;
              if (
                Math.hypot(
                  event.clientX - start.client.x,
                  event.clientY - start.client.y,
                ) > 4
              )
                start.moved = true;
              if (!start.moved) return;
              const point = localPoint(event.clientX, event.clientY);
              const delta = {
                x: point.x - start.start.x,
                y: point.y - start.start.y,
              };
              if (start.id === null)
                setView({
                  ...start.view,
                  x: start.view.x + delta.x,
                  y: start.view.y + delta.y,
                });
              else
                setPositions((current) => ({
                  ...current,
                  [start.id!]: {
                    x: start.position.x + delta.x / start.view.zoom,
                    y: start.position.y + delta.y / start.view.zoom,
                  },
                }));
            }}
            onPointerUp={(event) => {
              const start = drag.current;
              if (start?.pointer !== event.pointerId) return;
              if (!start.moved) {
                if (start.id) selectNode(start.id);
                else
                  showFeedback(
                    "canvas",
                    coordinate(event.clientX, event.clientY),
                    16,
                  );
              }
              drag.current = null;
              if (svg.current?.hasPointerCapture(event.pointerId))
                svg.current.releasePointerCapture(event.pointerId);
            }}
            onPointerCancel={(event) => {
              if (drag.current?.pointer === event.pointerId)
                drag.current = null;
            }}
            onLostPointerCapture={(event) => {
              if (drag.current?.pointer === event.pointerId)
                drag.current = null;
            }}
          >
            <defs>
              <pattern
                id="knowledge-grid"
                width="28"
                height="28"
                patternUnits="userSpaceOnUse"
              >
                <circle
                  cx="1"
                  cy="1"
                  r="0.65"
                  fill="#72a0b0"
                  fillOpacity="0.2"
                />
              </pattern>
            </defs>
            <rect
              ref={canvas}
              className="knowledge-network-canvas"
              width={size.width}
              height={size.height}
              fill="url(#knowledge-grid)"
            />
            <g
              className="knowledge-network-viewport"
              transform={`translate(${view.x} ${view.y}) scale(${view.zoom})`}
            >
              {network.navigation.map((link) => {
                const from = allPoints.get(link.from)!,
                  to = allPoints.get(link.to)!;
                return (
                  <path
                    key={`${link.from}:${link.to}`}
                    className={`knowledge-navigation-link ${selected ? "is-muted" : ""} is-${link.kind}`}
                    d={relationPath(from, to)}
                  >
                    <title>领域归属导航</title>
                  </path>
                );
              })}
              {network.edges.map((entry) => {
                const from = points.get(entry.subject)!,
                  to = points.get(entry.object)!;
                const active =
                  !selected || selected === from.id || selected === to.id;
                const path = relationPath(from, to, pairLanes.get(entry.id));
                return (
                  <g
                    key={entry.id}
                    className={`knowledge-network-edge ${active ? "" : "is-muted"} ${selectedEdge === entry.id ? "is-selected" : ""} ${selected && active ? "is-focused" : ""}`}
                    role="button"
                    tabIndex={0}
                    aria-label={`查看关系：${entry.title}`}
                    aria-pressed={selectedEdge === entry.id}
                    onClick={() => openRelation(entry)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openRelation(entry);
                      }
                    }}
                  >
                    <path className="knowledge-edge-hit" d={path} />
                    <path className="knowledge-edge-line" d={path} />
                    <text
                      x={(from.x + to.x) / 2}
                      y={(from.y + to.y) / 2 - 8}
                      textAnchor="middle"
                    >
                      {entry.predicate.length > 12
                        ? `${entry.predicate.slice(0, 11)}…`
                        : entry.predicate}
                    </text>
                    <title>{`${entry.subject} → ${entry.predicate} → ${entry.object}`}</title>
                  </g>
                );
              })}
              {[...points.values()].map((node) => {
                const active = selected === node.id || hovered === node.id;
                const labeled =
                  active ||
                  neighbors.has(node.id) ||
                  overviewLabels.has(node.id);
                return (
                  <g
                    key={node.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`筛选节点：${node.id}`}
                    aria-pressed={selected === node.id}
                    className={`knowledge-network-node ${selected === node.id ? "is-selected" : ""} ${labeled ? "is-labeled" : ""} ${selected && !active && !neighbors.has(node.id) ? "is-muted" : ""}`}
                    transform={`translate(${node.x} ${node.y})`}
                    onPointerDown={(event) => startDrag(node.id, event)}
                    onPointerEnter={() => setHovered(node.id)}
                    onPointerLeave={() => setHovered(null)}
                    onFocus={() => setHovered(node.id)}
                    onBlur={() => setHovered(null)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectNode(node.id);
                      }
                      const shift: Record<string, [number, number]> = {
                        ArrowLeft: [-14, 0],
                        ArrowRight: [14, 0],
                        ArrowUp: [0, -14],
                        ArrowDown: [0, 14],
                      };
                      const delta = shift[event.key];
                      if (delta) {
                        event.preventDefault();
                        setPositions((current) => ({
                          ...current,
                          [node.id]: {
                            x: node.x + delta[0],
                            y: node.y + delta[1],
                          },
                        }));
                      }
                    }}
                  >
                    <circle
                      className="knowledge-node-halo"
                      r={nodeRadius(node.degree) + 8}
                    />
                    <circle r={nodeRadius(node.degree)} fill={node.color} />
                    <text
                      x={nodeLabels.get(node.id)?.x ?? 0}
                      y={
                        nodeLabels.get(node.id)?.y ??
                        nodeRadius(node.degree) + 17
                      }
                      textAnchor="middle"
                    >
                      {node.id.length > (active ? 24 : 12)
                        ? `${node.id.slice(0, active ? 23 : 11)}…`
                        : node.id}
                    </text>
                    <title>
                      {node.id} / {node.category} / {node.degree} 条关系。Enter
                      筛选，方向键移动。
                    </title>
                  </g>
                );
              })}
              {network.anchors.map((anchor) => {
                const domain = network.domains.find(
                  (item) => item.id === anchor.domain,
                );
                const fullLabel = domain?.label ?? anchor.label;
                const activate = () => {
                  showFeedback("node", anchor, anchor.radius + 12);
                  onSelect(null);
                  if (anchor.domain === null) onDomainSelect?.(undefined);
                  else if (anchor.domain !== "unclassified")
                    onDomainSelect?.(anchor.domain as KnowledgeDomain);
                };
                return (
                  <g
                    key={anchor.id}
                    className={`knowledge-network-anchor ${anchor.domain === null ? "is-root" : ""} ${selected ? "is-muted" : ""}`}
                    transform={`translate(${anchor.x} ${anchor.y})`}
                    role="button"
                    tabIndex={0}
                    aria-label={
                      anchor.domain === null
                        ? "查看全部知识"
                        : `聚焦知识分区：${fullLabel}`
                    }
                    onClick={activate}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        activate();
                      }
                    }}
                  >
                    <circle
                      className="knowledge-anchor-halo"
                      r={anchor.radius + 6}
                      fill={`${anchor.color}0b`}
                      stroke={`${anchor.color}35`}
                    />
                    <circle r={anchor.radius} fill={anchor.color} />
                    <text
                      x={anchorLabels.get(anchor.id)!.x}
                      y={anchorLabels.get(anchor.id)!.y}
                      textAnchor="middle"
                    >
                      {anchor.label}
                    </text>
                    <title>{fullLabel} / 领域导航</title>
                  </g>
                );
              })}
              {feedback && (
                <g
                  key={feedback.key}
                  className={`knowledge-network-feedback is-${feedback.kind}`}
                  transform={`translate(${feedback.x} ${feedback.y})`}
                  aria-hidden="true"
                >
                  <circle
                    className="knowledge-click-inner"
                    r={feedback.radius}
                  />
                  <circle
                    className="knowledge-click-outer"
                    r={feedback.radius + 6}
                  />
                </g>
              )}
            </g>
          </svg>
        ) : (
          <Empty description="当前检索范围没有可展示的知识关系" />
        )}
      </div>
      <footer className="knowledge-network-legend">
        <div>
          <span>
            <i className="knowledge-line-key" />
            知识关系
          </span>
          <span>
            <i className="knowledge-line-key is-navigation" />
            领域归属
          </span>
        </div>
        <small>
          {network.nodes.length} 个节点 / {network.edges.length} /{" "}
          {entries.length} 条关系
          {summary.length < entries.length ? " / 点击领域查看更多" : ""}
        </small>
      </footer>
      {selected && (
        <div className="knowledge-network-selection">
          <span>
            正在查看 <strong>{selected}</strong> 的关联知识
          </span>
          <Button size="small" type="text" onClick={() => onSelect(null)}>
            清除筛选
          </Button>
        </div>
      )}
    </section>
  );
}
