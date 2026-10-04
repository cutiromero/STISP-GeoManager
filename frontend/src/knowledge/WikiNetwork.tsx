import { useMemo, useState } from "react";
import { Button } from "antd";
import type { KnowledgeWikiPage } from "../api/generated/types.gen";

export default function WikiNetwork({
  pages,
  onOpen,
}: {
  pages: KnowledgeWikiPage[];
  onOpen: (page: KnowledgeWikiPage) => void;
}) {
  const [paused, setPaused] = useState(false);
  const points = useMemo(() => {
    const importance = (page: KnowledgeWikiPage) =>
      page.links.length +
      pages.filter((item) => item.links.includes(page.id)).length;
    const shown = [...pages]
      .sort((a, b) => importance(b) - importance(a) || a.id.localeCompare(b.id))
      .slice(0, 18);
    const columns = Math.min(shown.length, 6);
    const rows = Math.ceil(shown.length / columns);
    return shown.map((page, i) => ({
      page,
      x:
        100 +
        (i % columns) * (880 / Math.max(columns - 1, 1)) +
        Math.sin(i * 3) * 12,
      y:
        85 +
        Math.floor(i / columns) * (275 / Math.max(rows - 1, 1)) +
        Math.cos(i * 2) * 18,
    }));
  }, [pages]);
  if (!points.length) return null;
  return (
    <div
      className={`knowledge-network knowledge-wiki-network ${paused ? "is-paused" : ""}`}
    >
      <div className="knowledge-network-heading">
        <div>
          <span className="knowledge-section-index">主题之间的联系</span>
          <h2>沿着知识继续探索</h2>
          <p>点击主题球阅读内容。连线来自资料整理出的主题引用。</p>
        </div>
        <Button onClick={() => setPaused(!paused)}>
          {paused ? "启用浮动" : "暂停浮动"}
        </Button>
      </div>
      <svg
        className="knowledge-network-svg"
        viewBox="0 0 1080 460"
        aria-label="Wiki 主题关联网络"
      >
        <defs>
          <radialGradient id="wiki-orb">
            <stop offset="0" stopColor="#69bdc2" />
            <stop offset="1" stopColor="#246275" />
          </radialGradient>
        </defs>
        {points.flatMap((point) =>
          point.page.links.map((id) => {
            const target = points.find((item) => item.page.id === id);
            return target ? (
              <line
                key={`${point.page.id}:${id}`}
                x1={point.x}
                y1={point.y}
                x2={target.x}
                y2={target.y}
                stroke="#4e929d"
                strokeOpacity="0.3"
              />
            ) : null;
          }),
        )}
        {points.map(({ page, x, y }, i) => (
          <g
            key={page.id}
            role="button"
            tabIndex={0}
            aria-label={`阅读主题：${page.title}`}
            onClick={() => onOpen(page)}
            onKeyDown={(event) => {
              if (["Enter", " "].includes(event.key)) {
                event.preventDefault();
                onOpen(page);
              }
            }}
            className="knowledge-wiki-node"
            style={{ animationDelay: `${-i * 0.5}s` }}
          >
            <circle
              cx={x}
              cy={y}
              r={17 + Math.min(page.links.length, 8)}
              fill="url(#wiki-orb)"
              stroke="#8bcbd0"
              strokeWidth="1.5"
            />
            <circle
              cx={x}
              cy={y}
              r={28 + Math.min(page.links.length, 8)}
              fill="none"
              stroke="#6ab2bf"
              strokeOpacity="0.12"
            />
            <text
              x={x}
              y={y + 45}
              textAnchor="middle"
              fill="#e3f3f3"
              fontSize="13"
            >
              {page.title.length > 12
                ? `${page.title.slice(0, 11)}…`
                : page.title}
            </text>
            <title>{page.title}</title>
          </g>
        ))}
      </svg>
      {pages.length > 18 && (
        <p className="knowledge-wiki-network-note">
          图中展示关联较多的 18 个主题，全部主题可在下方阅读。
        </p>
      )}
    </div>
  );
}
