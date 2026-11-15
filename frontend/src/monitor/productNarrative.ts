import type { MonitoringProduct } from "../api/generated/types.gen";

export const monitorTaskWritingGuidance =
  "交付说明先给主要结果，再说明观测时间、统计范围、单位和成果入口。只引用本次成功成果中的数值；区分实测、模型识别和待核验信息。已有有效预检与入库证据直接引用，输入或参数变化时重新核对。未启用人工审核且资料完整时直接继续，不为重复确认而等待。单期成果不推断变化趋势，模型概率不表述为准确率，历史野火观测不表述为实时预警。";

export function productNarrative(product: MonitoringProduct, english = false) {
  const metric = (key: string) =>
    product.metrics.find((row) => row.key === key)?.value;
  const number = (value: number | null | undefined, digits = 2) =>
    value == null || !Number.isFinite(value)
      ? undefined
      : value.toLocaleString(english ? "en-US" : "zh-CN", {
          maximumFractionDigits: digits,
        });
  const period = product.observedStart
    ? `${product.observedStart}${product.observedEnd && product.observedEnd !== product.observedStart ? ` — ${product.observedEnd}` : ""}`
    : english
      ? "Observation date pending verification"
      : "观测时间待核实";
  if (product.scene === "spartina") {
    const area = number(metric("area_ha"));
    const share = number(metric("coverage_percent"));
    const patches = number(metric("patch_count"), 0);
    return {
      summary:
        area === undefined
          ? product.interpretation
          : english
            ? `${period}: mapped Spartina area ${area} ha${share === undefined ? "" : ` (${share}% of the valid area)`}${patches === undefined ? "" : `, ${patches} patches`}.`
            : `${period}，互花米草分布面积 ${area} ha${share === undefined ? "" : `，占有效统计区 ${share}%`}${patches === undefined ? "" : `，共 ${patches} 个斑块`}。`,
      advice: english
        ? "Inspect mapped boundaries using the source image overlay. Compare periods only when valid areas and methods agree."
        : "可叠加原图核查分布边界；多期比较需保持有效范围与识别口径一致。",
    };
  }
  if (product.scene === "wildfire" && product.observation) {
    const observation = product.observation;
    const quantity = number(
      metric(observation.unit === "ha" ? "burned_area_ha" : "frp_w_m2"),
      3,
    );
    const cells = number(observation.activeCells, 0);
    return {
      summary:
        quantity === undefined
          ? product.interpretation
          : english
            ? `${period}: ${observation.unit === "ha" ? "observed burned area" : "mean fire radiative power density"} ${quantity} ${observation.unit}${cells === undefined ? "" : `; ${cells} grid cells with positive observations`}.`
            : `${period}，${observation.unit === "ha" ? "观测火烧面积" : "平均火辐射功率密度"} ${quantity} ${observation.unit}${cells === undefined ? "" : `，${cells} 个格网有正观测值`}。`,
      advice: english
        ? "Historical observations describe the selected period. Check valid coverage and the regional series before comparing periods."
        : "这是所选时段的历史观测。比较前请核对有效覆盖率与区域序列；格网数量不等同于火点数量。",
    };
  }
  if (product.scene === "landcover" && product.classification) {
    const largest = [...product.classification.categories].sort(
      (a, b) => b.areaKm2 - a.areaKm2,
    )[0];
    const area = number(metric("valid_area_km2"), 3);
    return {
      summary:
        largest && area !== undefined
          ? english
            ? `Valid area ${area} km². ${largest.name} has the largest mapped share (${number(largest.percent)}%, ${number(largest.areaKm2, 3)} km²).`
            : `有效统计区 ${area} km²。已识别类别中，${largest.name}占比最高，为 ${number(largest.percent)}%（${number(largest.areaKm2, 3)} km²）。`
          : product.interpretation,
      advice: english
        ? "Inspect boundaries against the RGB image. Bare land is the valid area outside the five extracted classes."
        : "可结合原始 RGB 影像核查边界。裸地表示五类之外的有效剩余区，不作为独立裸土识别结论。",
    };
  }
  return { summary: product.interpretation, advice: undefined };
}
