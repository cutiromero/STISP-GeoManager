import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
  type RasterSymbolization,
  type VectorSymbolization,
} from "../symbolization";
import { appTheme } from "../theme";
import {
  RasterSymbolizationEditor,
  VectorSymbolizationEditor,
} from "./SymbolizationEditor";
import "../styles.css";

describe("symbolization JSON reuse", () => {
  it("keeps raster import instructions and JSON text readable", async () => {
    render(
      <ConfigProvider locale={zhCN} theme={appTheme}>
        <AntApp>
          <RasterEditorHarness onApply={vi.fn()} />
        </AntApp>
      </ConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "导入 JSON" }));

    const instruction = await screen.findByText(
      "粘贴由“复制 JSON”生成的完整方案",
    );
    const modalTitle = screen.getByText("导入栅格符号化方案");
    const jsonInput = screen.getByRole("textbox", {
      name: "符号化方案 JSON",
    });
    expect(getComputedStyle(modalTitle).color).toBe("rgb(22, 41, 54)");
    expect(getComputedStyle(instruction).color).toBe("rgb(246, 250, 253)");
    expect(getComputedStyle(jsonInput).color).toBe("rgb(22, 41, 54)");
    expect(getComputedStyle(jsonInput).backgroundColor).toBe(
      "rgb(247, 249, 251)",
    );
  });

  it("imports pasted raster JSON into the editor before applying it", async () => {
    const onApply = vi.fn();
    render(
      <ConfigProvider locale={zhCN} theme={appTheme}>
        <AntApp>
          <RasterEditorHarness onApply={onApply} />
        </AntApp>
      </ConfigProvider>,
    );

    expect(
      screen.getByRole("button", { name: "复制 JSON" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "导入 JSON" }));

    const imported = cloneDefaultRasterSymbolization();
    imported.opacity = 63;
    fireEvent.change(
      await screen.findByRole("textbox", { name: "符号化方案 JSON" }),
      { target: { value: JSON.stringify(imported) } },
    );
    fireEvent.click(screen.getByRole("button", { name: "校验并导入" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "符号化方案 JSON" }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确定" }));

    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ opacity: 63 }),
    );
  });

  it("keeps an incompatible scheme in the dialog and explains the problem", async () => {
    render(
      <ConfigProvider locale={zhCN} theme={appTheme}>
        <AntApp>
          <RasterEditorHarness onApply={vi.fn()} />
        </AntApp>
      </ConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
    const imported = cloneDefaultRasterSymbolization();
    imported.bands = [2];
    fireEvent.change(
      await screen.findByRole("textbox", { name: "符号化方案 JSON" }),
      { target: { value: JSON.stringify(imported) } },
    );
    fireEvent.click(screen.getByRole("button", { name: "校验并导入" }));

    expect(
      await screen.findByText("目标栅格缺少方案引用的波段：2"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "符号化方案 JSON" }),
    ).toBeInTheDocument();
  });

  it("offers the same copy, import, and apply chain for vector schemes", async () => {
    const onApply = vi.fn();
    render(
      <ConfigProvider locale={zhCN} theme={appTheme}>
        <AntApp>
          <VectorEditorHarness onApply={onApply} />
        </AntApp>
      </ConfigProvider>,
    );

    expect(
      screen.getByRole("button", { name: "复制 JSON" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
    const imported = cloneDefaultVectorSymbolization();
    imported.opacity = 58;
    fireEvent.change(
      await screen.findByRole("textbox", { name: "符号化方案 JSON" }),
      { target: { value: JSON.stringify(imported) } },
    );
    fireEvent.click(screen.getByRole("button", { name: "校验并导入" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "符号化方案 JSON" }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确定" }));
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ opacity: 58 }),
    );
  });
});

function RasterEditorHarness({
  onApply,
}: {
  onApply: (value: RasterSymbolization) => void;
}) {
  const [value, setValue] = useState(cloneDefaultRasterSymbolization());
  return (
    <RasterSymbolizationEditor
      value={value}
      bands={[
        {
          band: 1,
          type: "Byte",
          description: "Band 1",
          colorInterpretation: "Gray",
          min: 0,
          max: 255,
          isInteger: true,
        },
      ]}
      onChange={setValue}
      onApply={() => onApply(value)}
    />
  );
}

function VectorEditorHarness({
  onApply,
}: {
  onApply: (value: VectorSymbolization) => void;
}) {
  const [value, setValue] = useState(cloneDefaultVectorSymbolization());
  return (
    <VectorSymbolizationEditor
      value={value}
      fields={[
        {
          name: "name",
          type: "String",
          nullable: false,
          sampleValues: ["胡杨"],
          description: "名称",
        },
      ]}
      geometryType="Point"
      onChange={setValue}
      onApply={() => onApply(value)}
    />
  );
}
