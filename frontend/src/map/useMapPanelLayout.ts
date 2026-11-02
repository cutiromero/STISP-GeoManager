import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
} from "react";

export type MapPanelSide = "left" | "right";
export interface MapPanelLayout {
  left: number;
  right: number;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
}
const MIN_WIDTH = 240;
const MAX_WIDTH = 560;
const COLLAPSED_WIDTH = 38;

export function constrainMapPanelLayout(
  layout: MapPanelLayout,
  viewport: number,
): MapPanelLayout {
  const available = Math.max(MIN_WIDTH * 2, viewport - 300);
  const limit = (value: number) =>
    Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, value));
  let left = limit(layout.left);
  let right = limit(layout.right);
  const occupied =
    (layout.leftCollapsed ? COLLAPSED_WIDTH : left) +
    (layout.rightCollapsed ? COLLAPSED_WIDTH : right);
  if (occupied > available) {
    const base =
      (layout.leftCollapsed ? COLLAPSED_WIDTH : MIN_WIDTH) +
      (layout.rightCollapsed ? COLLAPSED_WIDTH : MIN_WIDTH);
    const leftExtra = layout.leftCollapsed ? 0 : left - MIN_WIDTH;
    const rightExtra = layout.rightCollapsed ? 0 : right - MIN_WIDTH;
    const scale =
      Math.max(0, available - base) / Math.max(1, leftExtra + rightExtra);
    if (!layout.leftCollapsed) left = MIN_WIDTH + Math.floor(leftExtra * scale);
    if (!layout.rightCollapsed)
      right = MIN_WIDTH + Math.floor(rightExtra * scale);
  }
  return { ...layout, left, right };
}

function readLayout(key: string): MapPanelLayout {
  const fallback = {
    left: 320,
    right: 320,
    leftCollapsed: false,
    rightCollapsed: false,
  };
  try {
    const saved = JSON.parse(
      localStorage.getItem(key) ?? "null",
    ) as Partial<MapPanelLayout> | null;
    if (!saved) return fallback;
    return constrainMapPanelLayout(
      {
        left: Number.isFinite(saved.left) ? Number(saved.left) : fallback.left,
        right: Number.isFinite(saved.right)
          ? Number(saved.right)
          : fallback.right,
        leftCollapsed: saved.leftCollapsed === true,
        rightCollapsed: saved.rightCollapsed === true,
      },
      window.innerWidth,
    );
  } catch {
    return fallback;
  }
}

export function useMapPanelLayout(scope: string, onResize: () => void) {
  const key = `stisp:map-panel-layout:${scope}`;
  const [layout, setLayout] = useState(() => readLayout(key));
  const containerRef = useRef<HTMLDivElement>(null);
  const callbackRef = useRef(onResize);
  callbackRef.current = onResize;
  const dragCleanupRef = useRef<(() => void) | null>(null);
  const loadedKeyRef = useRef(key);
  const persistedKeyRef = useRef(key);

  useEffect(() => {
    if (loadedKeyRef.current !== key) {
      loadedKeyRef.current = key;
      setLayout(readLayout(key));
    }
  }, [key]);

  useEffect(() => {
    if (persistedKeyRef.current !== key) {
      persistedKeyRef.current = key;
      return;
    }
    try {
      localStorage.setItem(key, JSON.stringify(layout));
    } catch {
      /* Storage may be disabled. */
    }
    const frame = requestAnimationFrame(() => callbackRef.current());
    return () => cancelAnimationFrame(frame);
  }, [key, layout]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setLayout((current) => {
        const next = constrainMapPanelLayout(current, entry.contentRect.width);
        return next.left === current.left && next.right === current.right
          ? current
          : next;
      });
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      dragCleanupRef.current?.();
    };
  }, []);

  function resize(side: MapPanelSide, amount: number) {
    setLayout((current) => {
      const other = side === "left" ? "right" : "left";
      const otherCollapsed = current[`${other}Collapsed`];
      const width = containerRef.current?.clientWidth || window.innerWidth;
      const max = Math.min(
        MAX_WIDTH,
        width - 300 - (otherCollapsed ? COLLAPSED_WIDTH : current[other]),
      );
      return {
        ...current,
        [side]: Math.max(MIN_WIDTH, Math.min(max, current[side] + amount)),
      };
    });
  }

  function beginResize(side: MapPanelSide, event: PointerEvent) {
    if (event.button !== 0) return;
    event.preventDefault();
    dragCleanupRef.current?.();
    let lastX = event.clientX;
    let pending = 0;
    let frame = 0;
    const flush = () => {
      frame = 0;
      resize(side, pending);
      pending = 0;
    };
    const move = (next: globalThis.PointerEvent) => {
      pending += (next.clientX - lastX) * (side === "left" ? 1 : -1);
      lastX = next.clientX;
      if (!frame) frame = requestAnimationFrame(flush);
    };
    const previousCursor = document.body.style.cursor;
    const previousSelection = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const cleanup = () => {
      if (frame) {
        cancelAnimationFrame(frame);
        flush();
      }
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
      window.removeEventListener("blur", cleanup);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousSelection;
      dragCleanupRef.current = null;
    };
    dragCleanupRef.current = cleanup;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
    window.addEventListener("blur", cleanup);
  }

  const style = {
    "--map-left-panel-width": `${layout.leftCollapsed ? COLLAPSED_WIDTH : layout.left}px`,
    "--map-right-panel-width": `${layout.rightCollapsed ? COLLAPSED_WIDTH : layout.right}px`,
  } as CSSProperties;
  return {
    layout,
    style,
    containerRef,
    beginResize,
    resize,
    toggle: (side: MapPanelSide) =>
      setLayout((current) =>
        constrainMapPanelLayout(
          { ...current, [`${side}Collapsed`]: !current[`${side}Collapsed`] },
          containerRef.current?.clientWidth || window.innerWidth,
        ),
      ),
  };
}
