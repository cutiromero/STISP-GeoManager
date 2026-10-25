import { AimOutlined } from "@ant-design/icons";
import { Button } from "antd";
import type { prospectChanges } from "./multiElementTour";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";

export default function MultiElementOutcome({
  result,
  active,
  onFocus,
  onObjectFocus,
}: {
  result: ReturnType<typeof prospectChanges>;
  active: boolean;
  onFocus: (grade?: string) => void;
  onObjectFocus?: (
    feature: GeoJsonFeatureCollection["features"][number],
  ) => void;
}) {
  const changed = result.before.features.length + result.after.features.length;
  return (
    <section
      className={`multi-tour-outcome${active ? " is-active" : ""}`}
      aria-label="调查建议变化"
    >
      <div className="multi-tour-outcome-heading">
        <div>
          <span className="geology-review-eyebrow">最后，回到调查决策</span>
          <h2>这些处理怎样改变调查建议</h2>
        </div>
        <Button
          type={active ? "primary" : "default"}
          icon={<AimOutlined />}
          disabled={!changed}
          onClick={() => onFocus()}
        >
          定位变化的核查区
        </Button>
      </div>
      <div className="multi-tour-outcome-stats">
        {result.grades.map((item) => {
          const gradeChanged = [
            ...result.before.features,
            ...result.after.features,
          ].some((feature) => feature.properties.grade === item.grade);
          const delta =
            item.before.area !== null && item.after.area !== null
              ? item.after.area - item.before.area
              : null;
          return (
            <button
              key={item.grade}
              disabled={!gradeChanged}
              onClick={() => onFocus(item.grade)}
              aria-label={`定位${item.grade}类核查区变化`}
            >
              <span>{item.grade}类优先核查区</span>
              <strong>
                {item.before.count}
                <i>→</i>
                {item.after.count}
                <small>处</small>
              </strong>
              <p>
                {delta === null
                  ? "面积资料尚不完整"
                  : Math.abs(delta) < 0.00005
                    ? "面积保持不变"
                    : `面积${delta < 0 ? "减少" : "增加"}${Math.abs(delta).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}平方公里`}
              </p>
            </button>
          );
        })}
      </div>
      <p>
        {changed
          ? "双图聚焦实际发生变化的核查区，未变化区域淡化。数量和面积由本次前后图层统计。"
          : "本次前后核查区保持一致。"}
        这里反映核查排序与范围的变化，找矿效果仍需后续调查验证。
      </p>
      {changed > 0 && (
        <details className="multi-tour-evidence multi-outcome-evidence">
          <summary>逐区查看实际调查依据与变化位置</summary>
          <p>
            岩性背景、参与分析的构造交汇和矿物权重按当次算法输出记录。点击定位，展开具体证据核对各要素如何影响核查区。
          </p>
          {[
            { label: "处理前", data: result.before },
            { label: "处理后", data: result.after },
          ].map((side) => (
            <section key={side.label}>
              <h3>{side.label}发生变化的核查区</h3>
              {side.data.features.map((feature, index) => (
                <details key={`${side.label}:${String(feature.id ?? index)}`}>
                  <summary>
                    {String(feature.properties.grade)}类核查区 {index + 1}
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
                    {String(
                      feature.properties.explanation ?? "详见该区具体证据记录",
                    )}
                  </p>
                  <p>
                    面积：
                    {Number(feature.properties.area_km2).toLocaleString(
                      "zh-CN",
                      { maximumFractionDigits: 4 },
                    )}
                    平方公里
                  </p>
                  <pre>
                    {typeof feature.properties.evidence_json === "string"
                      ? feature.properties.evidence_json
                      : JSON.stringify(
                          feature.properties.evidence_json ?? {},
                          null,
                          2,
                        )}
                  </pre>
                </details>
              ))}
            </section>
          ))}
        </details>
      )}
    </section>
  );
}
