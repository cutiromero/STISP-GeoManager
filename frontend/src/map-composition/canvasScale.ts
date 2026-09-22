import type { MapBounds } from "./layout";
import type { PixelBox } from "./canvasElements";

export function drawScaleBar(
  context: CanvasRenderingContext2D,
  box: PixelBox,
  bounds: MapBounds,
  color: string,
  mapWidth: number,
) {
  const { distance, width } = scaleBarMetrics(bounds, mapWidth, box.width);
  const segmentWidth = width / 4;
  const barHeight = box.height * 0.34;
  context.save();
  context.strokeStyle = color;
  context.lineWidth = Math.max(1, box.height * 0.06);
  for (let index = 0; index < 4; index += 1) {
    context.fillStyle = index % 2 === 0 ? color : "#ffffff";
    context.fillRect(
      box.x + segmentWidth * index,
      box.y,
      segmentWidth,
      barHeight,
    );
    context.strokeRect(
      box.x + segmentWidth * index,
      box.y,
      segmentWidth,
      barHeight,
    );
  }
  context.fillStyle = color;
  context.font = `${box.height * 0.38}px "Microsoft YaHei", sans-serif`;
  context.textAlign = "left";
  context.textBaseline = "bottom";
  context.fillText(formatDistance(distance), box.x, box.y + box.height);
  context.restore();
}

/** Local scale at the Mercator map centre. Resizing the bar cannot change map scale. */
export function scaleBarMetrics(
  bounds: MapBounds,
  mapWidth: number,
  maxWidth: number,
) {
  const mercator = (latitude: number) =>
    Math.asinh(Math.tan((latitude * Math.PI) / 180));
  const centerLat = Math.atan(
    Math.sinh((mercator(bounds[1]) + mercator(bounds[3])) / 2),
  );
  const metersPerPixel =
    (((Math.abs(bounds[2] - bounds[0]) * Math.PI) / 180) *
      6378137 *
      Math.cos(centerLat)) /
    mapWidth;
  if (!(metersPerPixel > 0) || !(maxWidth > 0))
    throw new Error("Invalid scale extent");
  const distance = niceDistance(metersPerPixel * maxWidth);
  return { distance, width: distance / metersPerPixel, metersPerPixel };
}

function niceDistance(value: number) {
  const power = 10 ** Math.floor(Math.log10(value));
  const normalized = value / power;
  const factor = normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1;
  return factor * power;
}

function formatDistance(meters: number) {
  return meters >= 1000
    ? `${Number((meters / 1000).toFixed(3))} 千米`
    : `${Math.round(meters)} 米`;
}
