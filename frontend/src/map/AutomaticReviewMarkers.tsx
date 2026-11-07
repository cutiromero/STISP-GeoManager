import { useMemo } from "react";
import type { AgentAutomaticReviewMap } from "../api/generated/types.gen";
import type { ReviewViewport } from "./localReviewGeometry";
import { automaticReviewClusters } from "./automaticReviewClusters";

export default function AutomaticReviewMarkers({
  points,
  view,
  width,
  height,
}: {
  points: AgentAutomaticReviewMap["points"];
  view: ReviewViewport;
  width: number;
  height: number;
}) {
  const clusters = useMemo(
    () => automaticReviewClusters(points, view, width, height),
    [points, view, width, height],
  );
  return (
    <g
      data-layer="automatic-dispositions"
      className="automatic-review-markers"
      pointerEvents="none"
    >
      {clusters.map((point) => (
        <g key={point.id} data-automatic-count={point.count}>
          <circle
            cx={point.x}
            cy={point.y}
            r={point.radius}
            fill="#70867d"
            fillOpacity={point.count > 1 ? 0.25 : 0.45}
            stroke="#ffffff"
            strokeOpacity={0.65}
            strokeWidth={0.8}
            vectorEffect="non-scaling-stroke"
          />
          {point.count > 1 && (
            <text
              x={point.x}
              y={point.y}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={point.fontSize}
              fill="#40564c"
            >
              {point.count}
            </text>
          )}
        </g>
      ))}
    </g>
  );
}
