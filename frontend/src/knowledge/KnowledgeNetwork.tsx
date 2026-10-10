import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Space } from "antd";
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
  onDomainSelect?: (domain: KnowledgeDomain) => void;
}) {
  const section = useRef<HTMLElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const canvas = useRef<SVGRectElement>(null);
  const [size, setSize] = useState({ width: 1100, height: 520 });
  const summary = useMemo(
    () => networkSummary(entries, selected),
    [entries, selected],
  );
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
      const height = width < 650 ? 500 : 520;
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
    const timer = window.setTimeout(() => setFeedback(null), 640);
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
    showFeedback("node", node, nodeRadius(node.degree) + 9);
    onSelect(selected === id ? null : id);
  }
  function openRelation(entry: KnowledgeEntry) {
    const from = points.get(entry.subject)!,
      to = points.get(entry.object)!;
    showFeedback(
      "edge",
      { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 },
      13,
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
  return (
    <section
      ref={section}
      className="knowledge-network"
      aria-label="知识关系网络"
    >
      <div className="knowledge-network-heading">
        <div>
          <span className="knowledge-section-index">01 / KNOWLEDGE ATLAS</span>
          <h2>让知识连成线</h2>
          <p>按领域聚焦知识，点击连线阅读依据。滚轮缩放，拖动空白处移动。</p>
        </div>
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
            适应画布
          </Button>
        </Space>
      </div>
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
                "knowledge-network-region-boundary",
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
            if (drag.current?.pointer === event.pointerId) drag.current = null;
          }}
          onLostPointerCapture={(event) => {
            if (drag.current?.pointer === event.pointerId) drag.current = null;
          }}
        >
          <defs>
            <pattern
              id="knowledge-grid"
              width="28"
              height="28"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="0.8" fill="#274861" />
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
            {network.regions.map((region) => (
              <g key={region.id} className="knowledge-network-region">
                <rect
                  className="knowledge-network-region-boundary"
                  x={region.x}
                  y={region.y}
                  width={region.width}
                  height={region.height}
                  rx="18"
                  style={{
                    fill: `${region.color}06`,
                    stroke: `${region.color}35`,
                  }}
                />
                <g
                  className="knowledge-network-region-heading"
                  role={
                    onDomainSelect && region.id !== "unclassified"
                      ? "button"
                      : undefined
                  }
                  tabIndex={
                    onDomainSelect && region.id !== "unclassified"
                      ? 0
                      : undefined
                  }
                  aria-label={`聚焦知识分区：${region.label}`}
                  onClick={() => {
                    if (region.id !== "unclassified")
                      onDomainSelect?.(region.id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      if (region.id !== "unclassified")
                        onDomainSelect?.(region.id);
                    }
                  }}
                >
                  <circle
                    cx={region.x + 17}
                    cy={region.y + 23}
                    r="3"
                    fill={region.color}
                  />
                  <text x={region.x + 28} y={region.y + 27} fill={region.color}>
                    {size.width < 650 && region.label.length > 9
                      ? `${region.label.slice(0, 8)}…`
                      : region.label}
                  </text>
                  <title>{region.label} · 点击聚焦分区</title>
                </g>
              </g>
            ))}
            {network.edges.map((entry) => {
              const from = points.get(entry.subject)!,
                to = points.get(entry.object)!;
              const active =
                !selected || selected === from.id || selected === to.id;
              const path = relationPath(from, to, pairLanes.get(entry.id));
              return (
                <g
                  key={entry.id}
                  className={`knowledge-network-edge ${active ? "" : "is-muted"} ${selectedEdge === entry.id ? "is-selected" : ""} ${from.domain !== to.domain ? "is-cross-domain" : ""}`}
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
                (view.zoom >= 0.85 && node.primary) ||
                (view.zoom >= 1.6 && node.representative);
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
                  <text y={nodeRadius(node.degree) + 18} textAnchor="middle">
                    {node.id.length > (active ? 24 : 10)
                      ? `${node.id.slice(0, active ? 23 : 9)}…`
                      : node.id}
                  </text>
                  <title>
                    {node.id} · {node.degree} 条关系。Enter 筛选，方向键移动。
                  </title>
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
                <circle r={feedback.radius} />
              </g>
            )}
          </g>
        </svg>
      ) : (
        <Empty description="当前检索范围没有可展示的知识关系" />
      )}
      <footer className="knowledge-network-legend">
        <span>连线表示知识关系 · 分区边界表示领域归类</span>
        <small>
          {network.nodes.length} 个节点 · {network.edges.length} /{" "}
          {entries.length} 条关系
          {summary.length < entries.length ? "，聚焦分区查看更多" : ""}
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
