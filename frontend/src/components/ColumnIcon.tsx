import type { CSSProperties } from "react";
import platform from "../assets/columns/0-平台2.svg";
import map from "../assets/columns/1-地理工作台.svg";
import data from "../assets/columns/2-数据资源.svg";
import compute from "../assets/columns/3-计算中心.svg";
import analysis from "../assets/columns/4-数据分析.svg";
import results from "../assets/columns/5-成果展示.svg";
import agent from "../assets/columns/6-智能预警.svg";
import admin from "../assets/columns/7-后台管理.svg";
import knowledge from "../assets/columns/8-时空科普.svg";
import news from "../assets/columns/9-团队动态.svg";
import about from "../assets/columns/10-关于我们.svg";
import upload from "../assets/columns/11-数据导入.svg";
import language from "../assets/columns/12-切换语言.svg";
import project from "../assets/columns/14-项目.svg";

const icons = {
  platform,
  map,
  data,
  compute,
  analysis,
  results,
  agent,
  admin,
  knowledge,
  news,
  about,
  upload,
  language,
  project,
};

export default function ColumnIcon({
  name,
  style,
}: {
  name: keyof typeof icons;
  style?: CSSProperties;
}) {
  if (name === "platform") {
    return (
      <img
        src={platform}
        alt=""
        aria-hidden="true"
        style={{ width: "1em", height: "1em", ...style }}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="anticon column-icon"
      style={{
        display: "inline-block",
        width: "1em",
        height: "1em",
        flexShrink: 0,
        backgroundColor: "currentColor",
        mask: `url("${icons[name]}") center / contain no-repeat`,
        WebkitMask: `url("${icons[name]}") center / contain no-repeat`,
        ...style,
      }}
    />
  );
}
