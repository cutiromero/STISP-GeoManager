import type { LoadedLayerGroup } from "../types";

export interface LayerWorkspaceFingerprint {
  fingerprint: string;
  byteLength: number;
}

export function createLayerWorkspaceFingerprint(
  groups: LoadedLayerGroup[],
  maxBytes: number,
): LayerWorkspaceFingerprint | null {
  if (jsonLowerBoundExceeds(groups, maxBytes)) {
    return null;
  }
  const serialized = JSON.stringify(groups);
  const byteLength = utf8ByteLength(serialized, maxBytes);
  if (byteLength > maxBytes) {
    return null;
  }
  return {
    fingerprint: compactFingerprint(serialized, byteLength),
    byteLength,
  };
}

function jsonLowerBoundExceeds(value: unknown, maxBytes: number): boolean {
  let bytes = 0;
  const ancestors = new WeakSet<object>();
  const add = (amount: number) => {
    bytes += amount;
    return bytes > maxBytes;
  };

  const visit = (current: unknown, arrayItem = false): boolean => {
    if (current === null) return add(4);
    switch (typeof current) {
      case "string":
        return add(current.length + 2);
      case "number":
        return add(Number.isFinite(current) ? String(current).length : 4);
      case "boolean":
        return add(current ? 4 : 5);
      case "undefined":
      case "function":
      case "symbol":
        return arrayItem ? add(4) : false;
      case "bigint":
        return true;
      case "object":
        break;
    }

    const objectValue = current as object;
    if (ancestors.has(objectValue)) return true;
    ancestors.add(objectValue);
    try {
      if (Array.isArray(current)) {
        if (add(2 + Math.max(0, current.length - 1))) return true;
        for (const item of current) {
          if (visit(item, true)) return true;
        }
        return false;
      }

      const entries = Object.entries(current as Record<string, unknown>).filter(
        ([, item]) =>
          item !== undefined &&
          typeof item !== "function" &&
          typeof item !== "symbol",
      );
      if (add(2 + Math.max(0, entries.length - 1))) return true;
      for (const [key, item] of entries) {
        if (add(key.length + 3) || visit(item)) return true;
      }
      return false;
    } finally {
      ancestors.delete(objectValue);
    }
  };

  return visit(value);
}

function utf8ByteLength(value: string, stopAfter: number): number {
  let bytes = 0;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x7f) {
      bytes += 1;
    } else if (code <= 0x7ff) {
      bytes += 2;
    } else if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        bytes += 4;
        index += 1;
      } else {
        bytes += 3;
      }
    } else {
      bytes += 3;
    }
    if (bytes > stopAfter) return bytes;
  }
  return bytes;
}

function compactFingerprint(serialized: string, byteLength: number) {
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < serialized.length; index += 1) {
    const code = serialized.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
  }
  return `${byteLength}:${first >>> 0}:${second >>> 0}`;
}
