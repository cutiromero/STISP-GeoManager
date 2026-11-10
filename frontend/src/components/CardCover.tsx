import { useState } from "react";
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
  const available = Boolean(thumbnailUrl && failedUrl !== thumbnailUrl);
  const loaded = available && loadedUrl === thumbnailUrl;
  return (
    <div
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
        </span>
      )}
      {available && (
        <img
          src={thumbnailUrl!}
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
