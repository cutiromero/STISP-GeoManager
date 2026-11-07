import type { AgentAutomaticReviewMap } from "../api/generated/types.gen";
import {
  projectReviewPosition,
  type ReviewViewport,
} from "./localReviewGeometry";

export function automaticReviewClusters(
  points: AgentAutomaticReviewMap["points"],
  view: ReviewViewport,
  width: number,
  height: number,
) {
  const scale = Math.min(width / view.width, height / view.height);
  const step = 44 / scale;
  const cells = new Map<
    string,
    { id: string; x: number; y: number; count: number }
  >();
  for (const point of points) {
    const [x, y] = projectReviewPosition(point.coordinates);
    if (
      x < view.x ||
      x > view.x + view.width ||
      y < view.y ||
      y > view.y + view.height
    )
      continue;
    const key = `${Math.floor((x - view.x) / step)}:${Math.floor((y - view.y) / step)}`;
    const cell = cells.get(key) ?? { id: key, x: 0, y: 0, count: 0 };
    cell.x += x * point.count;
    cell.y += y * point.count;
    cell.count += point.count;
    cells.set(key, cell);
  }
  return [...cells.values()].map((cell) => ({
    ...cell,
    x: cell.x / cell.count,
    y: cell.y / cell.count,
    radius: (cell.count > 1 ? 9 : 3) / scale,
    fontSize: 9 / scale,
  }));
}
