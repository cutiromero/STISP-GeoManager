import type { CompositionLegendItem } from "./legend";
import type { LayoutBox, MapCompositionLayout, TextElement } from "./layout";

export interface PixelBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function pixelBox(box: LayoutBox, pxPerMm: number): PixelBox {
  return {
    x: box.xMm * pxPerMm,
    y: box.yMm * pxPerMm,
    width: box.widthMm * pxPerMm,
    height: box.heightMm * pxPerMm,
  };
}

export function drawImageCover(
  context: CanvasRenderingContext2D,
  image: CanvasImageSource,
  box: PixelBox,
) {
  const width = "width" in image ? Number(image.width) : box.width;
  const height = "height" in image ? Number(image.height) : box.height;
  const scale = Math.max(box.width / width, box.height / height);
  const sourceWidth = box.width / scale;
  const sourceHeight = box.height / scale;
  const sourceX = (width - sourceWidth) / 2;
  const sourceY = (height - sourceHeight) / 2;
  context.drawImage(
    image,
    sourceX,
    sourceY,
    sourceWidth,
    sourceHeight,
    box.x,
    box.y,
    box.width,
    box.height,
  );
}

export function drawTextElement(
  context: CanvasRenderingContext2D,
  element: TextElement,
  pxPerMm: number,
) {
  if (!element.enabled || !element.text.trim()) return;
  const box = pixelBox(element, pxPerMm);
  context.save();
  context.fillStyle = element.color;
  context.font = `${pointsToPixels(element.fontSizePt, pxPerMm)}px "Microsoft YaHei", sans-serif`;
  context.textAlign = element.align;
  context.textBaseline = "top";
  const x =
    element.align === "center"
      ? box.x + box.width / 2
      : element.align === "right"
        ? box.x + box.width
        : box.x;
  drawWrappedText(context, element.text, x, box.y, box.width, box.height);
  context.restore();
}

export function drawLegend(
  context: CanvasRenderingContext2D,
  layout: MapCompositionLayout,
  items: CompositionLegendItem[],
  pxPerMm: number,
) {
  if (!layout.legend.enabled) return;
  const box = pixelBox(layout.legend, pxPerMm);
  context.save();
  context.fillStyle = layout.legend.backgroundColor;
  context.fillRect(box.x, box.y, box.width, box.height);
  context.strokeStyle = layout.legend.borderColor;
  context.lineWidth = Math.max(1, pxPerMm * 0.25);
  context.strokeRect(box.x, box.y, box.width, box.height);
  const padding = 3 * pxPerMm;
  const titleSize = pointsToPixels(layout.legend.fontSizePt + 2, pxPerMm);
  context.fillStyle = "#172a2d";
  context.font = `600 ${titleSize}px "Microsoft YaHei", sans-serif`;
  context.textBaseline = "top";
  context.fillText(layout.legend.title, box.x + padding, box.y + padding);
  const columns = Math.max(1, layout.legend.columns);
  const columnWidth = (box.width - padding * 2) / columns;
  const fontSize = pointsToPixels(layout.legend.fontSizePt, pxPerMm);
  const rowHeight = Math.max(fontSize * 1.45, 5 * pxPerMm);
  const startY = box.y + padding + titleSize * 1.45;
  const rows = Math.max(
    1,
    Math.floor((box.height - (startY - box.y) - padding) / rowHeight),
  );
  context.font = `${fontSize}px "Microsoft YaHei", sans-serif`;
  for (const [index, item] of items.slice(0, rows * columns).entries()) {
    const column = Math.floor(index / rows);
    const row = index % rows;
    const x = box.x + padding + column * columnWidth;
    const y = startY + row * rowHeight;
    drawLegendSymbol(context, item, x, y + rowHeight * 0.15, rowHeight * 0.65);
    context.fillStyle = "#273b3f";
    context.fillText(
      truncateText(context, item.label, columnWidth - rowHeight - pxPerMm),
      x + rowHeight,
      y,
    );
  }
  context.restore();
}

export function drawNorthArrow(
  context: CanvasRenderingContext2D,
  box: PixelBox,
) {
  context.save();
  const centerX = box.x + box.width / 2;
  context.fillStyle = "#102a2e";
  context.font = `700 ${box.height * 0.28}px Arial, sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "top";
  context.fillText("N", centerX, box.y);
  context.beginPath();
  context.moveTo(centerX, box.y + box.height * 0.25);
  context.lineTo(box.x + box.width * 0.78, box.y + box.height * 0.9);
  context.lineTo(centerX, box.y + box.height * 0.72);
  context.lineTo(box.x + box.width * 0.22, box.y + box.height * 0.9);
  context.closePath();
  context.fill();
  context.restore();
}

function drawLegendSymbol(
  context: CanvasRenderingContext2D,
  item: CompositionLegendItem,
  x: number,
  y: number,
  size: number,
) {
  context.fillStyle = item.color;
  context.strokeStyle = item.color;
  context.lineWidth = Math.max(2, size * 0.18);
  if (item.shape === "point") {
    context.beginPath();
    context.arc(x + size / 2, y + size / 2, size * 0.32, 0, Math.PI * 2);
    context.fill();
  } else if (item.shape === "line") {
    line(context, x, y + size / 2, x + size, y + size / 2);
  } else {
    context.fillRect(x, y, size, size * 0.72);
    context.strokeRect(x, y, size, size * 0.72);
  }
}

function drawWrappedText(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  maxHeight: number,
) {
  const lineHeight = parseFloat(context.font) * 1.35;
  let line = "";
  let currentY = y;
  for (const character of text) {
    const candidate = line + character;
    if (line && context.measureText(candidate).width > maxWidth) {
      context.fillText(line, x, currentY);
      currentY += lineHeight;
      if (currentY + lineHeight > y + maxHeight) return;
      line = character;
    } else {
      line = candidate;
    }
  }
  if (line) context.fillText(line, x, currentY);
}

function truncateText(
  context: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
) {
  if (context.measureText(text).width <= maxWidth) return text;
  let output = text;
  while (
    output.length > 1 &&
    context.measureText(`${output}…`).width > maxWidth
  ) {
    output = output.slice(0, -1);
  }
  return `${output}…`;
}

function pointsToPixels(points: number, pxPerMm: number) {
  return points * 0.352778 * pxPerMm;
}

function line(
  context: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
) {
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  context.stroke();
}
