import { expect, it } from "vitest";
import { automaticReviewClusters } from "./automaticReviewClusters";
import { projectReviewPosition } from "./localReviewGeometry";

it("aggregates crowded automatic locations and preserves their counts", () => {
  const [x, y] = projectReviewPosition([96, 36]);
  const points = Array.from({ length: 196 }, (_, id) => ({
    id: String(id),
    coordinates: [96 + id * 0.000001, 36],
    count: 1,
  }));
  const result = automaticReviewClusters(
    points,
    { x: x - 1, y: y - 1, width: 10, height: 10 },
    600,
    400,
  );
  expect(result.length).toBeLessThan(10);
  expect(result.reduce((total, item) => total + item.count, 0)).toBe(196);
});
it("resolves nearby locations on zoom without fetching new data", () => {
  const [x, y] = projectReviewPosition([96, 36]);
  const points = [
    { id: "a", coordinates: [96, 36], count: 1 },
    { id: "b", coordinates: [96.001, 36], count: 2 },
  ];
  const wide = automaticReviewClusters(
    points,
    { x: x - 1, y: y - 1, width: 100, height: 100 },
    600,
    400,
  );
  const close = automaticReviewClusters(
    points,
    { x: x - 1, y: y - 1, width: 3, height: 3 },
    600,
    400,
  );
  expect(wide).toHaveLength(1);
  expect(close).toHaveLength(2);
  expect(close.reduce((total, item) => total + item.count, 0)).toBe(3);
});
