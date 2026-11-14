export function globeFit(width: number, height: number) {
  const diameter = Math.max(120, Math.min(width * 0.86, height * 0.86));
  const zoom = Math.min(3.5, Math.log2((diameter * Math.PI) / 512));
  return { zoom, diameter: (512 * 2 ** zoom) / Math.PI };
}

export function isRegionalZoom(zoom: number, width: number, height: number) {
  return zoom > globeFit(width, height).zoom + 0.8;
}
