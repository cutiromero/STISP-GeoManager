import { useCallback, useRef } from "react";
import type { LoadedLayer, LoadedLayerGroup } from "../types";
import { findLoadedResourceLayer } from "../utils/uniqueLoadedLayers";

export function useUniqueLayerLoad(options: {
  scope: string;
  groups: LoadedLayerGroup[];
  onExisting: (group: LoadedLayerGroup, layer: LoadedLayer) => Promise<void>;
  onLoading: () => void;
}) {
  const latest = useRef(options);
  latest.current = options;
  const pending = useRef(new Map<string, Promise<boolean>>());

  const showExisting = useCallback(async (key: string) => {
    const found = findLoadedResourceLayer(latest.current.groups, key);
    if (!found) return false;
    await latest.current.onExisting(found.group, found.layer);
    return true;
  }, []);

  const load = useCallback(
    async (key: string, create: () => Promise<boolean>) => {
      const requestKey = `${latest.current.scope}:${key}`;
      const inFlight = pending.current.get(requestKey);
      if (inFlight) {
        latest.current.onLoading();
        return inFlight;
      }
      // Register before yielding so rapid clicks and different entry points
      // share one query/render operation, including the initial existence test.
      const operation = (async () => {
        if (await showExisting(key)) return true;
        return create();
      })();
      pending.current.set(requestKey, operation);
      try {
        return await operation;
      } finally {
        if (pending.current.get(requestKey) === operation) {
          pending.current.delete(requestKey);
        }
      }
    },
    [showExisting],
  );

  return { load, showExisting };
}
