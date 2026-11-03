/**
 * One rule for areas shown to users: square metres below a hectare (whole
 * numbers), hectares below a square kilometre, otherwise square kilometres.
 */
export function formatArea(squareMetres: number): string {
  const value = Math.abs(squareMetres);
  if (value < 10_000)
    return `${Math.round(squareMetres).toLocaleString("zh-CN")} 平方米`;
  if (value < 1_000_000)
    return `${(squareMetres / 10_000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 公顷`;
  return `${(squareMetres / 1_000_000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} km²`;
}
