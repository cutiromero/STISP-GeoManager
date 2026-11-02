import { useEffect, useRef, useState } from "react";

const defaults = { sidebar: 260, input: 64, workflow: 720 };
const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

export default function useAgentLayout(storageKey: string) {
  const [preferred, setPreferred] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null");
      return {
        sidebar: Number.isFinite(saved?.sidebar)
          ? clamp(saved.sidebar, 216, 400)
          : defaults.sidebar,
        input: Number.isFinite(saved?.input)
          ? clamp(saved.input, 64, 320)
          : defaults.input,
        workflow: Number.isFinite(saved?.workflow)
          ? clamp(saved.workflow, 360, 1120)
          : defaults.workflow,
      };
    } catch {
      return defaults;
    }
  });
  const [viewport, setViewport] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const savedPreference = useRef(preferred);
  useEffect(() => {
    const resize = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const persist = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(savedPreference.current));
    } catch {
      // Resizing remains available when browser storage is disabled.
    }
  };
  useEffect(() => {
    savedPreference.current = preferred;
    const timer = setTimeout(persist, 180);
    return () => clearTimeout(timer);
  }, [preferred, storageKey]);
  useEffect(() => () => persist(), [storageKey]);
  const sidebarMax = Math.max(
    216,
    Math.min(400, Math.floor(viewport.width * 0.34)),
  );
  const inputMax = Math.max(
    64,
    Math.min(320, Math.floor(viewport.height * 0.32)),
  );
  const workflowMax = Math.min(1120, viewport.width);
  const workflowMin = Math.min(360, workflowMax);
  return {
    defaults,
    narrow: viewport.width <= 900,
    sidebar: clamp(preferred.sidebar, 216, sidebarMax),
    sidebarMin: 216,
    sidebarMax,
    input: clamp(preferred.input, 64, inputMax),
    inputMin: 64,
    inputMax,
    workflow: clamp(preferred.workflow, workflowMin, workflowMax),
    workflowMin,
    workflowMax,
    setSidebar: (value: number) =>
      setPreferred((previous) => ({ ...previous, sidebar: value })),
    setInput: (value: number) =>
      setPreferred((previous) => ({ ...previous, input: value })),
    setWorkflow: (value: number) =>
      setPreferred((previous) => ({ ...previous, workflow: value })),
  };
}
