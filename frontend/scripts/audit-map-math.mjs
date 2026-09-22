import { writeFile } from "node:fs/promises";
import { drawScaleBar } from "../src/map-composition/canvasScale.ts";

const results = [];
for (const width of [100, 200]) {
  let drawnWidth = 0;
  let label = "";
  const context = {
    save() {},
    restore() {},
    strokeRect() {},
    fillRect(_x, _y, w) {
      drawnWidth += w;
    },
    fillText(text) {
      label = text;
    },
  };
  drawScaleBar(
    context,
    { x: 0, y: 0, width, height: 20 },
    [0, -1, 4, 1],
    "#000000",
  );
  results.push({
    mapWidthPx: 1000,
    mapLongitudeSpanDegrees: 4,
    scaleBoxWidthPx: width,
    barWidthPx: drawnWidth,
    label,
    representedDistanceMetersAtEquator: (drawnWidth / 1000) * 4 * 111320,
  });
}
await writeFile(
  "../output/20260918-platform-audit/map-scale-probe.json",
  JSON.stringify(results, null, 2),
);
console.log(JSON.stringify(results));
