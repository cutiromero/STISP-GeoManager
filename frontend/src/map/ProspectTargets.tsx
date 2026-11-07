import { AimOutlined } from "@ant-design/icons";
import { Button } from "antd";
import type {
  ComputeMapPreview,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";

type Feature = GeoJsonFeatureCollection["features"][number];
export default function ProspectTargets({
  data,
  active,
  onFocus,
  onObjectFocus,
  colorRamp,
  heatmapError,
}: {
  data: GeoJsonFeatureCollection;
  active: boolean;
  colorRamp?: ComputeMapPreview["metadata"]["colorRamp"];
  heatmapError?: string;
  onFocus: () => void;
  onObjectFocus?: (feature: Feature) => void;
}) {
  const area = data.features.reduce(
    (total, feature) => total + Number(feature.properties.area_km2),
    0,
  );
  return (
    <section
      className={`multi-tour-outcome${active ? " is-active" : ""}`}
      aria-label="修正后找矿远景区"
    >
      <div className="multi-tour-outcome-heading">
        <div>
          <span className="geology-review-eyebrow">修正后资料综合分析</span>
          <h2>优先核查的找矿目标</h2>
        </div>
        <Button
          icon={<AimOutlined />}
          disabled={!data.features.length}
          onClick={onFocus}
        >
          定位远景目标
        </Button>
      </div>
      <p>
        圈定 {data.features.length} 处，总面积
        {Number.isFinite(area)
          ? area.toLocaleString("zh-CN", { maximumFractionDigits: 3 })
          : "待核实"}
        平方公里。以构造与蚀变组合为主，结合岩性背景确定核查顺序。
      </p>
      {colorRamp?.length && data.features.length > 0 ? (
        <div
          className="prospect-confidence-legend"
          aria-label="远景相对置信度色带"
        >
          <span>相对置信度（证据支持度）</span>
          <i
            style={{
              background: `linear-gradient(to right, ${colorRamp.map((stop) => `${stop.color} ${stop.value * 100}%`).join(", ")})`,
            }}
          />
          <div>
            {colorRamp.map((stop) => (
              <span key={stop.value}>{stop.label}</span>
            ))}
          </div>
        </div>
      ) : null}
      {heatmapError && (
        <p role="status">
          热力图暂未加载：{heatmapError}。目标轮廓和依据仍可查看。
        </p>
      )}
      {!data.features.length && (
        <p>本次资料未形成符合圈区条件的目标，具体筛选结果见质量报告。</p>
      )}
      {data.features.map((feature) => (
        <details
          key={String(feature.properties.zone_id)}
          className="multi-tour-evidence"
        >
          <summary>
            {String(feature.properties.zone_id)} ·{" "}
            {Number(feature.properties.area_km2).toLocaleString("zh-CN", {
              maximumFractionDigits: 3,
            })}
            平方公里
            <Button
              type="link"
              size="small"
              onClick={(event) => {
                event.preventDefault();
                onObjectFocus?.(feature);
              }}
            >
              定位
            </Button>
          </summary>
          <p>
            {String(feature.properties.explanation ?? "详见每区实测依据表")}
          </p>
        </details>
      ))}
      <p>目标表示有依据的调查线索，需结合后续地质调查核查。</p>
    </section>
  );
}
