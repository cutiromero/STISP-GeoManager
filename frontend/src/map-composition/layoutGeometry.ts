import type {
  LayoutBox,
  MapCompositionLayout,
  PaperOrientation,
} from "./layoutTypes";

const PAGE_MARGIN_MM = 12;
const ELEMENT_GAP_MM = 7;

interface StandardCompositionBoxes {
  mapFrame: LayoutBox;
  title: LayoutBox;
  subtitle: LayoutBox;
  legend: LayoutBox;
  overview: LayoutBox;
  northArrow: LayoutBox;
  scaleBar: LayoutBox;
  source: LayoutBox;
  note: LayoutBox;
}

export function standardCompositionBoxes(
  widthMm: number,
  heightMm: number,
  orientation: PaperOrientation,
): StandardCompositionBoxes {
  const contentWidth = widthMm - PAGE_MARGIN_MM * 2;
  const footerY = heightMm - 16;
  const title = box(PAGE_MARGIN_MM, 7, contentWidth, 12);
  const subtitle = box(PAGE_MARGIN_MM, 19, contentWidth, 7);
  const footerGap = 7;
  const footerColumnWidth = (contentWidth - footerGap) / 2;
  const source = box(PAGE_MARGIN_MM, footerY, footerColumnWidth, 7);
  const note = box(
    PAGE_MARGIN_MM + footerColumnWidth + footerGap,
    footerY,
    footerColumnWidth,
    7,
  );

  if (orientation === "portrait") {
    const mapY = 30;
    const panelHeight = clamp(heightMm * 0.17, 50, 70);
    const panelY = footerY - 8 - panelHeight;
    const mapHeight = panelY - ELEMENT_GAP_MM - mapY;
    const overviewWidth = clamp(widthMm * 0.31, 62, 88);
    const legendWidth = contentWidth - ELEMENT_GAP_MM - overviewWidth;
    const mapFrame = box(PAGE_MARGIN_MM, mapY, contentWidth, mapHeight);
    return {
      mapFrame,
      title,
      subtitle,
      legend: box(PAGE_MARGIN_MM, panelY, legendWidth, panelHeight),
      overview: box(
        PAGE_MARGIN_MM + legendWidth + ELEMENT_GAP_MM,
        panelY,
        overviewWidth,
        panelHeight,
      ),
      northArrow: box(
        mapFrame.xMm + mapFrame.widthMm - 24,
        mapFrame.yMm + 8,
        18,
        22,
      ),
      scaleBar: box(
        mapFrame.xMm + 6,
        mapFrame.yMm + mapFrame.heightMm - 13,
        54,
        8,
      ),
      source,
      note,
    };
  }

  const mapY = 28;
  const mapBottom = footerY - 8;
  const mapHeight = mapBottom - mapY;
  const sidebarWidth = clamp(widthMm * 0.19, 56, 76);
  const mapWidth = contentWidth - ELEMENT_GAP_MM - sidebarWidth;
  const sidebarX = PAGE_MARGIN_MM + mapWidth + ELEMENT_GAP_MM;
  const legendHeight = clamp(mapHeight * 0.38, 56, 88);
  const overviewHeight = clamp(mapHeight * 0.24, 36, 54);
  const overviewY = mapY + legendHeight + ELEMENT_GAP_MM;
  const northArrowHeight = 22;
  const northArrowY = Math.min(
    overviewY + overviewHeight + ELEMENT_GAP_MM,
    mapY + mapHeight - northArrowHeight,
  );
  const mapFrame = box(PAGE_MARGIN_MM, mapY, mapWidth, mapHeight);
  return {
    mapFrame,
    title,
    subtitle,
    legend: box(sidebarX, mapY, sidebarWidth, legendHeight),
    overview: box(sidebarX, overviewY, sidebarWidth, overviewHeight),
    northArrow: box(
      sidebarX + (sidebarWidth - 18) / 2,
      northArrowY,
      18,
      northArrowHeight,
    ),
    scaleBar: box(
      mapFrame.xMm + 6,
      mapFrame.yMm + mapFrame.heightMm - 13,
      54,
      8,
    ),
    source,
    note,
  };
}

export function applyStandardGeometry(
  layout: MapCompositionLayout,
): MapCompositionLayout {
  const boxes = standardCompositionBoxes(
    layout.page.widthMm,
    layout.page.heightMm,
    layout.page.orientation,
  );
  return {
    ...layout,
    mapFrame: { ...layout.mapFrame, ...boxes.mapFrame },
    title: { ...layout.title, ...boxes.title },
    subtitle: { ...layout.subtitle, ...boxes.subtitle },
    legend: { ...layout.legend, ...boxes.legend },
    overview: { ...layout.overview, ...boxes.overview },
    northArrow: { ...layout.northArrow, ...boxes.northArrow },
    scaleBar: { ...layout.scaleBar, ...boxes.scaleBar },
    source: { ...layout.source, ...boxes.source },
    note: { ...layout.note, ...boxes.note },
  };
}

export function constrainCompositionLayout(
  layout: MapCompositionLayout,
): MapCompositionLayout {
  const pageWidth = Math.max(1, finite(layout.page.widthMm, 1));
  const pageHeight = Math.max(1, finite(layout.page.heightMm, 1));
  return {
    ...layout,
    mapFrame: fitBox(layout.mapFrame, pageWidth, pageHeight),
    title: fitBox(layout.title, pageWidth, pageHeight),
    subtitle: fitBox(layout.subtitle, pageWidth, pageHeight),
    legend: fitBox(layout.legend, pageWidth, pageHeight),
    overview: fitBox(layout.overview, pageWidth, pageHeight),
    northArrow: fitBox(layout.northArrow, pageWidth, pageHeight),
    scaleBar: fitBox(layout.scaleBar, pageWidth, pageHeight),
    source: fitBox(layout.source, pageWidth, pageHeight),
    note: fitBox(layout.note, pageWidth, pageHeight),
    extraTexts: layout.extraTexts.map((item) =>
      fitBox(item, pageWidth, pageHeight),
    ),
  };
}

export function layoutHasOutOfBoundsBoxes(layout: MapCompositionLayout) {
  return [
    layout.mapFrame,
    layout.title,
    layout.subtitle,
    layout.legend,
    layout.overview,
    layout.northArrow,
    layout.scaleBar,
    layout.source,
    layout.note,
  ].some((item) => !isBoxWithinPage(layout, item));
}

export function isBoxWithinPage(layout: MapCompositionLayout, item: LayoutBox) {
  return (
    Number.isFinite(item.xMm) &&
    Number.isFinite(item.yMm) &&
    Number.isFinite(item.widthMm) &&
    Number.isFinite(item.heightMm) &&
    item.xMm >= 0 &&
    item.yMm >= 0 &&
    item.widthMm > 0 &&
    item.heightMm > 0 &&
    item.xMm + item.widthMm <= layout.page.widthMm &&
    item.yMm + item.heightMm <= layout.page.heightMm
  );
}

function fitBox<T extends LayoutBox>(
  item: T,
  pageWidth: number,
  pageHeight: number,
): T {
  const widthMm = clamp(finite(item.widthMm, 1), 1, pageWidth);
  const heightMm = clamp(finite(item.heightMm, 1), 1, pageHeight);
  const xMm = clamp(finite(item.xMm, 0), 0, pageWidth - widthMm);
  const yMm = clamp(finite(item.yMm, 0), 0, pageHeight - heightMm);
  return { ...item, xMm, yMm, widthMm, heightMm };
}

function box(xMm: number, yMm: number, widthMm: number, heightMm: number) {
  return {
    xMm: roundMm(xMm),
    yMm: roundMm(yMm),
    widthMm: roundMm(widthMm),
    heightMm: roundMm(heightMm),
  };
}

function finite(value: number, fallback: number) {
  return Number.isFinite(value) ? value : fallback;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function roundMm(value: number) {
  return Math.round(value * 100) / 100;
}
