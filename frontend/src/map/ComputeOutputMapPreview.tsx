import {
  ArrowLeftOutlined,
  CloseOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import { Alert, Button, Slider, Spin } from "antd";
import type { Map as MapboxMap } from "mapbox-gl";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { computeApi } from "../api/compute";
import type { ComputeMapPreview } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import {
  getActiveProject,
  projectSignal,
  projectUrl,
} from "../projects/session";
import "./computePreview.css";

const sourceId = "compute-output-preview-source";
const layerId = "compute-output-preview-layer";

export function removeComputePreview(map: MapboxMap) {
  try {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  } catch {
    // A destroyed map has already removed its transient content.
  }
}

export function addComputePreview(
  map: MapboxMap,
  preview: ComputeMapPreview,
  imageUrl: string,
) {
  if (!map.isStyleLoaded()) return false;
  if (!map.getSource(sourceId)) {
    map.addSource(sourceId, {
      type: "image",
      url: imageUrl,
      coordinates: preview.imageCoordinates,
    });
  }
  if (!map.getLayer(layerId)) {
    map.addLayer({
      id: layerId,
      type: "raster",
      source: sourceId,
      paint: { "raster-opacity": 1, "raster-fade-duration": 0 },
    });
  }
  return true;
}

async function readPreviewImage(url: string, signal: AbortSignal) {
  const parsed = new URL(url, window.location.origin);
  if (
    parsed.origin !== window.location.origin ||
    !parsed.pathname.startsWith("/api/compute/outputs/")
  )
    throw new Error("结果预览地址无效");
  const response = await fetch(
    projectUrl(`${parsed.pathname}${parsed.search}`),
    {
      credentials: "include",
      headers: { "X-Project-Id": getActiveProject() },
      signal,
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || "无法读取结果预览");
  }
  if (!response.headers.get("Content-Type")?.startsWith("image/png"))
    throw new Error("结果预览图片尚未就绪");
  return URL.createObjectURL(await response.blob());
}

export default function ComputeOutputMapPreview({
  outputId,
  map,
  projectTagId,
  onClose,
}: {
  outputId: number;
  map: MapboxMap | null;
  projectTagId?: string | null;
  onClose: () => void;
}) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<{
    data: ComputeMapPreview;
    image: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [opacity, setOpacity] = useState(100);
  const opacityRef = useRef(opacity);
  opacityRef.current = opacity;
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let currentUrl = "";
    let imageUrl = "";
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, projectSignal()]);
    setPreview(null);
    setError("");
    setLoading(true);
    const refresh = async () => {
      try {
        if (projectTagId && projectTagId !== getActiveProject())
          throw new Error(
            ui(
              "请切换到结果所属项目后查看。",
              "Select the result's project before viewing.",
            ),
          );
        const next = await computeApi.mapPreview(outputId);
        if (disposed) return;
        if (next.imageUrl !== currentUrl || !imageUrl) {
          const image = await readPreviewImage(next.imageUrl, signal);
          if (disposed) {
            URL.revokeObjectURL(image);
            return;
          }
          if (imageUrl) URL.revokeObjectURL(imageUrl);
          imageUrl = image;
          currentUrl = next.imageUrl;
          setPreview({ data: next, image });
        }
        setLoading(false);
        setError("");
        timer = setTimeout(refresh, document.hidden ? 30000 : 15000);
      } catch (reason) {
        if (disposed) return;
        setPreview(null);
        setLoading(false);
        setError(reason instanceof Error ? reason.message : "结果预览失败");
      }
    };
    void refresh();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [outputId, projectTagId, revision]);
  useEffect(() => {
    if (!map || !preview) return;
    let fitted = false;
    const restore = () => {
      if (map.getLayer(layerId) && map.getSource(sourceId)) return;
      if (!addComputePreview(map, preview.data, preview.image)) return;
      map.setPaintProperty(layerId, "raster-opacity", opacityRef.current / 100);
      if (fitted) return;
      fitted = true;
      const coordinates = preview.data.imageCoordinates;
      const longitudes = coordinates.map((point) => point[0]);
      const latitudes = coordinates.map((point) => point[1]);
      map.fitBounds(
        [
          [Math.min(...longitudes), Math.min(...latitudes)],
          [Math.max(...longitudes), Math.max(...latitudes)],
        ],
        { padding: 90, maxZoom: 19, bearing: 0, pitch: 0, duration: 500 },
      );
    };
    map.on("style.load", restore);
    map.on("idle", restore);
    restore();
    return () => {
      map.off("style.load", restore);
      map.off("idle", restore);
      removeComputePreview(map);
    };
  }, [map, preview]);
  useEffect(() => {
    if (map?.getLayer(layerId))
      map.setPaintProperty(layerId, "raster-opacity", opacity / 100);
  }, [map, opacity, preview]);
  return (
    <section
      className="compute-map-preview-bar"
      aria-label={ui("计算结果预览", "Computed result preview")}
    >
      <div className="compute-map-preview-title">
        <EyeOutlined />
        <div>
          <strong>
            {preview?.data.name ||
              ui("计算结果预览", "Computed result preview")}
          </strong>
          <span>
            {ui(
              "临时预览 · 原数据保持不变",
              "Temporary preview · Original data preserved",
            )}
          </span>
        </div>
        <Button
          type="text"
          icon={<CloseOutlined />}
          aria-label={ui("关闭结果预览", "Close result preview")}
          onClick={onClose}
        />
      </div>
      {loading && (
        <div className="compute-map-preview-loading" role="status">
          <Spin size="small" />
          {ui("正在准备结果预览…", "Preparing the result preview…")}
        </div>
      )}
      {error && (
        <Alert
          title={error}
          type="error"
          action={
            <Button
              size="small"
              onClick={() => setRevision((value) => value + 1)}
            >
              {ui("重试", "Retry")}
            </Button>
          }
        />
      )}
      {preview && (
        <div className="compute-map-preview-opacity">
          <span>{ui("结果透明度", "Result opacity")}</span>
          <Slider
            value={opacity}
            onChange={setOpacity}
            aria-label={ui("结果透明度", "Result opacity")}
          />
        </div>
      )}
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate("/agent/workbench")}
      >
        {ui(
          "返回智能体，选择是否入库",
          "Return to the agent to choose whether to import",
        )}
      </Button>
    </section>
  );
}
