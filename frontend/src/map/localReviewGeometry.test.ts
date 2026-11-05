import { expect, it } from "vitest";
import { beforeReviewMap } from "./geologyReview.testFixtures";
import {
  projectReviewPosition,
  reviewGeometry,
  reviewViewport,
  zoomReviewViewport,
} from "./localReviewGeometry";

it("projects longitude/latitude locally with finite polar coordinates", () => {
  expect(projectReviewPosition([0, 0])[0]).toBe(0);
  expect(projectReviewPosition([0, 0])[1]).toBeCloseTo(0);
  expect(projectReviewPosition([98, 36])[1]).toBeLessThan(
    projectReviewPosition([98, 35])[1],
  );
  expect(projectReviewPosition([0, 90]).every(Number.isFinite)).toBe(true);
});

it("preserves polygon holes and multipart geometries without external assets", () => {
  const polygon = reviewGeometry(beforeReviewMap.features[0]!.geometry);
  expect(polygon.polygon).toBe(true);
  expect(polygon.path.match(/M/g)).toHaveLength(2);
  expect(polygon.path.match(/Z/g)).toHaveLength(2);
  expect(
    reviewGeometry({
      type: "MultiPolygon",
      coordinates: [beforeReviewMap.features[0]!.geometry.coordinates],
    }).path,
  ).toBe(polygon.path);
  expect(
    reviewGeometry({
      type: "MultiLineString",
      coordinates: [
        [
          [0, 0],
          [1, 1],
        ],
        [
          [2, 2],
          [3, 3],
        ],
      ],
    }).path.match(/M/g),
  ).toHaveLength(2);
  expect(
    reviewGeometry({
      type: "LineString",
      coordinates: [
        [0, 0],
        [1, 1],
      ],
    }).polygon,
  ).toBe(false);
  expect(
    reviewGeometry({ type: "Point", coordinates: [98, 36] }).points,
  ).toEqual([projectReviewPosition([98, 36])]);
  expect(
    reviewGeometry({
      type: "MultiPoint",
      coordinates: [
        [98, 36],
        [99, 37],
      ],
    }).points,
  ).toHaveLength(2);
});

it("fits degenerate extents and zooms about the requested anchor", () => {
  const view = reviewViewport([98, 36, 98, 36]);
  expect(view.width).toBeGreaterThan(0);
  expect(view.height).toBeGreaterThan(0);
  const zoomed = zoomReviewViewport(
    { x: 10, y: 20, width: 100, height: 50 },
    0.5,
    [10, 20],
  );
  expect(zoomed).toEqual({ x: 10, y: 20, width: 50, height: 25 });
  expect(zoomReviewViewport(zoomed, 2, [10, 20])).toEqual({
    x: 10,
    y: 20,
    width: 100,
    height: 50,
  });
  expect(
    zoomReviewViewport({ x: 0, y: 0, width: 0.01, height: 100 }, 0.5).height,
  ).toBe(50);
});
