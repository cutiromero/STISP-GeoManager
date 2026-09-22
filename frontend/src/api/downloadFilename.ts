export function filenameFromHeaders(headers: Headers) {
  const disposition = headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(
    /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i,
  )?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.trim().replace(/^"|"$/g, ""));
    } catch {
      // Fall through to the plain filename or content-type fallback.
    }
  }
  const plain = disposition.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
  const filename = (plain?.[1] ?? plain?.[2])?.trim();
  if (filename) return filename;
  const contentType = headers.get("Content-Type")?.toLowerCase() ?? "";
  if (contentType.includes("application/pdf")) return "map-composition.pdf";
  if (contentType.includes("image/png")) return "map-composition.png";
  if (contentType.includes("image/jpeg")) return "map-composition.jpg";
  if (contentType.includes("zip")) return "layers-export.zip";
  return "download.bin";
}
