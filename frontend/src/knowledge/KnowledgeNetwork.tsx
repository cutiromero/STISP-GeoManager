import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Space } from "antd";
import {
  MinusOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { KnowledgeEntry } from "../api/generated/types.gen";
import { buildNetwork, networkColors } from "./network";

export default function KnowledgeNetwork({
  entries,
  selected,
  onSelect,
  onOpen,
}: {
  entries: KnowledgeEntry[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  onOpen: (entry: KnowledgeEntry) => void;
}) {
  const network = useMemo(() => buildNetwork(entries), [entries]);
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});
  const [paused, setPaused] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [zoom, setZoom] = useState(1);
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null);
  const [time, setTime] = useState(0);
  const [feedback, setFeedback] = useState<{
    key: number;
    kind: "node" | "edge" | "canvas";
    x: number;
    y: number;
    radius: number;
  } | null>(null);
  const feedbackSequence = useRef(0);
  const svg = useRef<SVGSVGElement>(null);
  const canvas = useRef<SVGRectElement>(null);
  const drag = useRef<{
    id: string | null;
    pointer: number;
    x: number;
    y: number;
    moved: boolean;
  } | null>(null);
  useEffect(() => {
    setPositions({});
    setZoom(1);
    setSelectedEdge(null);
    setFeedback(null);
  }, [network]);
  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(null), 640);
    return () => window.clearTimeout(timer);
  }, [feedback]);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      if (preference.matches) setPaused(true);
    };
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (paused) return;
    let frame = 0;
    let previous = 0;
    const animate = (stamp: number) => {
      if (stamp - previous > 45) {
        setTime(stamp / 1700);
        previous = stamp;
      }
      frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [paused]);
  const points = new Map(
    network.nodes.map((node, index) => {
      const base = positions[node.id] ?? node;
      return [
        node.id,
        {
          ...node,
          x: base.x + Math.sin(time + index) * 3,
          y: base.y + Math.cos(time * 0.8 + index) * 3,
        },
      ];
    }),
  );
  function coordinate(clientX: number, clientY: number) {
    const transform = svg.current?.getScreenCTM();
    if (!transform) return { x: 550, y: 250 };
    const local = new DOMPoint(clientX, clientY).matrixTransform(
      transform.inverse(),
    );
    return { x: (local.x - 550) / zoom + 550, y: (local.y - 250) / zoom + 250 };
  }
  function showFeedback(
    kind: "node" | "edge" | "canvas",
    point: { x: number; y: number },
    radius: number,
  ) {
    setFeedback({
      key: ++feedbackSequence.current,
      kind,
      x: point.x,
      y: point.y,
      radius,
    });
  }
  return (
    <section className="knowledge-network" aria-label="知识关系网络">
      <div className="knowledge-network-heading">
        <div>
          <span className="knowledge-section-index">01 / RELATIONS</span>
          <h2>让知识连成线</h2>
          <p>点击节点筛选知识，点击关系查看依据。拖动节点调整位置。</p>
        </div>
        <Space size={6}>
          <Button
            aria-label="缩小知识网络"
            icon={<MinusOutlined />}
            onClick={() => setZoom((value) => Math.max(0.65, value - 0.15))}
          />
          <Button
            aria-label="放大知识网络"
            icon={<PlusOutlined />}
            onClick={() => setZoom((value) => Math.min(1.9, value + 0.15))}
          />
          <Button
            icon={paused ? <PlayCircleOutlined /> : <PauseOutlined />}
            onClick={() => setPaused(!paused)}
          >
            {paused ? "启用浮动" : "暂停浮动"}
          </Button>
          <Button
            aria-label="重置知识网络"
            icon={<ReloadOutlined />}
            onClick={() => {
              setPositions({});
              setZoom(1);
              setSelectedEdge(null);
              setFeedback(null);
              onSelect(null);
            }}
          />
        </Space>
      </div>
      {network.nodes.length ? (
        <svg
          ref={svg}
          className="knowledge-network-svg"
          viewBox="0 0 1100 500"
          aria-label="可交互知识图谱"
          onPointerDown={(event) => {
            if (
              event.button !== 0 ||
              drag.current ||
              (event.target !== canvas.current && event.target !== svg.current)
            )
              return;
            drag.current = {
              id: null,
              pointer: event.pointerId,
              x: event.clientX,
              y: event.clientY,
              moved: false,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (drag.current?.pointer !== event.pointerId) return;
            if (
              Math.hypot(
                event.clientX - drag.current.x,
                event.clientY - drag.current.y,
              ) > 4
            )
              drag.current.moved = true;
            const id = drag.current.id;
            if (id === null || !drag.current.moved) return;
            const point = coordinate(event.clientX, event.clientY);
            setPositions((current) => ({
              ...current,
              [id]: point,
            }));
          }}
          onPointerUp={(event) => {
            const start = drag.current;
            if (start?.pointer !== event.pointerId) return;
            if (!start.moved) {
              const node = start.id === null ? null : points.get(start.id);
              if (node) {
                showFeedback("node", node, 25 + Math.min(node.degree, 5) * 2);
                onSelect(selected === node.id ? null : node.id);
              } else if (start.id === null) {
                showFeedback(
                  "canvas",
                  coordinate(event.clientX, event.clientY),
                  18,
                );
              }
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
              width="40"
              height="40"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="1" fill="#244657" />
            </pattern>
          </defs>
          <rect
            ref={canvas}
            className="knowledge-network-canvas"
            width="1100"
            height="500"
            fill="url(#knowledge-grid)"
          />
          <g
            transform={`translate(550 250) scale(${zoom}) translate(-550 -250)`}
          >
            {network.edges.map((entry) => {
              const from = points.get(entry.subject)!,
                to = points.get(entry.object)!;
              const active =
                !selected || selected === from.id || selected === to.id;
              return (
                <g
                  key={entry.id}
                  className={`knowledge-network-edge ${active ? "" : "is-muted"} ${selectedEdge === entry.id ? "is-selected" : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-label={`查看关系：${entry.title}`}
                  aria-pressed={selectedEdge === entry.id}
                  onClick={() => {
                    showFeedback(
                      "edge",
                      { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 },
                      15,
                    );
                    setSelectedEdge(entry.id);
                    onOpen(entry);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      showFeedback(
                        "edge",
                        { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 },
                        15,
                      );
                      setSelectedEdge(entry.id);
                      onOpen(entry);
                    }
                  }}
                >
                  <line
                    className="knowledge-edge-hit"
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                  />
                  <line
                    className="knowledge-edge-line"
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                  />
                  <text
                    x={(from.x + to.x) / 2}
                    y={(from.y + to.y) / 2 - 7}
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
            {[...points.values()].map((node) => (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`筛选节点：${node.id}`}
                aria-pressed={selected === node.id}
                className={`knowledge-network-node ${selected === node.id ? "is-selected" : ""}`}
                transform={`translate(${node.x} ${node.y})`}
                onPointerDown={(event) => {
                  if (event.button !== 0 || drag.current) return;
                  event.preventDefault();
                  setPaused(true);
                  drag.current = {
                    id: node.id,
                    pointer: event.pointerId,
                    x: event.clientX,
                    y: event.clientY,
                    moved: false,
                  };
                  svg.current?.setPointerCapture(event.pointerId);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    showFeedback(
                      "node",
                      node,
                      25 + Math.min(node.degree, 5) * 2,
                    );
                    onSelect(selected === node.id ? null : node.id);
                  }
                  const shift: Record<string, [number, number]> = {
                    ArrowLeft: [-14, 0],
                    ArrowRight: [14, 0],
                    ArrowUp: [0, -14],
                    ArrowDown: [0, 14],
                  };
                  if (shift[event.key]) {
                    event.preventDefault();
                    setPaused(true);
                    const delta = shift[event.key]!;
                    setPositions((current) => ({
                      ...current,
                      [node.id]: { x: node.x + delta[0], y: node.y + delta[1] },
                    }));
                  }
                }}
              >
                <circle
                  className="knowledge-node-halo"
                  r={25 + Math.min(node.degree, 5) * 2}
                />
                <circle
                  r={13 + Math.min(node.degree, 5) * 2}
                  fill={
                    networkColors[
                      network.categories.indexOf(node.category) %
                        networkColors.length
                    ]
                  }
                />
                <text y={39} textAnchor="middle">
                  {node.id.length > 14 ? `${node.id.slice(0, 13)}…` : node.id}
                </text>
                <title>
                  {node.id} · {node.degree} 条关系。Enter 筛选，方向键移动。
                </title>
              </g>
            ))}
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
        <div>
          {network.categories.map((category, index) => (
            <span key={category}>
              <i
                style={{
                  background: networkColors[index % networkColors.length],
                }}
              />
              {category}
            </span>
          ))}
        </div>
        <small>
          {network.nodes.length} 个节点 · {network.edges.length} 条关系
          {entries.length > 40 ? "（当前页前 40 条）" : ""}
        </small>
      </footer>
    </section>
  );
}
