import type { GeoJsonGeometry } from "../api/generated/types.gen";

export type ReviewViewport = {
  x: number;
  y: number;
  width: number;
  height: number;
};
type Position = [number, number];

export function projectReviewPosition(position: number[]): Position {
  const latitude = Math.max(-85.051129, Math.min(85.051129, position[1]!));
  return [
    position[0]! * 1000,
    (-Math.log(Math.tan(Math.PI / 4 + (latitude * Math.PI) / 360)) * 180000) /
      Math.PI,
  ];
}

export function reviewViewport(
  bounds: [number, number, number, number],
): ReviewViewport {
  const [west, north] = projectReviewPosition([bounds[0], bounds[3]]);
  const [east, south] = projectReviewPosition([bounds[2], bounds[1]]);
  const width = Math.max(east - west, 0.01);
  const height = Math.max(south - north, 0.01);
  return {
    x: west - width * 0.08,
    y: north - height * 0.08,
    width: width * 1.16,
    height: height * 1.16,
  };
}

export function reviewGeometry(geometry: GeoJsonGeometry): {
  path: string;
  points: Position[];
  polygon: boolean;
} {
  const line = (coordinates: number[][], close = false) =>
    coordinates
      .map(
        (position, index) =>
          `${index ? "L" : "M"}${projectReviewPosition(position).join(",")}`,
      )
      .join(" ") + (close ? " Z" : "");
  switch (geometry.type) {
    case "Point":
      return {
        path: "",
        points: [projectReviewPosition(geometry.coordinates as number[])],
        polygon: false,
      };
    case "MultiPoint":
      return {
        path: "",
        points: (geometry.coordinates as number[][]).map(projectReviewPosition),
        polygon: false,
      };
    case "LineString":
      return {
        path: line(geometry.coordinates as number[][]),
        points: [],
        polygon: false,
      };
    case "MultiLineString":
      return {
        path: (geometry.coordinates as number[][][])
          .map((coordinates) => line(coordinates))
          .join(" "),
        points: [],
        polygon: false,
      };
    case "Polygon":
      return {
        path: (geometry.coordinates as number[][][])
          .map((coordinates) => line(coordinates, true))
          .join(" "),
        points: [],
        polygon: true,
      };
    case "MultiPolygon":
      return {
        path: (geometry.coordinates as number[][][][])
          .flatMap((polygon) =>
            polygon.map((coordinates) => line(coordinates, true)),
          )
          .join(" "),
        points: [],
        polygon: true,
      };
  }
}

export function zoomReviewViewport(
  view: ReviewViewport,
  factor: number,
  anchor: Position = [view.x + view.width / 2, view.y + view.height / 2],
): ReviewViewport {
  const span = Math.max(view.width, view.height);
  const scale = Math.max(0.01 / span, Math.min(360000 / span, factor));
  return {
    x: anchor[0] + (view.x - anchor[0]) * scale,
    y: anchor[1] + (view.y - anchor[1]) * scale,
    width: view.width * scale,
    height: view.height * scale,
  };
}
