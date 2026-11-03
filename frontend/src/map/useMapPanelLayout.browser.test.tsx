import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapPanelChrome from "./MapPanelChrome";
import { useMapPanelLayout } from "./useMapPanelLayout";
import "./map-workbench-panels.css";

function Harness({
  onResize = () => {},
  scope = "panel-test",
}: {
  onResize?: () => void;
  scope?: string;
}) {
  const panels = useMapPanelLayout(scope, onResize);
  return (
    <div ref={panels.containerRef} style={{ width: 1200, ...panels.style }}>
      <MapPanelChrome
        side="left"
        title="数据与图层"
        collapsed={panels.layout.leftCollapsed}
        width={panels.layout.left}
        english={false}
        onToggle={() => panels.toggle("left")}
        onResizeStart={(event) => panels.beginResize("left", event)}
        onResize={(amount) => panels.resize("left", amount)}
      />
      <output data-testid="panel-width">{panels.layout.left}</output>
    </div>
  );
}

describe("map panel resizing and recovery", () => {
  beforeEach(() =>
    localStorage.removeItem("stisp:map-panel-layout:panel-test"),
  );

  it("supports pointer resize, map resize, minimization and recovery after reopening", async () => {
    const onResize = vi.fn();
    const view = render(<Harness onResize={onResize} />);
    const handle = screen.getByRole("separator", {
      name: "调整数据与图层宽度",
    });
    fireEvent.pointerDown(handle, { button: 0, clientX: 320 });
    fireEvent.pointerMove(window, { clientX: 440 });
    fireEvent.pointerUp(window);
    await waitFor(() =>
      expect(screen.getByTestId("panel-width")).toHaveTextContent("440"),
    );
    await waitFor(() => expect(onResize).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "最小化数据与图层" }));
    await waitFor(() =>
      expect(
        JSON.parse(localStorage.getItem("stisp:map-panel-layout:panel-test")!),
      ).toMatchObject({ left: 440, leftCollapsed: true }),
    );
    view.unmount();
    render(<Harness />);
    expect(screen.queryByRole("separator")).toBeNull();
    fireEvent.click(
      screen.getAllByRole("button", { name: "展开数据与图层" })[0]!,
    );
    expect(screen.getByRole("separator")).toHaveAttribute(
      "aria-valuenow",
      "440",
    );
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    expect(screen.getByTestId("panel-width")).toHaveTextContent("460");
  });

  it("does not overwrite another user's saved panel layout when scope changes", async () => {
    localStorage.setItem(
      "stisp:map-panel-layout:other-user",
      JSON.stringify({
        left: 390,
        right: 280,
        leftCollapsed: false,
        rightCollapsed: true,
      }),
    );
    const view = render(<Harness />);
    await act(async () => view.rerender(<Harness scope="other-user" />));
    await waitFor(() =>
      expect(screen.getByTestId("panel-width")).toHaveTextContent("390"),
    );
    expect(
      JSON.parse(localStorage.getItem("stisp:map-panel-layout:other-user")!)
        .left,
    ).toBe(390);
  });
});
