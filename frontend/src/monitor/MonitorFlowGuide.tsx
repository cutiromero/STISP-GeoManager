import { Collapse } from "antd";

export default function MonitorFlowGuide({
  scene,
}: {
  scene: "spartina" | "wildfire";
}) {
  const spartina = scene === "spartina";
  return (
    <Collapse
      ghost
      size="small"
      items={[
        {
          key: "guide",
          label: "输入、输出与参数说明",
          children: spartina ? (
            <div className="monitor-flow-guide">
              <p>
                <strong>输入：</strong>
                同一年、同一区域的3月、8月、12月卫星影像。每期包含16个反射率与植被、水分等特征，三期共同提供48个模型特征。
              </p>
              <p>
                <strong>处理：</strong>
                依次输入3月、8月、12月影像，随机森林逐块识别互花米草。原图日期用于浏览单期影像，解译使用所选年度三期组合。
              </p>
              <p>
                <strong>输出：</strong>
                互花米草分布图、分布概率图和面积、斑块统计。
              </p>
              <p>
                <strong>范围：</strong>
                默认处理三期影像的共同覆盖区域；框选范围用于只处理其中一个区域。
              </p>
              <p>
                <strong>时相选择：</strong>
                当前权重的三个特征位置分别对应3月、8月、12月。选择监测年度后，平台匹配同系列、同网格的三期影像；新年度登记齐这三个月即可解译。其他月份可在原图时间轴浏览，采用其他季节组合的模型可另行登记。
              </p>
            </div>
          ) : (
            <div className="monitor-flow-guide">
              <p>
                <strong>输入：</strong>
                全球野火观测数据，按监测内容和真实日期提取火烧面积或火辐射功率。
              </p>
              <p>
                <strong>处理：</strong>
                提取所选观测期，按物理量区间配色，统计研究范围内的观测值。
              </p>
              <p>
                <strong>输出：</strong>
                当前期观测图、分级图、区域统计和所选时间范围的变化序列。
              </p>
              <p>
                <strong>监测内容：</strong>
                GWIS和GFED提供火烧面积，FCCI提供月火烧面积；CAMS提供火辐射功率。按需要的物理量和可用日期选择。
              </p>
              <p>
                <strong>观测日期：</strong>
                GWIS、GFED、CAMS通常一周期约8天，年底为5或6天；FCCI按月。日期来自原始数据。
              </p>
              <p>
                <strong>趋势统计：</strong>
                “仅当前期”用于查看本期；近1个月观察近期变化，近3个月覆盖一个季节，近1年查看年内季节变化。界面按真实观测日期计算需要的期数。
              </p>
              <p>
                观测图使用所选当前期，趋势图覆盖所选统计时段。统计边界按实际可用观测期对齐。
              </p>
              <p>
                <strong>范围与单位：</strong>
                默认数据全域。火烧面积单位为公顷，区域内直接求和；火辐射功率使用有效格网均值。
              </p>
            </div>
          ),
        },
      ]}
    />
  );
}
