import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { defaultCompositionLayout } from "../../map-composition/layout";
import CompositionCanvas from "./CompositionCanvas";

function Harness() {
  const [layout, setLayout] = useState(() =>
    defaultCompositionLayout("地图标题", [80, 30, 90, 40]),
  );
  return (
    <div style={{ width: 1000 }}>
      <CompositionCanvas
        layout={layout}
        previewUrl=""
        onChange={setLayout}
        onUndo={() => {}}
        onRedo={() => {}}
        canUndo={false}
        canRedo={false}
      />
      <output data-testid="layout">{JSON.stringify(layout)}</output>
    </div>
  );
}
describe("paper interaction", () => {
  it("commits a drag once, supports keyboard movement, and locks the element", async () => {
    const capture = vi
      .spyOn(HTMLElement.prototype, "setPointerCapture")
      .mockImplementation(() => {});
    render(<Harness />);
    const title = screen.getByRole("button", { name: "制图要素：标题" });
    const read = () => JSON.parse(screen.getByTestId("layout").textContent!);
    const before = read().title.xMm;
    fireEvent.pointerDown(title, {
      button: 0,
      pointerId: 1,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(title, { pointerId: 1, clientX: 160, clientY: 120 });
    expect(read().title.xMm).toBe(before);
    fireEvent.pointerUp(title, { pointerId: 1 });
    expect(read().title.xMm).toBeGreaterThan(before);
    const moved = read().title.xMm;
    fireEvent.keyDown(title, { key: "ArrowLeft" });
    expect(read().title.xMm).toBe(moved - 1);
    fireEvent.click(screen.getByRole("button", { name: /锁\s*定/ }));
    fireEvent.keyDown(title, { key: "ArrowLeft" });
    expect(read().title.xMm).toBe(moved - 1);
    capture.mockRestore();
  });
  it("adds editable text and persists its layer order", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "添加文字" }));
    fireEvent.change(screen.getByLabelText("选中要素文字"), {
      target: { value: "区域概况" },
    });
    fireEvent.click(screen.getByRole("button", { name: /置\s*底/ }));
    const layout = JSON.parse(screen.getByTestId("layout").textContent!);
    expect(layout.extraTexts[0].text).toBe("区域概况");
    expect(layout.editor.order[0]).toBe(layout.extraTexts[0].id);
  });
});
