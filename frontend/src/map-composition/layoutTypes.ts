export type PaperPreset = "A4" | "A3";
export type PaperOrientation = "landscape" | "portrait";
export type CompositionGridType = "geographic" | "projected";
export type MapBounds = [number, number, number, number];

export interface LayoutBox {
  xMm: number;
  yMm: number;
  widthMm: number;
  heightMm: number;
}

export interface TextElement extends LayoutBox {
  enabled: boolean;
  text: string;
  fontSizePt: number;
  color: string;
  align: "left" | "center" | "right";
}

export interface MapCompositionLayout {
  basemapId?: import("../map/basemapCatalog").BasemapId;
  [key: string]: unknown;
  version: 1;
  editor: { order: string[]; locked: string[] };
  extraTexts: (TextElement & { id: string })[];
  page: {
    preset: PaperPreset;
    orientation: PaperOrientation;
    widthMm: number;
    heightMm: number;
    dpi: number;
    backgroundColor: string;
  };
  mapFrame: LayoutBox & {
    bounds: MapBounds;
    borderColor: string;
    borderWidthPt: number;
  };
  title: TextElement;
  subtitle: TextElement;
  legend: LayoutBox & {
    enabled: boolean;
    title: string;
    columns: number;
    fontSizePt: number;
    backgroundColor: string;
    borderColor: string;
  };
  northArrow: LayoutBox & { enabled: boolean };
  scaleBar: LayoutBox & { enabled: boolean; color: string };
  overview: LayoutBox & {
    enabled: boolean;
    bounds: MapBounds;
    borderColor: string;
  };
  grid: {
    enabled: boolean;
    type: CompositionGridType;
    interval: number;
    color: string;
    labelColor: string;
    fontSizePt: number;
  };
  source: TextElement;
  note: TextElement;
}

export const platformProjectBounds: MapBounds = [50, 35, 100, 48];
