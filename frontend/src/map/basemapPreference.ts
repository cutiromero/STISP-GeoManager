import type { BasemapId } from "./basemapCatalog";

const preferenceKeyPrefix = "geomanager.basemap.v2";
const validBasemapIds = new Set<BasemapId>([
  "mapbox-satellite",
  "mapbox-streets",
  "tianditu-vector",
  "tianditu-imagery",
]);

interface BasemapPreferenceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function basemapPreferenceKey(scope: string) {
  const normalizedScope = scope.trim() || "anonymous";
  return `${preferenceKeyPrefix}:${normalizedScope}`;
}

export function readBasemapPreference(
  scope: string,
  storage: BasemapPreferenceStorage | null = browserStorage(),
): BasemapId | null {
  if (!storage) return null;
  try {
    const value = storage.getItem(basemapPreferenceKey(scope));
    return value && isBasemapId(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeBasemapPreference(
  scope: string,
  basemapId: BasemapId,
  storage: BasemapPreferenceStorage | null = browserStorage(),
) {
  if (!storage || !validBasemapIds.has(basemapId)) return false;
  try {
    storage.setItem(basemapPreferenceKey(scope), basemapId);
    return true;
  } catch {
    return false;
  }
}

function isBasemapId(value: string): value is BasemapId {
  return validBasemapIds.has(value as BasemapId);
}

function browserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
