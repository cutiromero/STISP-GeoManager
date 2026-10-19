import { App, Button, Modal, Space, Typography } from "antd";
import { selectedMapBasemap } from "../../map/basemapSnapshot";
import type { Map as MapboxMap } from "mapbox-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { compositionLegendItems } from "../../map-composition/legend";
import {
  constrainCompositionLayout,
  normalizeCompositionLayout,
  pagePixelSize,
  type MapBounds,
  type MapCompositionLayout,
} from "../../map-composition/layout";
import {
  compositionIssues,
  renderCompositionPng,
} from "../../map-composition/render";
import type {
  LoadedLayerGroup,
  MapComposition,
  WorkspaceSceneSnapshot,
} from "../../types";
import { downloadBlob } from "../../utils/download";
import CompositionCanvas from "./CompositionCanvas";
import { builtinOrder } from "../../map-composition/editing";
import CompositionSettings from "./CompositionSettings";
import CompositionOutputPanel from "./CompositionOutputPanel";

const autoPreviewDelayMs = 160;
const previewDpi = 96;

interface Props {
  open: boolean;
  composition: MapComposition | null;
  map: MapboxMap | null;
  groups: LoadedLayerGroup[];
  workspaceSnapshot: WorkspaceSceneSnapshot;
  fallbackBounds: MapBounds;
  sourceText: string;
  accessToken?: string;
  canExport: boolean;
  onClose: () => void;
  onSaved: (composition: MapComposition) => void;
}

export default function MapCompositionEditor({
  open,
  composition,
  map,
  groups,
  workspaceSnapshot,
  fallbackBounds,
  sourceText,
  accessToken,
  canExport,
  onClose,
  onSaved,
}: Props) {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const [layout, setLayout] = useState<MapCompositionLayout>(() =>
    normalizeCompositionLayout(
      {},
      english ? "Thematic map" : "专题图",
      fallbackBounds,
      sourceText,
    ),
  );
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [format, setFormat] = useState<"png" | "jpg" | "pdf">("pdf");
  const [versionNote, setVersionNote] = useState("");
  const initializedCompositionId = useRef<number | null>(null);
  const layoutRef = useRef(layout);
  const savedLayout = useRef("");
  const expectedUpdatedAt = useRef("");
  const imageCache = useRef(new Map<string, Blob>());
  const [autoSave, setAutoSave] = useState(true);
  const [saveState, setSaveState] = useState("");
  const history = useRef<MapCompositionLayout[]>([]);
  const future = useRef<MapCompositionLayout[]>([]);
  const [, setHistoryTick] = useState(0);
  const previewSequence = useRef(0);
  const previewUrlRef = useRef("");
  const previewAbortController = useRef<AbortController | null>(null);
  const previewTimer = useRef<number | null>(null);
  const legendItems = useMemo(() => compositionLegendItems(groups), [groups]);
  const issues = useMemo(
    () => compositionIssues(layout, legendItems, english),
    [english, layout, legendItems],
  );
  const hasErrors = issues.some((issue) => issue.level === "error");
  const pixels = pagePixelSize(layout);

  useEffect(() => {
    if (!composition) {
      initializedCompositionId.current = null;
      return;
    }
    if (initializedCompositionId.current === composition.id) return;
    initializedCompositionId.current = composition.id;
    expectedUpdatedAt.current = composition.updatedAt;
    imageCache.current.clear();
    setAutoSave(true);
    setSaveState("");
    previewAbortController.current?.abort();
    previewAbortController.current = null;
    previewSequence.current += 1;
    setPreviewUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    const nextLayout = normalizeCompositionLayout(
      composition.layout,
      composition.name,
      fallbackBounds,
      sourceText,
    );
    layoutRef.current = nextLayout;
    setLayout(nextLayout);
    savedLayout.current = JSON.stringify(nextLayout);
    history.current = [];
    future.current = [];
    setHistoryTick((t) => t + 1);
    setVersionNote("");
  }, [composition, fallbackBounds, sourceText]);

  useEffect(() => {
    previewUrlRef.current = previewUrl;
  }, [previewUrl]);

  useEffect(
    () => () => {
      if (previewTimer.current !== null) {
        window.clearTimeout(previewTimer.current);
        previewTimer.current = null;
      }
      previewAbortController.current?.abort();
      previewAbortController.current = null;
      previewSequence.current += 1;
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    },
    [],
  );

  const refreshPreview = useCallback(async () => {
    if (!map) {
      message.warning(english ? "The map is not ready" : "地图尚未准备好");
      return;
    }
    if (previewTimer.current !== null) {
      window.clearTimeout(previewTimer.current);
      previewTimer.current = null;
    }
    const previewLayout = layoutRef.current;
    const sequence = previewSequence.current + 1;
    previewSequence.current = sequence;
    previewAbortController.current?.abort();
    const controller = new AbortController();
    previewAbortController.current = controller;
    setPreviewing(true);
    try {
      const blob = await renderCompositionPng(
        map,
        previewLayout,
        legendItems,
        accessToken,
        {
          outputDpi: previewDpi,
          mapDpi: previewDpi,
          signal: controller.signal,
          imageCache: imageCache.current,
        },
      );
      if (sequence !== previewSequence.current) return;
      const nextUrl = URL.createObjectURL(blob);
      setPreviewUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextUrl;
      });
    } catch (error) {
      if (sequence !== previewSequence.current) return;
      if (isAbortError(error)) return;
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to preview thematic map"
            : "专题图预览失败",
      );
    } finally {
      if (previewAbortController.current === controller) {
        previewAbortController.current = null;
      }
      if (sequence === previewSequence.current) setPreviewing(false);
    }
  }, [accessToken, english, legendItems, map, message]);

  useEffect(() => {
    previewAbortController.current?.abort();
    previewAbortController.current = null;
    previewSequence.current += 1;
    if (!open || !map || !composition) {
      setPreviewing(false);
      return;
    }
    const timer = window.setTimeout(() => {
      if (previewTimer.current === timer) previewTimer.current = null;
      void refreshPreview();
    }, autoPreviewDelayMs);
    previewTimer.current = timer;
    return () => {
      window.clearTimeout(timer);
      if (previewTimer.current === timer) previewTimer.current = null;
      previewAbortController.current?.abort();
      previewAbortController.current = null;
    };
  }, [composition?.id, layout, map, open, refreshPreview]);

  useEffect(() => {
    if (!open || !map) return;
    const styleLoaded = () => void refreshPreview();
    map.on("style.load", styleLoaded);
    return () => {
      map.off("style.load", styleLoaded);
    };
  }, [map, open, refreshPreview]);

  const updateLayout = useCallback(
    (update: (current: MapCompositionLayout) => MapCompositionLayout) => {
      let candidate = update(layoutRef.current);
      for (const id of layoutRef.current.editor.locked) {
        if (!candidate.editor.locked.includes(id)) continue;
        if (builtinOrder.includes(id))
          candidate = { ...candidate, [id]: layoutRef.current[id] };
        else
          candidate = {
            ...candidate,
            extraTexts: candidate.extraTexts.map((t) =>
              t.id === id
                ? (layoutRef.current.extraTexts.find((old) => old.id === id) ??
                  t)
                : t,
            ),
          };
      }
      const next = constrainCompositionLayout(candidate);
      if (JSON.stringify(next) === JSON.stringify(layoutRef.current)) return;
      history.current = [...history.current.slice(-49), layoutRef.current];
      future.current = [];
      setHistoryTick((t) => t + 1);
      layoutRef.current = next;
      setLayout(next);
    },
    [],
  );

  function undo() {
    const previous = history.current.pop();
    if (!previous) return;
    future.current.push(layoutRef.current);
    layoutRef.current = previous;
    setLayout(previous);
    setHistoryTick((t) => t + 1);
  }
  function redo() {
    const next = future.current.pop();
    if (!next) return;
    history.current.push(layoutRef.current);
    layoutRef.current = next;
    setLayout(next);
    setHistoryTick((t) => t + 1);
  }
  function closeEditor() {
    if (savedLayout.current === JSON.stringify(layoutRef.current)) {
      onClose();
      return;
    }
    Modal.confirm({
      title: "保存制图草稿后关闭？",
      content: "当前有未保存的版式修改。",
      okText: "保存并关闭",
      cancelText: "继续编辑",
      onOk: async () => {
        const result = await saveDraft();
        if (result) onClose();
        else throw new Error("保存失败");
      },
    });
  }
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (open && savedLayout.current !== JSON.stringify(layoutRef.current))
        event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [open]);

  useEffect(() => {
    if (
      !open ||
      !composition ||
      saving ||
      exporting ||
      !autoSave ||
      savedLayout.current === JSON.stringify(layout)
    )
      return;
    setSaveState("未保存");
    const timer = window.setTimeout(() => {
      void saveDraft(true);
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [layout, open, composition?.id, autoSave, saving, exporting]);

  async function saveDraft(silent = false) {
    if (!composition) return null;
    setSaving(true);
    try {
      const result = await api.updateMapComposition(composition.id, {
        action: "update",
        layout: {
          ...layout,
          basemapId: layout.basemapId ?? selectedMapBasemap(map),
        },
        expectedUpdatedAt: expectedUpdatedAt.current,
      });
      if ("id" in result) {
        savedLayout.current = JSON.stringify(layout);
        expectedUpdatedAt.current = result.updatedAt;
        setSaveState("已保存");
        onSaved(result);
        if (!silent)
          message.success(english ? "Map draft saved" : "出图草稿已保存");
        return result;
      }
      return null;
    } catch (error) {
      setAutoSave(false);
      setSaveState("保存失败：草稿仍保留在当前页面");
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to save map draft"
            : "出图草稿保存失败",
      );
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function generateVersion() {
    if (!composition || !map || hasErrors) {
      if (hasErrors)
        message.warning(
          english
            ? "Resolve the output-check errors first"
            : "请先处理出图检查中的错误",
        );
      return;
    }
    previewAbortController.current?.abort();
    previewAbortController.current = null;
    previewSequence.current += 1;
    setPreviewing(false);
    setExporting(true);
    try {
      const saved = await api.updateMapComposition(composition.id, {
        action: "update",
        layout: {
          ...layout,
          basemapId: layout.basemapId ?? selectedMapBasemap(map),
        },
        expectedUpdatedAt: expectedUpdatedAt.current,
      });
      if ("id" in saved) {
        expectedUpdatedAt.current = saved.updatedAt;
        savedLayout.current = JSON.stringify(layout);
      }
      const master = await renderCompositionPng(
        map,
        layout,
        legendItems,
        accessToken,
      );
      const version = await api.createMapCompositionVersion(
        composition.id,
        master,
        {
          format,
          dpi: layout.page.dpi,
          widthPx: pixels.width,
          heightPx: pixels.height,
          note: versionNote.trim(),
          workspaceSnapshot,
        },
      );
      const result = await api.downloadMapCompositionVersion(
        composition.id,
        version.versionNumber,
      );
      downloadBlob(result.blob, result.filename);
      const refreshed = await api.mapComposition(composition.id);
      expectedUpdatedAt.current = refreshed.updatedAt;
      onSaved(refreshed);
      message.success(
        english
          ? `Thematic result V${version.versionNumber} generated and downloaded`
          : `专题成果 V${version.versionNumber} 已生成并下载`,
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to generate thematic result"
            : "专题成果生成失败",
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <Modal
      className="map-composition-editor-modal"
      title={
        composition
          ? english
            ? `Thematic mapping: ${composition.name}`
            : `专题制图：${composition.name}`
          : english
            ? "Thematic mapping"
            : "专题制图"
      }
      open={open}
      width="calc(100vw - 24px)"
      style={{ top: 12 }}
      footer={null}
      destroyOnHidden
      onCancel={closeEditor}
    >
      <div className="map-composition-editor">
        <aside className="map-composition-settings-pane">
          <CompositionSettings
            layout={layout}
            liveMapBounds={fallbackBounds}
            onChange={updateLayout}
          />
        </aside>
        <main className="map-composition-preview-pane">
          <div className="composition-preview-toolbar">
            <Typography.Text>
              {layout.page.preset} /{" "}
              {layout.page.orientation === "landscape"
                ? english
                  ? "Landscape"
                  : "横向"
                : english
                  ? "Portrait"
                  : "纵向"}{" "}
              / {pixels.width}×{pixels.height}px
            </Typography.Text>
            <Space>
              <Typography.Text type="secondary">{saveState}</Typography.Text>
              <Button size="small" onClick={() => setAutoSave((v) => !v)}>
                {autoSave ? "自动保存：开" : "自动保存：关"}
              </Button>
              <Typography.Text type="secondary">
                {previewing
                  ? english
                    ? "Updating preview…"
                    : "正在自动更新预览…"
                  : english
                    ? "Preview updates after changes"
                    : "修改后自动预览"}
              </Typography.Text>
              <Button loading={saving} onClick={() => void saveDraft()}>
                {english ? "Save draft" : "保存草稿"}
              </Button>
              <Button
                type="primary"
                loading={previewing}
                onClick={() => void refreshPreview()}
              >
                {english ? "Refresh now" : "立即刷新"}
              </Button>
            </Space>
          </div>
          <CompositionCanvas
            layout={layout}
            previewUrl={previewUrl}
            onChange={updateLayout}
            onUndo={undo}
            onRedo={redo}
            canUndo={history.current.length > 0}
            canRedo={future.current.length > 0}
          />
        </main>
        <CompositionOutputPanel
          issues={issues}
          format={format}
          note={versionNote}
          canExport={canExport}
          exporting={exporting}
          disabled={hasErrors || !map}
          onFormatChange={setFormat}
          onNoteChange={setVersionNote}
          onGenerate={() => void generateVersion()}
        />
      </div>
    </Modal>
  );
}

function isAbortError(error: unknown) {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : typeof error === "object" &&
        error !== null &&
        "name" in error &&
        error.name === "AbortError";
}
