import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { appTheme } from "../theme";
import type { FeatureInfo } from "../types";
import FeatureDetailPanel from "./FeatureDetailPanel";

function renderProperties(properties: FeatureInfo["properties"]) {
  return render(
    <ConfigProvider theme={appTheme}>
      <FeatureDetailPanel
        feature={{ layerId: "result", layerName: "计算成果", properties }}
      />
    </ConfigProvider>,
  );
}

function labels(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll(".ant-descriptions-item-label"),
    (label) => label.textContent,
  );
}

describe("FeatureDetailPanel result properties", () => {
  it("shows real-map age changes and their source without changing values", () => {
    const { container } = renderProperties({
      feature_id: "pred-00231",
      formation: "八宝山组",
      geologic_age: "T3",
      source_kind: "真实预测图局部副本；预置少量时代录入演示错误",
      area_m2: 42000,
      change_old: "J3",
      change_new: "T3",
      change_reason: "地层名称、东昆仑南坡位置与辞书条件相符",
    });

    expect(labels(container)).toEqual([
      "修改前值",
      "修改后值",
      "修改原因",
      "地层名称",
      "地层时代",
      "资料性质",
      "面积（平方米）",
      "图斑编号",
    ]);
    expect(screen.getByText("J3")).toBeInTheDocument();
    expect(screen.getAllByText("T3")).toHaveLength(2);
    expect(screen.getByText("42000")).toBeInTheDocument();
    expect(screen.getByText("pred-00231")).toBeInTheDocument();
  });

  it("prioritizes real change details while preserving other fields and values", () => {
    const { container } = renderProperties({
      feature_id: "F06",
      contact_type: "断层",
      change_fields: "contact_type",
      change_evidence: "survey-contact-F06",
      check_status: "corrected",
      change_reason: "编号、空间位置、允许值和置信度均满足调查一致性规则",
      change_new: "contact_type=断层",
      change_old: "contact_type=整合",
      custom_zero: 0,
      custom_false: false,
      custom_null: null,
      custom_missing: undefined,
    });

    expect(labels(container)).toEqual([
      "修改前值",
      "修改后值",
      "修改原因",
      "修改依据",
      "检查状态",
      "修改字段",
      "图斑编号",
      "contact_type",
      "custom_zero",
      "custom_false",
      "custom_null",
    ]);
    expect(screen.getByText("contact_type=整合")).toBeInTheDocument();
    expect(screen.getByText("contact_type=断层")).toBeInTheDocument();
    expect(screen.getByText("survey-contact-F06")).toBeInTheDocument();
    expect(screen.getByText("corrected")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("-")).toBeInTheDocument();
    expect(screen.queryByText("custom_missing")).not.toBeInTheDocument();
    expect(screen.queryByText("调查优先顺序")).not.toBeInTheDocument();
  });

  it("prioritizes survey evidence without inventing absent change results", () => {
    const { container } = renderProperties({
      region: "缺资料区",
      evidence_sources: "observation-missing",
      reason: "有效覆盖不足，需要补充调查",
      decline_fraction: 0.125,
      mean_change: -0.05,
      coverage: 0.19995117,
      priority_rank: null,
      priority_class: "needs_data",
    });

    expect(labels(container)).toEqual([
      "调查优先类别",
      "调查优先顺序",
      "判断原因",
      "证据来源",
      "有效覆盖比例",
      "平均变化值",
      "下降面积占比",
      "region",
    ]);
    expect(screen.getByText("0.19995117")).toBeInTheDocument();
    expect(screen.getByText("-0.05")).toBeInTheDocument();
    expect(screen.getByText("needs_data")).toBeInTheDocument();
    expect(screen.queryByText("修改前值")).not.toBeInTheDocument();
    expect(screen.queryByText("检查状态")).not.toBeInTheDocument();
  });

  it("uses English labels for existing result fields and leaves unknown keys intact", async () => {
    await setLocale("en-US");
    const { container } = renderProperties({
      original_key: "original value",
      priority_rank: 1,
      change_reason: "Survey agreement",
      change_new: "contact_type=fault",
      change_old: "contact_type=conformable",
    });

    expect(labels(container)).toEqual([
      "Previous value",
      "Updated value",
      "Reason for change",
      "Survey priority rank",
      "original_key",
    ]);
    expect(screen.getByText("original value")).toBeInTheDocument();
    expect(screen.getByText("contact_type=fault")).toBeInTheDocument();
    expect(screen.queryByText("Check status")).not.toBeInTheDocument();
  });
});
