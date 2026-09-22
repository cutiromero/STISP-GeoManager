import type { LoadedLayerGroup } from "../types";

const DB_NAME = "huyang-system-map-workspace";
const DB_VERSION = 1;
const STORE_NAME = "layer-groups";
const maxInMemoryWorkspaces = 3;
const inMemoryLayerGroups = new Map<string, LoadedLayerGroup[]>();

interface CachedLayerWorkspace {
  key: string;
  groups: LoadedLayerGroup[];
  savedAt: string;
}

export async function readCachedLayerGroups(
  workspaceKey: string,
): Promise<LoadedLayerGroup[]> {
  const inMemory = inMemoryLayerGroups.get(workspaceKey);
  if (inMemory) {
    inMemoryLayerGroups.delete(workspaceKey);
    inMemoryLayerGroups.set(workspaceKey, inMemory);
    return inMemory;
  }
  if (!hasIndexedDb()) {
    return [];
  }
  const db = await openLayerWorkspaceDb();
  try {
    const workspace = await requestToPromise<CachedLayerWorkspace | undefined>(
      db
        .transaction(STORE_NAME, "readonly")
        .objectStore(STORE_NAME)
        .get(workspaceKey),
    );
    return Array.isArray(workspace?.groups) ? workspace.groups : [];
  } finally {
    db.close();
  }
}

export async function writeCachedLayerGroups(
  workspaceKey: string,
  groups: LoadedLayerGroup[],
): Promise<void> {
  rememberCachedLayerGroups(workspaceKey, groups);
  if (!hasIndexedDb()) {
    return;
  }
  const db = await openLayerWorkspaceDb();
  try {
    await requestToPromise(
      db
        .transaction(STORE_NAME, "readwrite")
        .objectStore(STORE_NAME)
        .put({
          key: workspaceKey,
          groups,
          savedAt: new Date().toISOString(),
        } satisfies CachedLayerWorkspace),
    );
  } finally {
    db.close();
  }
}

export async function clearCachedLayerGroups(): Promise<void> {
  inMemoryLayerGroups.clear();
  if (!hasIndexedDb()) {
    return;
  }
  const db = await openLayerWorkspaceDb();
  try {
    await requestToPromise(
      db.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).clear(),
    );
  } finally {
    db.close();
  }
}

export function rememberCachedLayerGroups(
  workspaceKey: string,
  groups: LoadedLayerGroup[],
): void {
  inMemoryLayerGroups.delete(workspaceKey);
  inMemoryLayerGroups.set(workspaceKey, groups);
  while (inMemoryLayerGroups.size > maxInMemoryWorkspaces) {
    const leastRecentlyUsedKey = inMemoryLayerGroups.keys().next().value;
    if (leastRecentlyUsedKey === undefined) break;
    inMemoryLayerGroups.delete(leastRecentlyUsedKey);
  }
}

function hasIndexedDb(): boolean {
  return typeof globalThis.indexedDB !== "undefined";
}

function openLayerWorkspaceDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = globalThis.indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("图层缓存数据库升级被阻塞"));
  });
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
