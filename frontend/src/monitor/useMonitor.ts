import { useEffect, useState } from "react";
import { applyMonitorEvent } from "./state";
import type { MonitorDataSource, MonitorEvent, MonitorSnapshot } from "./types";

export function useMonitor(source: MonitorDataSource) {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot>();
  const [error, setError] = useState(false);
  const [lastEvent, setLastEvent] = useState<MonitorEvent>();
  useEffect(() => {
    let disposed = false;
    let buffered: MonitorEvent[] = [];
    let ready = false;
    setSnapshot(undefined);
    setLastEvent(undefined);
    setError(false);
    const unsubscribe = source.subscribe((event) => {
      if (disposed) return;
      if (!ready) {
        buffered.push(event);
        return;
      }
      setSnapshot((current) =>
        current ? applyMonitorEvent(current, event) : current,
      );
      setLastEvent(event);
    });
    void source
      .getSnapshot()
      .then((initial) => {
        if (disposed) return;
        const latest = buffered.reduce(applyMonitorEvent, initial);
        setSnapshot(latest);
        setLastEvent(buffered[buffered.length - 1]);
        buffered = [];
        ready = true;
      })
      .catch(() => {
        if (!disposed) {
          setError(true);
          unsubscribe();
        }
      });
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, [source]);
  return { snapshot, error, lastEvent };
}

export function useMonitorActivity() {
  const [visible, setVisible] = useState(() => !document.hidden);
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateVisibility = () => setVisible(!document.hidden);
    const updateMotion = () => setReducedMotion(media.matches);
    document.addEventListener("visibilitychange", updateVisibility);
    media.addEventListener("change", updateMotion);
    updateVisibility();
    updateMotion();
    return () => {
      document.removeEventListener("visibilitychange", updateVisibility);
      media.removeEventListener("change", updateMotion);
    };
  }, []);
  return { visible, reducedMotion, animated: visible && !reducedMotion };
}
