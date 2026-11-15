import { browserSessionEpoch } from "../auth/browserSession";
import {
  attachProjectHeader,
  fetchProjectRequest,
  getActiveProject,
  releaseProjectResponse,
} from "../projects/session";
import { ReadFlights } from "./readFlights";

const flights = new ReadFlights();

export function readThumbnail(url: string, signal: AbortSignal) {
  return flights.run(
    JSON.stringify([browserSessionEpoch(), getActiveProject(), url]),
    async (sharedSignal) => {
      const request = attachProjectHeader(
        new Request(new URL(url, window.location.origin), {
          credentials: "include",
          signal: sharedSignal,
          headers: { Accept: "image/webp" },
        }),
      );
      const response = await fetchProjectRequest(request);
      try {
        if (!response.ok)
          throw Object.assign(new Error("封面暂时无法加载"), {
            status: response.status,
          });
        if (response.headers.get("X-Thumbnail-Status") === "pending") {
          await response.body?.cancel();
          return { pending: true, blob: null };
        }
        const blob = await response.blob();
        if (!blob.type.startsWith("image/") || !blob.size)
          throw new Error("封面响应不是有效图片");
        return { pending: false, blob };
      } finally {
        releaseProjectResponse(response);
      }
    },
    signal,
  );
}
