import { defaultUniqueValueClass } from "../symbolization";
import type { VectorSymbolization } from "../symbolization";

/** Agent maps may save a concise style; ordinary complete snapshots stay intact. */
export function restoreVectorStyle(
  base: VectorSymbolization,
  saved: Partial<VectorSymbolization>,
): VectorSymbolization {
  const renderer =
    saved.renderer?.type === "uniqueValue"
      ? {
          ...saved.renderer,
          classes: saved.renderer.classes.map((item) => ({
            ...defaultUniqueValueClass,
            ...item,
          })),
          defaultClass: {
            ...defaultUniqueValueClass,
            ...saved.renderer.defaultClass,
          },
        }
      : (saved.renderer ?? base.renderer);
  return {
    ...base,
    ...saved,
    renderer,
    circle: { ...base.circle, ...saved.circle },
    symbol: { ...base.symbol, ...saved.symbol },
    heatmap: { ...base.heatmap, ...saved.heatmap },
    cluster: { ...base.cluster, ...saved.cluster },
    line: { ...base.line, ...saved.line },
    fill: { ...base.fill, ...saved.fill },
  };
}
