import { defaultCompositionLayout } from "./layout";
import {
  applyStandardGeometry,
  constrainCompositionLayout,
} from "./layoutGeometry";
import type {
  MapCompositionLayout,
  PaperOrientation,
  PaperPreset,
} from "./layoutTypes";

export function applyPaperPreset(
  current: MapCompositionLayout,
  preset: PaperPreset,
  orientation: PaperOrientation,
): MapCompositionLayout {
  const [baseWidth, baseHeight] = preset === "A3" ? [420, 297] : [297, 210];
  const widthMm = orientation === "landscape" ? baseWidth : baseHeight;
  const heightMm = orientation === "landscape" ? baseHeight : baseWidth;
  const next = defaultCompositionLayout(
    current.title.text,
    current.mapFrame.bounds,
    current.source.text,
  );
  next.page = { ...current.page, preset, orientation, widthMm, heightMm };
  next.mapFrame = {
    ...next.mapFrame,
    bounds: current.mapFrame.bounds,
    borderColor: current.mapFrame.borderColor,
    borderWidthPt: current.mapFrame.borderWidthPt,
  };
  next.title = preserveTextStyle(next.title, current.title);
  next.subtitle = preserveTextStyle(next.subtitle, current.subtitle);
  next.legend = {
    ...next.legend,
    enabled: current.legend.enabled,
    title: current.legend.title,
    columns: orientation === "portrait" ? 2 : current.legend.columns,
    fontSizePt: current.legend.fontSizePt,
    backgroundColor: current.legend.backgroundColor,
    borderColor: current.legend.borderColor,
  };
  next.overview = {
    ...next.overview,
    enabled: current.overview.enabled,
    bounds: current.overview.bounds,
    borderColor: current.overview.borderColor,
  };
  next.northArrow = {
    ...next.northArrow,
    enabled: current.northArrow.enabled,
  };
  next.scaleBar = {
    ...next.scaleBar,
    enabled: current.scaleBar.enabled,
    color: current.scaleBar.color,
  };
  next.grid = { ...current.grid };
  next.source = preserveTextStyle(next.source, current.source);
  next.note = preserveTextStyle(next.note, current.note);
  return constrainCompositionLayout(applyStandardGeometry(next));
}

export function restoreStandardCompositionLayout(
  current: MapCompositionLayout,
): MapCompositionLayout {
  const next = applyPaperPreset(
    current,
    current.page.preset,
    current.page.orientation,
  );
  return {
    ...next,
    page: { ...next.page, backgroundColor: "#ffffff" },
  };
}

function preserveTextStyle(
  standard: MapCompositionLayout["title"],
  current: MapCompositionLayout["title"],
) {
  return {
    ...standard,
    enabled: current.enabled,
    text: current.text,
    fontSizePt: current.fontSizePt,
    color: current.color,
    align: current.align,
  };
}
