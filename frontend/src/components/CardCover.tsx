import { useEffect, useRef, useState } from "react";
import { readThumbnail } from "../api/thumbnailReads";
import { waitForAbortableDelay } from "../utils/rasterRenderTasks";
import "./CardCover.css";

interface Props {
  thumbnailUrl?: string | null;
  alt: string;
  className?: string;
  aspectRatio?: string;
  fit?: "cover" | "contain";
  priority?: boolean;
}

export default function CardCover({
  thumbnailUrl,
  alt,
  className = "",
  aspectRatio = "16 / 9",
  fit = "cover",
  priority = false,
}: Props) {
  const [failedUrl, setFailedUrl] = useState<string>();
  const [loadedUrl, setLoadedUrl] = useState<string>();
  const root = useRef<HTMLDivElement>(null);
  const managed = Boolean(thumbnailUrl?.startsWith("/api/"));
  const [visible, setVisible] = useState(priority);
  const [prepared, setPrepared] = useState<{ source: string; url: string }>();
  useEffect(() => {
    if (!managed || priority || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, [managed, priority]);
  useEffect(() => {
    if (!managed || !thumbnailUrl || !visible) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    const load = async () => {
      for (let attempt = 0; attempt < 8; attempt++) {
        const result = await readThumbnail(thumbnailUrl, controller.signal);
        controller.signal.throwIfAborted();
        if (!result.pending && result.blob) {
          objectUrl = URL.createObjectURL(result.blob);
          setPrepared({ source: thumbnailUrl, url: objectUrl });
          return;
        }
        await waitForAbortableDelay(
          Math.min(8000, 1000 * 2 ** attempt),
          controller.signal,
        );
      }
      throw new Error("封面准备超时");
    };
    void load().catch(() => {
      if (!controller.signal.aborted) setFailedUrl(thumbnailUrl);
    });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [managed, thumbnailUrl, visible]);
  const imageUrl = managed
    ? prepared?.source === thumbnailUrl
      ? prepared?.url
      : undefined
    : thumbnailUrl;
  const available = Boolean(thumbnailUrl && failedUrl !== thumbnailUrl);
  const loaded = available && loadedUrl === thumbnailUrl;
  return (
    <div
      ref={root}
      className={`card-cover ${className}`}
      style={{ aspectRatio }}
      data-state={loaded ? "ready" : "placeholder"}
    >
      {!loaded && (
        <span className="card-cover-placeholder" role="img" aria-label={alt}>
          <svg aria-hidden="true" viewBox="0 0 32 24" width="32" height="24">
            <rect x="1" y="1" width="30" height="22" rx="3" />
            <path d="m2 20 8-9 6 6 5-5 9 9M23 6h1" />
          </svg>
          {failedUrl === thumbnailUrl && thumbnailUrl && (
            <small>图片暂不可用</small>
          )}
        </span>
      )}
      {available && imageUrl && (
        <img
          src={imageUrl}
          alt={loaded ? alt : ""}
          width={640}
          height={360}
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          style={{ objectFit: fit, opacity: loaded ? 1 : 0 }}
          onLoad={() => setLoadedUrl(thumbnailUrl!)}
          onError={() => setFailedUrl(thumbnailUrl!)}
        />
      )}
    </div>
  );
}
