import {
  AimOutlined,
  BgColorsOutlined,
  DeleteOutlined,
  DownloadOutlined,
  DownOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  FolderOpenOutlined,
  HolderOutlined,
  PlusOutlined,
  RightOutlined,
  SaveOutlined,
  TableOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popover,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Tooltip,
  Typography,
} from "antd";
import {
  type DragEvent,
  type ReactNode,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import i18n from "../i18n";
import {
  type DropPlacement,
  type ExportFormat,
  type LayerDropPlacement,
  useLayerContext,
} from "../hooks/LayerContext";
import {
  isGraduatedRenderer,
  isUniqueValueRenderer,
  rasterSymbolizationFromRules,
  type GroupSymbolization,
  type RasterSymbolization,
  type VectorSymbolization,
} from "../symbolization";
import {
  classValuesLabel,
  graduatedRangeLabel,
} from "../symbolizationTemplates";
import type {
  ExportLayerItem,
  LoadedLayer,
  LoadedLayerGroup,
  RasterBandMetadata,
  ResourceField,
  ResourceListItem,
  ResourceVisualizationSummary,
  WorkspaceSceneSummary,
} from "../types";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import { resourceExportId } from "../utils/resources";

const RasterSymbolizationEditor = lazy(() =>
  import("./SymbolizationEditor").then((module) => ({
    default: module.RasterSymbolizationEditor,
  })),
);
const VectorSymbolizationEditor = lazy(() =>
  import("./SymbolizationEditor").then((module) => ({
    default: module.VectorSymbolizationEditor,
  })),
);

export default function LayerPanel() {
  const ctx = useLayerContext();
  const { message } = App.useApp();
  const { t } = useTranslation();
  const [saveForm] = Form.useForm<SaveWorkspaceFormValues>();
  const groups = ctx.groups;
  const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [draggingGroupId, setDraggingGroupId] = useState<string | null>(null);
  const [dragTarget, setDragTarget] = useState<{
    groupId: string;
    placement: DropPlacement;
  } | null>(null);
  const [draggingLayer, setDraggingLayer] = useState<{
    groupId: string;
    layerId: string;
  } | null>(null);
  const [layerDropTarget, setLayerDropTarget] = useState<{
    groupId: string;
    layerId: string | null;
    placement: LayerDropPlacement;
  } | null>(null);
  const [saveMode, setSaveMode] = useState<"create" | "update">("create");
  const [saveOpen, setSaveOpen] = useState(false);
  const [savingWorkspace, setSavingWorkspace] = useState(false);
  const [saveSearch, setSaveSearch] = useState("");
  const [saveCandidates, setSaveCandidates] = useState<WorkspaceSceneSummary[]>(
    [],
  );
  const [saveCandidateTotal, setSaveCandidateTotal] = useState(0);
  const saveSearchSequence = useRef(0);
  useEffect(() => {
    if (!saveOpen) return;
    const sequence = ++saveSearchSequence.current;
    const timer = setTimeout(() => {
      void api
        .workspaces({ q: saveSearch, limit: 100 })
        .then((result) => {
          if (sequence !== saveSearchSequence.current) return;
          setSaveCandidates(result.items);
          setSaveCandidateTotal(result.total);
        })
        .catch((error) => message.error(error.message));
    }, 200);
    return () => {
      clearTimeout(timer);
      saveSearchSequence.current += 1;
    };
  }, [saveOpen, saveSearch, message]);
  const groupDragFrameRef = useRef<number | null>(null);
  const groupDragPendingRef = useRef<{
    element: HTMLElement;
    clientY: number;
    targetGroupId: string;
  } | null>(null);
  const layerDragFrameRef = useRef<number | null>(null);
  const layerDragPendingRef = useRef<{
    element: HTMLElement;
    clientY: number;
    targetGroupId: string;
    targetLayerId: string;
  } | null>(null);
  const selectedSaveTargetId = Form.useWatch("targetId", saveForm);
  const saveTargetScenes = useMemo(
    () =>
      [
        ...new Map(
          [...ctx.workspaceScenes, ...saveCandidates].map((scene) => [
            scene.id,
            scene,
          ]),
        ).values(),
      ].filter((scene) => scene.canEdit),
    [ctx.workspaceScenes, saveCandidates],
  );
  const selectedSaveTarget = useMemo(
    () => saveTargetScenes.find((scene) => scene.id === selectedSaveTargetId),
    [saveTargetScenes, selectedSaveTargetId],
  );
  const layerTreeLabel = groups.some((group) => group.isManual)
    ? t("layerPanel.loadedLayersAndGroups")
    : t("layerPanel.loadedLayers");

  const setDragTargetIfChanged = useCallback(
    (next: { groupId: string; placement: DropPlacement } | null) => {
      setDragTarget((current) =>
        current?.groupId === next?.groupId &&
        current?.placement === next?.placement
          ? current
          : next,
      );
    },
    [],
  );

  const setLayerDropTargetIfChanged = useCallback(
    (
      next: {
        groupId: string;
        layerId: string | null;
        placement: LayerDropPlacement;
      } | null,
    ) => {
      setLayerDropTarget((current) =>
        current?.groupId === next?.groupId &&
        current?.layerId === next?.layerId &&
        current?.placement === next?.placement
          ? current
          : next,
      );
    },
    [],
  );

  const scheduleGroupDragTarget = useCallback(
    (element: HTMLElement, clientY: number, targetGroupId: string) => {
      groupDragPendingRef.current = { element, clientY, targetGroupId };
      if (groupDragFrameRef.current !== null) return;
      groupDragFrameRef.current = window.requestAnimationFrame(() => {
        groupDragFrameRef.current = null;
        const pending = groupDragPendingRef.current;
        groupDragPendingRef.current = null;
        if (!pending) return;
        const rect = pending.element.getBoundingClientRect();
        const placement =
          pending.clientY < rect.top + rect.height / 2 ? "before" : "after";
        setDragTargetIfChanged({
          groupId: pending.targetGroupId,
          placement,
        });
      });
    },
    [setDragTargetIfChanged],
  );

  const scheduleLayerDragTarget = useCallback(
    (
      element: HTMLElement,
      clientY: number,
      targetGroupId: string,
      targetLayerId: string,
    ) => {
      layerDragPendingRef.current = {
        element,
        clientY,
        targetGroupId,
        targetLayerId,
      };
      if (layerDragFrameRef.current !== null) return;
      layerDragFrameRef.current = window.requestAnimationFrame(() => {
        layerDragFrameRef.current = null;
        const pending = layerDragPendingRef.current;
        layerDragPendingRef.current = null;
        if (!pending) return;
        const rect = pending.element.getBoundingClientRect();
        const placement =
          pending.clientY < rect.top + rect.height / 2 ? "before" : "after";
        setLayerDropTargetIfChanged({
          groupId: pending.targetGroupId,
          layerId: pending.targetLayerId,
          placement,
        });
      });
    },
    [setLayerDropTargetIfChanged],
  );

  useEffect(() => {
    return () => {
      if (groupDragFrameRef.current !== null) {
        window.cancelAnimationFrame(groupDragFrameRef.current);
      }
      if (layerDragFrameRef.current !== null) {
        window.cancelAnimationFrame(layerDragFrameRef.current);
      }
    };
  }, []);

  function cancelScheduledGroupDragTarget() {
    if (groupDragFrameRef.current !== null) {
      window.cancelAnimationFrame(groupDragFrameRef.current);
      groupDragFrameRef.current = null;
    }
    groupDragPendingRef.current = null;
  }

  function cancelScheduledLayerDragTarget() {
    if (layerDragFrameRef.current !== null) {
      window.cancelAnimationFrame(layerDragFrameRef.current);
      layerDragFrameRef.current = null;
    }
    layerDragPendingRef.current = null;
  }

  function resetGroupDragState() {
    cancelScheduledGroupDragTarget();
    setDraggingGroupId(null);
    setDragTarget(null);
  }

  function resetLayerDragState() {
    cancelScheduledLayerDragTarget();
    setDraggingLayer(null);
    setLayerDropTarget(null);
  }

  function toggleGroup(groupId: string) {
    setCollapsedGroupIds((current) => {
      const next = new Set(current);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }

  function openSaveWorkspace() {
    if (!ctx.canCreateWorkspaces) {
      message.warning(t("layerPanel.noCreatePermission"));
      return;
    }
    if (groups.length === 0) {
      message.warning(t("layerPanel.noLayersToSave"));
      return;
    }
    setSaveMode("create");
    saveForm.setFieldsValue({
      targetId: undefined,
      name: "",
      description: "",
      accessGroupIds: [],
    });
    setSaveOpen(true);
  }

  async function submitSaveWorkspace() {
    const values = await saveForm.validateFields();
    const targetScene =
      saveMode === "update"
        ? saveTargetScenes.find((scene) => scene.id === values.targetId)
        : null;
    if (saveMode === "update" && !targetScene) {
      message.warning(t("layerPanel.selectOverwriteTarget"));
      return;
    }
    setSavingWorkspace(true);
    try {
      await ctx.saveWorkspace(
        saveMode === "update" && targetScene
          ? {
              targetId: targetScene.id,
              expectedUpdatedAt: values.expectedUpdatedAt,
              name: targetScene.name,
              description: targetScene.description,
              accessGroupIds: values.accessGroupIds ?? [],
            }
          : values,
      );
      setSaveOpen(false);
    } finally {
      setSavingWorkspace(false);
    }
  }

  function handleDragStart(event: DragEvent<HTMLElement>, groupId: string) {
    event.stopPropagation();
    resetLayerDragState();
    cancelScheduledGroupDragTarget();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", `group:${groupId}`);
    setDraggingGroupId(groupId);
  }

  function handleDragOver(
    event: DragEvent<HTMLElement>,
    targetGroupId: string,
  ) {
    const sourceLayer =
      draggingLayer ??
      layerPayloadFromDrag(event.dataTransfer.getData("text/plain"));
    if (sourceLayer) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      const rect = event.currentTarget.getBoundingClientRect();
      const placement =
        event.clientY < rect.top + rect.height / 2 ? "before" : "after";
      setLayerDropTargetIfChanged({
        groupId: targetGroupId,
        layerId: null,
        placement,
      });
      return;
    }

    const sourceGroupId =
      draggingGroupId ??
      groupIdFromDrag(event.dataTransfer.getData("text/plain"));
    if (!sourceGroupId || sourceGroupId === targetGroupId) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    scheduleGroupDragTarget(event.currentTarget, event.clientY, targetGroupId);
  }

  function handleDrop(event: DragEvent<HTMLElement>, targetGroupId: string) {
    const sourceLayer =
      layerPayloadFromDrag(event.dataTransfer.getData("text/plain")) ||
      draggingLayer;
    if (sourceLayer) {
      event.preventDefault();
      event.stopPropagation();
      cancelScheduledLayerDragTarget();
      const rect = event.currentTarget.getBoundingClientRect();
      const placement = verticalDropPlacement(event.clientY, rect);
      ctx.extractLayer(
        sourceLayer.groupId,
        sourceLayer.layerId,
        targetGroupId,
        placement,
      );
      resetLayerDragState();
      return;
    }

    const sourceGroupId =
      groupIdFromDrag(event.dataTransfer.getData("text/plain")) ||
      draggingGroupId;
    if (!sourceGroupId || sourceGroupId === targetGroupId) {
      resetGroupDragState();
      return;
    }
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const placement = verticalDropPlacement(event.clientY, rect);
    ctx.reorderGroups(sourceGroupId, targetGroupId, placement);
    resetGroupDragState();
  }

  function handleLayerDragStart(
    event: DragEvent<HTMLElement>,
    groupId: string,
    layerId: string,
  ) {
    event.stopPropagation();
    resetGroupDragState();
    cancelScheduledLayerDragTarget();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", `layer:${groupId}:${layerId}`);
    setDraggingLayer({ groupId, layerId });
  }

  function handleLayerDragOverGroup(
    event: DragEvent<HTMLElement>,
    targetGroupId: string,
  ) {
    const sourceLayer =
      draggingLayer ??
      layerPayloadFromDrag(event.dataTransfer.getData("text/plain"));
    if (!sourceLayer) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setLayerDropTargetIfChanged({
      groupId: targetGroupId,
      layerId: null,
      placement: "inside",
    });
  }

  function handleLayerDragOverLayer(
    event: DragEvent<HTMLElement>,
    targetGroupId: string,
    targetLayerId: string,
  ) {
    const sourceLayer =
      draggingLayer ??
      layerPayloadFromDrag(event.dataTransfer.getData("text/plain"));
    if (!sourceLayer || sourceLayer.layerId === targetLayerId) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    scheduleLayerDragTarget(
      event.currentTarget,
      event.clientY,
      targetGroupId,
      targetLayerId,
    );
  }

  function handleLayerDrop(
    event: DragEvent<HTMLElement>,
    targetGroupId: string,
    targetLayerId: string | null,
  ) {
    const sourceLayer =
      layerPayloadFromDrag(event.dataTransfer.getData("text/plain")) ||
      draggingLayer;
    if (!sourceLayer) {
      resetLayerDragState();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    cancelScheduledLayerDragTarget();
    const placement: LayerDropPlacement =
      targetLayerId !== null
        ? verticalDropPlacement(
            event.clientY,
            event.currentTarget.getBoundingClientRect(),
          )
        : "inside";
    ctx.moveLayer(
      sourceLayer.groupId,
      sourceLayer.layerId,
      targetGroupId,
      targetLayerId,
      placement,
    );
    resetLayerDragState();
  }

  function handleLayerSymbolizationChange(
    groupId: string,
    layerId: string,
    symbolization: VectorSymbolization | RasterSymbolization,
  ) {
    if (!ctx.canUseCustomSymbolization) {
      return;
    }
    const targetLayer = ctx.groups
      .find((g) => g.id === groupId)
      ?.children.find((l) => l.id === layerId);
    ctx.setLayerSymbolization(groupId, layerId, symbolization);
    if (
      "mode" in symbolization &&
      "bands" in symbolization &&
      targetLayer?.layerType === "raster"
    ) {
      ctx.startRasterRender(
        groupId,
        layerId,
        symbolization,
        { ...targetLayer, symbolization },
        "custom",
      );
    }
  }

  function createManualLayerGroup() {
    const group = createEmptyLayerGroup(
      t("layerPanel.groupDefaultName", { number: groups.length + 1 }),
    );
    ctx.addGroup(group);
    message.success(t("layerPanel.groupCreated"));
  }

  return (
    <section className="panel-section">
      <div className="layer-save-actions">
        <Button
          size="small"
          icon={<SaveOutlined style={{ fontSize: 14 }} />}
          disabled={groups.length === 0 || !ctx.canCreateWorkspaces}
          onClick={openSaveWorkspace}
        >
          {t("layerPanel.saveAsProject")}
        </Button>
        <Button
          size="small"
          icon={<PlusOutlined style={{ fontSize: 14 }} />}
          onClick={createManualLayerGroup}
        >
          {t("layerPanel.createGroup")}
        </Button>
      </div>
      {groups.length > 0 ? (
        <div className="layer-tree" role="tree" aria-label={layerTreeLabel}>
          {groups.map((group) => {
            const standaloneLayer = standaloneLayerForGroup(group);
            const expanded = !collapsedGroupIds.has(group.id);
            const dropClass =
              dragTarget?.groupId === group.id
                ? ` layer-group-drop-${dragTarget.placement}`
                : layerDropTarget?.groupId === group.id &&
                    layerDropTarget.layerId === null &&
                    layerDropTarget.placement !== "inside"
                  ? ` layer-group-drop-${layerDropTarget.placement}`
                  : "";
            if (standaloneLayer) {
              return (
                <div
                  key={group.id}
                  className="layer-group-shell layer-standalone-shell"
                >
                  <LayerItemNode
                    groupId={group.id}
                    layer={standaloneLayer}
                    dragging={
                      draggingLayer?.groupId === group.id &&
                      draggingLayer.layerId === standaloneLayer.id
                    }
                    dropPlacement={
                      layerDropTarget?.groupId === group.id &&
                      layerDropTarget.layerId === standaloneLayer.id
                        ? layerDropTarget.placement
                        : null
                    }
                    onDragStart={(event) =>
                      handleLayerDragStart(event, group.id, standaloneLayer.id)
                    }
                    onDragEnd={() => {
                      resetLayerDragState();
                    }}
                    onDragOver={(event) =>
                      handleLayerDragOverLayer(
                        event,
                        group.id,
                        standaloneLayer.id,
                      )
                    }
                    onDrop={(event) =>
                      handleLayerDrop(event, group.id, standaloneLayer.id)
                    }
                    onVisibilityChange={ctx.setLayerVisibility}
                    onNameChange={ctx.setLayerName}
                    onSymbolizationChange={handleLayerSymbolizationChange}
                    onLocate={ctx.locateLayer}
                    onRemove={ctx.removeLayer}
                    onSelect={() =>
                      ctx.selectLayer(group.id, standaloneLayer.id)
                    }
                    selected={ctx.selectedLayerId === standaloneLayer.id}
                    exportItems={exportItemsForLayer(standaloneLayer)}
                  />
                </div>
              );
            }
            return (
              <div
                key={group.id}
                className={`layer-group-shell${draggingGroupId === group.id ? " is-dragging" : ""}${dropClass}`}
                role="treeitem"
                tabIndex={0}
                aria-expanded={expanded}
              >
                <LayerGroupNode
                  group={group}
                  expanded={expanded}
                  onToggleExpand={() => toggleGroup(group.id)}
                  onDragStart={(event) => handleDragStart(event, group.id)}
                  onDragEnd={() => {
                    resetGroupDragState();
                  }}
                  onDragOver={(event) => handleDragOver(event, group.id)}
                  onDragLeave={(event) => {
                    const relatedTarget = event.relatedTarget;
                    if (
                      relatedTarget instanceof Node &&
                      event.currentTarget.contains(relatedTarget)
                    ) {
                      return;
                    }
                    cancelScheduledGroupDragTarget();
                    setDragTarget(null);
                  }}
                  onDrop={(event) => handleDrop(event, group.id)}
                  onVisibilityChange={ctx.setGroupVisibility}
                  onNameChange={ctx.setGroupName}
                  onLocate={ctx.locateGroup}
                  onRemove={ctx.removeGroup}
                  onSelect={() => {
                    const firstLayer = group.children[0];
                    if (firstLayer) {
                      ctx.selectLayer(group.id, firstLayer.id);
                    }
                  }}
                  exportItems={exportItemsForGroup(group)}
                />
                {expanded && (
                  <fieldset
                    className={
                      layerDropTarget?.groupId === group.id &&
                      layerDropTarget.layerId === null &&
                      layerDropTarget.placement === "inside"
                        ? "layer-children layer-children-drop-inside"
                        : "layer-children"
                    }
                    onDragOver={(event) =>
                      handleLayerDragOverGroup(event, group.id)
                    }
                    onDrop={(event) => handleLayerDrop(event, group.id, null)}
                  >
                    {group.children.map((layer) => (
                      <LayerItemNode
                        key={layer.id}
                        groupId={group.id}
                        layer={layer}
                        dragging={
                          draggingLayer?.groupId === group.id &&
                          draggingLayer.layerId === layer.id
                        }
                        dropPlacement={
                          layerDropTarget?.groupId === group.id &&
                          layerDropTarget.layerId === layer.id
                            ? layerDropTarget.placement
                            : null
                        }
                        onDragStart={(event) =>
                          handleLayerDragStart(event, group.id, layer.id)
                        }
                        onDragEnd={() => {
                          resetLayerDragState();
                        }}
                        onDragOver={(event) =>
                          handleLayerDragOverLayer(event, group.id, layer.id)
                        }
                        onDrop={(event) =>
                          handleLayerDrop(event, group.id, layer.id)
                        }
                        onVisibilityChange={ctx.setLayerVisibility}
                        onNameChange={ctx.setLayerName}
                        onSymbolizationChange={handleLayerSymbolizationChange}
                        onLocate={ctx.locateLayer}
                        onRemove={ctx.removeLayer}
                        onSelect={() => ctx.selectLayer(group.id, layer.id)}
                        selected={ctx.selectedLayerId === layer.id}
                        exportItems={exportItemsForLayer(layer)}
                      />
                    ))}
                    {group.children.length === 0 ? (
                      <div className="layer-children-empty">
                        {t("layerPanel.dropLayerHere")}
                      </div>
                    ) : null}
                  </fieldset>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <Empty
          className="layer-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("layerPanel.noLoadedLayers")}
        />
      )}
      <Modal
        title={t("layerPanel.saveAsProject")}
        open={saveOpen}
        okText={t("layerPanel.save")}
        confirmLoading={savingWorkspace}
        onOk={submitSaveWorkspace}
        onCancel={() => setSaveOpen(false)}
        destroyOnHidden
      >
        <Form form={saveForm} layout="vertical">
          <Form.Item name="expectedUpdatedAt" hidden>
            <Input />
          </Form.Item>
          <Form.Item label={t("layerPanel.saveMode")}>
            <Segmented
              block
              value={saveMode}
              options={[
                { label: t("layerPanel.create"), value: "create" },
                {
                  label: t("layerPanel.overwriteProject"),
                  value: "update",
                  disabled: saveTargetScenes.length === 0,
                },
              ]}
              onChange={(value) => {
                const nextMode = value as "create" | "update";
                setSaveMode(nextMode);
                if (nextMode === "create") {
                  saveForm.setFieldsValue({
                    targetId: undefined,
                    name: "",
                    description: "",
                    accessGroupIds: [],
                  });
                  return;
                }
                const firstScene = saveTargetScenes[0];
                saveForm.setFieldsValue({
                  targetId: firstScene?.id,
                  expectedUpdatedAt: firstScene?.updatedAt,
                  name: firstScene?.name ?? "",
                  description: firstScene?.description ?? "",
                  accessGroupIds:
                    firstScene?.accessGroups.map((group) => group.id) ?? [],
                });
              }}
            />
          </Form.Item>
          {saveMode === "update" ? (
            <>
              <Form.Item
                name="targetId"
                label={t("layerPanel.selectProject")}
                rules={[
                  { required: true, message: t("layerPanel.selectSaveTarget") },
                ]}
              >
                <Select
                  showSearch
                  filterOption={false}
                  onSearch={setSaveSearch}
                  onPopupScroll={(event) => {
                    const element = event.target as HTMLElement;
                    if (
                      element.scrollTop + element.clientHeight <
                        element.scrollHeight - 12 ||
                      saveCandidates.length >= saveCandidateTotal
                    )
                      return;
                    const sequence = saveSearchSequence.current;
                    void api
                      .workspaces({
                        q: saveSearch,
                        limit: 100,
                        offset: saveCandidates.length,
                      })
                      .then((result) => {
                        if (sequence === saveSearchSequence.current)
                          setSaveCandidates((current) => [
                            ...new Map(
                              [...current, ...result.items].map((scene) => [
                                scene.id,
                                scene,
                              ]),
                            ).values(),
                          ]);
                      })
                      .catch((error) => message.error(error.message));
                  }}
                  placeholder={t("layerPanel.overwritePlaceholder")}
                  options={saveTargetScenes.map((scene) => ({
                    value: scene.id,
                    label: scene.name,
                  }))}
                  onChange={(targetId) => {
                    const scene = saveTargetScenes.find(
                      (item) => item.id === targetId,
                    );
                    saveForm.setFieldsValue({
                      name: scene?.name ?? "",
                      expectedUpdatedAt: scene?.updatedAt,
                      description: scene?.description ?? "",
                      accessGroupIds:
                        scene?.accessGroups.map((group) => group.id) ?? [],
                    });
                  }}
                />
              </Form.Item>
              {selectedSaveTarget ? (
                <Alert
                  className="workspace-save-overwrite-alert"
                  type="warning"
                  showIcon
                  title={t("layerPanel.overwriteTitle", {
                    name: selectedSaveTarget.name,
                  })}
                  description={t("layerPanel.overwriteDescription")}
                />
              ) : null}
            </>
          ) : (
            <>
              <Form.Item
                name="name"
                label={t("layerPanel.projectName")}
                rules={[{ required: true, message: t("layerPanel.enterName") }]}
              >
                <Input maxLength={80} />
              </Form.Item>
              <Form.Item name="description" label={t("common.description")}>
                <Input.TextArea rows={3} maxLength={300} />
              </Form.Item>
            </>
          )}
          <Alert
            className="workspace-save-fixed-access-alert"
            type="info"
            showIcon
            title={t("layerPanel.ownerAlwaysVisible")}
            description={t("layerPanel.systemAccessDescription")}
          />
        </Form>
      </Modal>
    </section>
  );
}

function LayerTooltip({
  title,
  children,
}: {
  title: ReactNode;
  children: ReactNode;
}) {
  return (
    <Tooltip
      title={title}
      color="rgba(6, 24, 32, 0.96)"
      rootClassName="layer-action-tooltip"
    >
      {children}
    </Tooltip>
  );
}

interface SaveWorkspaceFormValues {
  expectedUpdatedAt?: string;
  targetId?: number;
  name: string;
  description?: string;
  accessGroupIds?: number[];
}

function standaloneLayerForGroup(group: LoadedLayerGroup): LoadedLayer | null {
  if (group.isManual || group.children.length !== 1) {
    return null;
  }
  return group.children[0] ?? null;
}

interface GroupNodeProps {
  group: LoadedLayerGroup;
  expanded: boolean;
  onToggleExpand: () => void;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDragLeave: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onVisibilityChange: (groupId: string, visible: boolean) => void;
  onNameChange: (groupId: string, name: string) => void;
  onLocate: (groupId: string) => void;
  onRemove: (groupId: string) => void;
  onSelect: () => void;
  exportItems: ExportLayerItem[];
}

function LayerGroupNode({
  group,
  expanded,
  onToggleExpand,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDragLeave,
  onDrop,
  onVisibilityChange,
  onNameChange,
  onLocate,
  onRemove,
  onSelect,
  exportItems,
}: GroupNodeProps) {
  const ctx = useLayerContext();
  return (
    <div
      className="layer-tree-node layer-tree-node-group"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="layer-row-main">
        <div className="layer-heading">
          <LayerTooltip
            title={
              expanded
                ? i18n.t("layerPanel.collapse")
                : i18n.t("layerPanel.expand")
            }
          >
            <Button
              className="layer-icon-button"
              type="text"
              size="small"
              aria-label={
                expanded
                  ? i18n.t("layerPanel.collapseNamed", { name: group.name })
                  : i18n.t("layerPanel.expandNamed", { name: group.name })
              }
              icon={
                expanded ? (
                  <DownOutlined style={{ fontSize: 14 }} />
                ) : (
                  <RightOutlined style={{ fontSize: 14 }} />
                )
              }
              onClick={(event) => {
                event.stopPropagation();
                onToggleExpand();
              }}
            />
          </LayerTooltip>
          <Switch
            className="visibility-switch"
            checked={group.visible}
            size="small"
            aria-label={i18n.t(
              group.visible ? "layerPanel.hideGroup" : "layerPanel.showGroup",
              { name: group.name },
            )}
            checkedChildren={<EyeOutlined style={{ fontSize: 10 }} />}
            unCheckedChildren={
              <EyeInvisibleOutlined style={{ fontSize: 10 }} />
            }
            onChange={(checked) => onVisibilityChange(group.id, checked)}
          />
          <FolderOpenOutlined style={{ fontSize: 14 }} />
        </div>
        <div className="layer-row-tools">
          <NodeActions
            symbolization={group.symbolization}
            fields={[]}
            subjectName={group.name}
            onSymbolizationChange={() => undefined}
            onLocate={() => onLocate(group.id)}
            onRemove={() => onRemove(group.id)}
            exportItems={exportItems}
            canUseCustomSymbolization={false}
            canExportData={ctx.canExportData}
          />
          <LayerTooltip title={i18n.t("layerPanel.sort")}>
            <Button
              className="layer-drag-handle action-btn"
              type="text"
              size="small"
              aria-label={i18n.t("layerPanel.dragGroup", { name: group.name })}
              draggable
              icon={<HolderOutlined style={{ fontSize: 14 }} />}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onClick={(event) => event.stopPropagation()}
            />
          </LayerTooltip>
        </div>
      </div>
      <div className="layer-name-row">
        <Typography.Text
          strong
          editable={{
            onChange: (next) =>
              onNameChange(group.id, next.trim() || group.name),
          }}
        >
          {group.name}
        </Typography.Text>
        <Button size="small" type="link" onClick={onSelect}>
          {i18n.t("layerPanel.select")}
        </Button>
      </div>
    </div>
  );
}

interface LayerNodeProps {
  groupId: string;
  layer: LoadedLayer;
  dragging: boolean;
  dropPlacement: LayerDropPlacement | null;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onVisibilityChange: (
    groupId: string,
    layerId: string,
    visible: boolean,
  ) => void;
  onNameChange: (groupId: string, layerId: string, name: string) => void;
  onSymbolizationChange: (
    groupId: string,
    layerId: string,
    value: VectorSymbolization | RasterSymbolization,
  ) => void;
  onLocate: (groupId: string, layerId: string) => void;
  onRemove: (groupId: string, layerId: string) => void;
  onSelect: () => void;
  selected: boolean;
  exportItems: ExportLayerItem[];
}

function LayerItemNode({
  groupId,
  layer,
  dragging,
  dropPlacement,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  onVisibilityChange,
  onNameChange,
  onSymbolizationChange,
  onLocate,
  onRemove,
  onSelect,
  selected,
  exportItems,
}: LayerNodeProps) {
  const ctx = useLayerContext();
  const dropClass = dropPlacement ? ` layer-drop-${dropPlacement}` : "";
  const fieldValueCounts = useMemo(() => buildFieldValueCounts(layer), [layer]);
  return (
    <div
      className={`layer-tree-node${selected ? " layer-tree-node-selected" : ""}${dragging ? " is-dragging" : ""}${dropClass}`}
      role="treeitem"
      tabIndex={0}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="layer-row-main">
        <div className="layer-heading">
          <Switch
            className="visibility-switch"
            checked={layer.visible}
            size="small"
            aria-label={i18n.t(
              layer.visible ? "layerPanel.hideLayer" : "layerPanel.showLayer",
              { name: layer.name },
            )}
            checkedChildren={<EyeOutlined style={{ fontSize: 10 }} />}
            unCheckedChildren={
              <EyeInvisibleOutlined style={{ fontSize: 10 }} />
            }
            onChange={(checked) =>
              onVisibilityChange(groupId, layer.id, checked)
            }
          />
          <LayerTooltip
            title={
              ctx.isLayerExtentVisible(layer.id)
                ? i18n.t("layerPanel.hideExtent")
                : i18n.t("layerPanel.showExtent")
            }
          >
            <Switch
              className="layer-extent-switch"
              checked={ctx.isLayerExtentVisible(layer.id)}
              size="small"
              checkedChildren={<AimOutlined style={{ fontSize: 10 }} />}
              unCheckedChildren={<AimOutlined style={{ fontSize: 10 }} />}
              aria-label={i18n.t(
                ctx.isLayerExtentVisible(layer.id)
                  ? "layerPanel.hideNamedExtent"
                  : "layerPanel.showNamedExtent",
                { name: layer.name },
              )}
              onChange={(checked) =>
                ctx.setLayerExtentVisibility(layer.id, checked)
              }
            />
          </LayerTooltip>
        </div>
        <div className="layer-row-tools">
          <NodeActions
            symbolization={layer.symbolization}
            fields={layer.fields}
            fieldValueCounts={fieldValueCounts}
            geometryType={layer.geometryType}
            sourceResource={layer.sourceResource}
            rasterBands={
              layer.layerType === "raster"
                ? (layer.rasterMetadata?.bands ?? [])
                : []
            }
            rasterDatasetId={
              layer.layerType === "raster" ? layer.rasterDatasetId : undefined
            }
            subjectName={layer.name}
            onSymbolizationChange={(next) =>
              onSymbolizationChange(
                groupId,
                layer.id,
                next as VectorSymbolization | RasterSymbolization,
              )
            }
            onLocate={() => onLocate(groupId, layer.id)}
            onRemove={() => onRemove(groupId, layer.id)}
            exportItems={exportItems}
            canUseCustomSymbolization={ctx.canUseCustomSymbolization}
            canExportData={ctx.canExportData}
            onOpenTable={() => ctx.openLayerTable(groupId, layer.id)}
          />
          <LayerTooltip title={i18n.t("layerPanel.dragToSort")}>
            <Button
              className="layer-drag-handle action-btn"
              type="text"
              size="small"
              aria-label={i18n.t("layerPanel.dragLayer", { name: layer.name })}
              draggable
              icon={<HolderOutlined style={{ fontSize: 14 }} />}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onClick={(event) => event.stopPropagation()}
            />
          </LayerTooltip>
        </div>
      </div>
      <div className="layer-name-row">
        <Typography.Text
          strong
          editable={{
            onChange: (next) =>
              onNameChange(groupId, layer.id, next.trim() || layer.name),
          }}
        >
          {layer.name}
        </Typography.Text>
        <Button
          size="small"
          type={selected ? "primary" : "link"}
          onClick={onSelect}
        >
          {selected
            ? i18n.t("layerPanel.selected")
            : i18n.t("layerPanel.select")}
        </Button>
      </div>
      {layer.metadata.对比任务 && (
        <small className="layer-comparison-role">
          {String(layer.metadata.对比角色)} / {String(layer.metadata.对比要素)}
        </small>
      )}
      <RasterRenderFeedback layer={layer} />
      <LayerLegend layer={layer} />
    </div>
  );
}

function RasterRenderFeedback({ layer }: { layer: LoadedLayer }) {
  if (layer.layerType !== "raster") return null;
  const status = layer.renderStatus ?? "";
  const running = ["queued", "running", "processing"].includes(status);
  if (!running && status !== "failed") return null;

  const progress = Math.min(100, Math.max(0, layer.renderProgress ?? 0));
  const messages = layer.renderMessages ?? [];
  const latestMessage = messages[messages.length - 1];
  const isUniqueValue = layer.symbolization.mode === "unique";
  if (status === "failed") {
    return (
      <div
        className="layer-raster-render-feedback is-failed"
        role="alert"
        aria-label={i18n.t("layerPanel.renderFailed", { name: layer.name })}
      >
        <strong>
          {isUniqueValue
            ? i18n.t("layerPanel.uniqueRenderFailed")
            : i18n.t("layerPanel.rasterRenderFailed")}
        </strong>
        <small>
          {latestMessage || layer.summary || i18n.t("layerPanel.retryLater")}
        </small>
      </div>
    );
  }

  return (
    <div
      className="layer-raster-render-feedback"
      role="status"
      aria-live="polite"
      aria-label={i18n.t("layerPanel.renderStatus", { name: layer.name })}
    >
      <div className="layer-raster-render-heading">
        <span>
          <Spin size="small" />
          {isUniqueValue
            ? i18n.t("layerPanel.uniqueRendering")
            : i18n.t("layerPanel.rasterRendering")}
        </span>
        <b>{Math.round(progress)}%</b>
      </div>
      <Progress percent={progress} size="small" showInfo={false} />
      <small>
        {latestMessage || i18n.t("layerPanel.preparingRender")}
        {`; ${i18n.t("layerPanel.autoUpdateNotice")}`}
      </small>
    </div>
  );
}

function LayerLegend({ layer }: { layer: LoadedLayer }) {
  if (layer.layerType !== "vector") return null;
  const renderer = layer.symbolization.renderer;
  const visibleClasses = isUniqueValueRenderer(renderer)
    ? [...renderer.classes, renderer.defaultClass]
        .filter((item) => item.visible)
        .map((item) => ({
          id: item.id,
          label: item.label,
          color: item.color,
          count: item.count,
          title: `${item.label}：${classValuesLabel(item)}`,
        }))
    : isGraduatedRenderer(renderer)
      ? [...renderer.classes, renderer.defaultClass]
          .filter((item) => item.visible)
          .map((item) => ({
            id: item.id,
            label: item.label,
            color: item.color,
            count: item.count,
            title: `${item.label}：${graduatedRangeLabel(item)}`,
          }))
      : [];
  if (visibleClasses.length === 0) return null;
  return (
    <div
      className="layer-legend-strip"
      aria-label={i18n.t("layerPanel.legendLabel", { name: layer.name })}
    >
      {visibleClasses.slice(0, 6).map((item) => (
        <span className="layer-legend-item" key={item.id}>
          <i style={{ backgroundColor: item.color }} />
          <span title={item.title}>{item.label}</span>
          <small>{item.count}</small>
        </span>
      ))}
      {visibleClasses.length > 6 && (
        <span className="layer-legend-more">+{visibleClasses.length - 6}</span>
      )}
    </div>
  );
}

function buildFieldValueCounts(layer: LoadedLayer) {
  if (layer.layerType !== "vector") return {};
  const result: Record<string, Record<string, number>> = {};
  for (const field of layer.fields) {
    const counts: Record<string, number> = {};
    for (const feature of layer.geojson.features) {
      const properties = feature.properties ?? {};
      const value = (properties as Record<string, unknown>)[field.name];
      if (value === null || value === undefined) continue;
      const key = String(value).trim();
      if (!key) continue;
      counts[key] = (counts[key] ?? 0) + 1;
    }
    result[field.name] = counts;
  }
  return result;
}

function groupIdFromDrag(value: string): string | null {
  const match = value.match(/^group:(.+)$/);
  return match?.[1] ?? null;
}

function layerPayloadFromDrag(
  value: string,
): { groupId: string; layerId: string } | null {
  const match = value.match(/^layer:([^:]+):(.+)$/);
  if (!match?.[1] || !match[2]) return null;
  return { groupId: match[1], layerId: match[2] };
}

function verticalDropPlacement(
  clientY: number,
  rect: Pick<DOMRect, "top" | "height">,
): DropPlacement {
  return clientY < rect.top + rect.height / 2 ? "before" : "after";
}

interface NodeActionProps {
  symbolization: GroupSymbolization | VectorSymbolization | RasterSymbolization;
  fields: ResourceField[];
  fieldValueCounts?: Record<string, Record<string, number>>;
  geometryType?: string;
  sourceResource?: ResourceListItem;
  rasterBands?: RasterBandMetadata[];
  rasterDatasetId?: number;
  subjectName: string;
  onSymbolizationChange: (
    value: GroupSymbolization | VectorSymbolization | RasterSymbolization,
  ) => void;
  onLocate: () => void;
  onRemove: () => void;
  onOpenTable?: () => void;
  exportItems: ExportLayerItem[];
  canUseCustomSymbolization: boolean;
  canExportData: boolean;
}

function NodeActions({
  symbolization,
  fields,
  fieldValueCounts,
  geometryType,
  sourceResource,
  rasterBands = [],
  rasterDatasetId,
  subjectName,
  onSymbolizationChange,
  onLocate,
  onRemove,
  onOpenTable,
  exportItems,
  canUseCustomSymbolization,
  canExportData,
}: NodeActionProps) {
  const ctx = useLayerContext();
  const { message } = App.useApp();
  const [symbolizationOpen, setSymbolizationOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [draftSymbolization, setDraftSymbolization] = useState(symbolization);
  const committedSymbolizationRef = useRef(symbolization);
  const [exportReproject, setExportReproject] = useState(false);
  const [exportClip, setExportClip] = useState(false);
  const [exportEpsg, setExportEpsg] = useState<number | null>(
    defaultExportEpsg(exportItems),
  );
  const [exportFormat, setExportFormat] = useState<ExportFormat>("geojson");
  const [exportRunning, setExportRunning] = useState(false);
  const [exportProgress, setExportProgress] = useState(0);
  const [exportMessages, setExportMessages] = useState<string[]>([]);
  const [recommendedSymbolizations, setRecommendedSymbolizations] = useState<
    ResourceVisualizationSummary["recommendedSymbolizations"]
  >([]);
  const [
    recommendedSymbolizationsLoading,
    setRecommendedSymbolizationsLoading,
  ] = useState(false);
  const [recommendedSymbolizationsError, setRecommendedSymbolizationsError] =
    useState<string | null>(null);
  const [restoringRasterDefault, setRestoringRasterDefault] = useState(false);
  const recommendedRequestRef = useRef(0);
  const isDeferredSymbolization =
    isVectorSymbolization(symbolization) ||
    isRasterSymbolization(symbolization);
  const canPreviewRecommendedSymbolizations =
    isVectorSymbolization(symbolization) && Boolean(sourceResource);
  const canOpenSymbolization =
    canUseCustomSymbolization || canPreviewRecommendedSymbolizations;

  useEffect(() => {
    if (!symbolizationOpen) {
      setDraftSymbolization(symbolization);
    }
  }, [symbolization, symbolizationOpen]);

  function openSymbolizationModal() {
    if (!canOpenSymbolization) return;
    committedSymbolizationRef.current = symbolization;
    setDraftSymbolization(symbolization);
    setSymbolizationOpen(true);
    if (isVectorSymbolization(symbolization) && sourceResource) {
      void loadRecommendedSymbolizations(sourceResource);
    } else {
      setRecommendedSymbolizations([]);
      setRecommendedSymbolizationsError(null);
      setRecommendedSymbolizationsLoading(false);
    }
  }

  async function loadRecommendedSymbolizations(resource: ResourceListItem) {
    const requestId = recommendedRequestRef.current + 1;
    recommendedRequestRef.current = requestId;
    setRecommendedSymbolizationsLoading(true);
    setRecommendedSymbolizationsError(null);
    try {
      const summary = await api.resourceVisualizationSummary(resource);
      if (recommendedRequestRef.current !== requestId) return;
      setRecommendedSymbolizations(summary.recommendedSymbolizations ?? []);
    } catch (error) {
      if (recommendedRequestRef.current !== requestId) return;
      setRecommendedSymbolizations([]);
      setRecommendedSymbolizationsError(
        error instanceof Error
          ? error.message
          : i18n.t("layerPanel.recommendationFailed"),
      );
    } finally {
      if (recommendedRequestRef.current === requestId) {
        setRecommendedSymbolizationsLoading(false);
      }
    }
  }

  function closeSymbolizationModal() {
    const committedSymbolization = committedSymbolizationRef.current;
    if (
      isVectorSymbolization(committedSymbolization) &&
      isVectorSymbolization(draftSymbolization)
    ) {
      onSymbolizationChange(committedSymbolization);
      setDraftSymbolization(committedSymbolization);
    }
    setSymbolizationOpen(false);
  }

  function handleExportOpenChange(open: boolean) {
    if (open && !canExportData) {
      return;
    }
    setExportOpen(open);
    if (open) {
      setExportEpsg(defaultExportEpsg(exportItems));
      setExportProgress(0);
      setExportMessages([]);
    }
  }

  async function confirmExport() {
    const exportableItems = exportItems.filter(
      (item) => item.layerType === "vector" || item.datasetId,
    );
    if (exportableItems.length === 0) {
      message.warning(i18n.t("layerPanel.noExportData"));
      return;
    }
    if (exportReproject && !exportEpsg) {
      message.warning(i18n.t("layerPanel.enterTargetEpsg"));
      return;
    }
    if (exportClip && !ctx.exportClipGeometry) {
      message.warning(i18n.t("layerPanel.setSpatialExtent"));
      return;
    }
    setExportRunning(true);
    try {
      await ctx.exportLayers(
        exportableItems,
        {
          epsg: exportEpsg,
          reproject: exportReproject,
          clip: exportClip,
          clipGeometry: exportClip ? ctx.exportClipGeometry : null,
          format: exportFormat,
        },
        ({ percent, messages }) => {
          setExportProgress(percent);
          setExportMessages(messages);
        },
      );
      setExportOpen(false);
    } finally {
      setExportRunning(false);
    }
  }

  function applyDraftSymbolization() {
    if (!canUseCustomSymbolization) {
      return;
    }
    committedSymbolizationRef.current = draftSymbolization;
    onSymbolizationChange(draftSymbolization);
    setSymbolizationOpen(false);
  }

  async function restoreRasterDefaultSymbolization() {
    if (!sourceResource || !isRasterSymbolization(draftSymbolization)) return;
    setRestoringRasterDefault(true);
    try {
      const profile = await api.resourceProfile(sourceResource);
      if (!profile.raster?.defaultRules) {
        message.warning(i18n.t("layerPanel.noDefaultRasterStyle"));
        return;
      }
      setDraftSymbolization(
        rasterSymbolizationFromRules(profile.raster.defaultRules),
      );
      message.success(i18n.t("layerPanel.defaultStyleRestored"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : i18n.t("layerPanel.restoreDefaultFailed"),
      );
    } finally {
      setRestoringRasterDefault(false);
    }
  }

  function previewVectorSymbolization(next: VectorSymbolization) {
    if (!canUseCustomSymbolization) return;
    setDraftSymbolization(next);
    onSymbolizationChange(next);
  }

  function renderSymbolizationEditor() {
    if (isVectorSymbolization(draftSymbolization) && isDeferredSymbolization) {
      return (
        <VectorSymbolizationEditor
          value={draftSymbolization}
          fields={fields}
          fieldValueCounts={fieldValueCounts}
          geometryType={geometryType}
          recommendedSymbolizations={recommendedSymbolizations}
          recommendedSymbolizationsLoading={recommendedSymbolizationsLoading}
          recommendedSymbolizationsError={recommendedSymbolizationsError}
          readOnly={!canUseCustomSymbolization}
          canApplyRecommendedSymbolizations={canUseCustomSymbolization}
          onChange={
            canUseCustomSymbolization ? previewVectorSymbolization : () => {}
          }
          onApply={
            canUseCustomSymbolization ? applyDraftSymbolization : undefined
          }
        />
      );
    }
    if (isRasterSymbolization(draftSymbolization) && isDeferredSymbolization) {
      return (
        <RasterSymbolizationEditor
          value={draftSymbolization}
          bands={rasterBands}
          datasetId={rasterDatasetId}
          onRestoreDefault={restoreRasterDefaultSymbolization}
          restoringDefault={restoringRasterDefault}
          onChange={setDraftSymbolization}
          onApply={applyDraftSymbolization}
        />
      );
    }
    return null;
  }

  return (
    <>
      <div
        className="icon-cluster"
        role="toolbar"
        aria-label={i18n.t("layerPanel.layerActions", { name: subjectName })}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        {onOpenTable && (
          <LayerTooltip title={i18n.t("layerPanel.dataTable")}>
            <Button
              className="action-btn"
              type="text"
              size="small"
              aria-label={i18n.t("layerPanel.dataTableFor", {
                name: subjectName,
              })}
              icon={<TableOutlined style={{ fontSize: 14 }} />}
              onClick={onOpenTable}
            />
          </LayerTooltip>
        )}
        <LayerTooltip title={i18n.t("layerPanel.locate")}>
          <Button
            className="action-btn"
            type="text"
            size="small"
            aria-label={i18n.t("layerPanel.locateNamed", {
              name: subjectName,
            })}
            icon={<AimOutlined style={{ fontSize: 14 }} />}
            onClick={onLocate}
          />
        </LayerTooltip>
        {canExportData && (
          <Popover
            trigger="click"
            placement="leftTop"
            classNames={{ root: "symbolization-popover" }}
            open={exportOpen}
            onOpenChange={handleExportOpenChange}
            content={
              <ExportOptionsCard
                title={i18n.t("layerPanel.exportNamed", { name: subjectName })}
                epsg={exportEpsg}
                format={exportFormat}
                reproject={exportReproject}
                clip={exportClip}
                clipReady={Boolean(ctx.exportClipGeometry)}
                running={exportRunning}
                progress={exportProgress}
                messages={exportMessages}
                onEpsgChange={setExportEpsg}
                onFormatChange={setExportFormat}
                onReprojectChange={setExportReproject}
                onClipChange={setExportClip}
                onClearClip={ctx.clearExportClipGeometry}
                onExport={confirmExport}
              />
            }
          >
            <LayerTooltip title={i18n.t("layerPanel.export")}>
              <Button
                className="action-btn"
                type="text"
                size="small"
                aria-label={i18n.t("layerPanel.exportNamedLabel", {
                  name: subjectName,
                })}
                icon={<DownloadOutlined style={{ fontSize: 14 }} />}
              />
            </LayerTooltip>
          </Popover>
        )}
        {canOpenSymbolization && (
          <LayerTooltip
            title={
              canUseCustomSymbolization
                ? i18n.t("layerPanel.symbolization")
                : i18n.t("layerPanel.recommendationPreview")
            }
          >
            <Button
              className={`action-btn symbolization-action-btn${
                symbolizationOpen ? " is-active" : ""
              }`}
              type="text"
              size="small"
              aria-label={
                canUseCustomSymbolization
                  ? i18n.t("layerPanel.symbolizationFor", {
                      name: subjectName,
                    })
                  : i18n.t("layerPanel.recommendationFor", {
                      name: subjectName,
                    })
              }
              aria-expanded={symbolizationOpen}
              aria-haspopup="dialog"
              icon={<BgColorsOutlined style={{ fontSize: 14 }} />}
              onClick={openSymbolizationModal}
            />
          </LayerTooltip>
        )}
        <LayerTooltip title={i18n.t("layerPanel.remove")}>
          <Button
            className="action-btn"
            type="text"
            size="small"
            aria-label={i18n.t("layerPanel.removeNamed", { name: subjectName })}
            icon={<DeleteOutlined style={{ fontSize: 14 }} />}
            onClick={onRemove}
          />
        </LayerTooltip>
      </div>
      {canOpenSymbolization && (
        <Modal
          title={
            canUseCustomSymbolization
              ? i18n.t("layerPanel.symbolizationFor", { name: subjectName })
              : i18n.t("layerPanel.recommendationFor", { name: subjectName })
          }
          open={symbolizationOpen}
          footer={null}
          width="min(760px, calc(100vw - 32px))"
          wrapClassName="layer-symbolization-modal"
          onCancel={closeSymbolizationModal}
          destroyOnHidden
        >
          <Suspense fallback={<Spin />}>{renderSymbolizationEditor()}</Suspense>
        </Modal>
      )}
    </>
  );
}

function isVectorSymbolization(
  value: GroupSymbolization | VectorSymbolization | RasterSymbolization,
): value is VectorSymbolization {
  return "pointMode" in value;
}

function isRasterSymbolization(
  value: GroupSymbolization | VectorSymbolization | RasterSymbolization,
): value is RasterSymbolization {
  return "mode" in value && "bands" in value;
}

function exportItemsForGroup(group: LoadedLayerGroup): ExportLayerItem[] {
  return group.children.flatMap((layer) => exportItemsForLayer(layer));
}

function exportItemsForLayer(layer: LoadedLayer): ExportLayerItem[] {
  if (layer.layerType === "vector") {
    return [
      {
        layerType: "vector",
        name: layer.name,
        resourceId: resourceExportId(layer.sourceResource),
        geojson: layer.geojson,
        sourceCrs: layer.sourceResource.coordinateSystem,
      },
    ];
  }
  return [
    {
      layerType: "raster",
      name: layer.name,
      resourceId: resourceExportId(layer.sourceResource),
      datasetId: layer.rasterDatasetId,
      sourceCrs:
        layer.rasterMetadata?.coordinateSystem ??
        layer.sourceResource.coordinateSystem,
    },
  ];
}

function ExportOptionsCard({
  title,
  epsg,
  format,
  reproject,
  clip,
  clipReady,
  running,
  progress,
  messages,
  onEpsgChange,
  onFormatChange,
  onReprojectChange,
  onClipChange,
  onClearClip,
  onExport,
}: {
  title: string;
  epsg: number | null;
  format: ExportFormat;
  reproject: boolean;
  clip: boolean;
  clipReady: boolean;
  running: boolean;
  progress: number;
  messages: string[];
  onEpsgChange: (value: number | null) => void;
  onFormatChange: (value: ExportFormat) => void;
  onReprojectChange: (value: boolean) => void;
  onClipChange: (value: boolean) => void;
  onClearClip: () => void;
  onExport: () => void;
}) {
  const latestMessage =
    messages.length > 0 ? messages[messages.length - 1] : "";
  return (
    <Card className="symbolization-card export-card" size="small" title={title}>
      <Space orientation="vertical" className="full-width symbolization-stack">
        <div className="export-option-row">
          <Typography.Text strong>
            {i18n.t("layerPanel.vectorFormat")}
          </Typography.Text>
          <Segmented<ExportFormat>
            size="small"
            value={format}
            options={[
              { label: "GeoJSON", value: "geojson" },
              { label: "Shapefile", value: "shapefile" },
            ]}
            onChange={onFormatChange}
          />
        </div>
        <div className="export-option-row">
          <Typography.Text strong>
            {i18n.t("layerPanel.reproject")}
          </Typography.Text>
          <Switch checked={reproject} onChange={onReprojectChange} />
        </div>
        <label className="export-epsg-field" htmlFor="export-epsg-input">
          <span>{i18n.t("layerPanel.targetEpsg")}</span>
          <InputNumber
            id="export-epsg-input"
            className="full-width"
            min={1024}
            max={999999}
            value={epsg}
            disabled={!reproject}
            onChange={(value) =>
              onEpsgChange(typeof value === "number" ? value : null)
            }
          />
        </label>
        <div className="export-option-row">
          <Typography.Text strong>{i18n.t("layerPanel.clip")}</Typography.Text>
          <Switch checked={clip} onChange={onClipChange} />
        </div>
        {clip && (
          <Space orientation="vertical" className="full-width compact-stack">
            <div className="export-clip-actions">
              <Typography.Text type={clipReady ? "success" : "secondary"}>
                {clipReady
                  ? i18n.t("layerPanel.extentSet")
                  : i18n.t("layerPanel.setExtentInDrawing")}
              </Typography.Text>
              <Button size="small" onClick={onClearClip} disabled={!clipReady}>
                {i18n.t("common.clear")}
              </Button>
            </div>
          </Space>
        )}
        {running && (
          <Space orientation="vertical" className="full-width compact-stack">
            <Progress percent={progress} size="small" />
            {latestMessage && (
              <Alert type="info" showIcon title={latestMessage} />
            )}
          </Space>
        )}
        <Button
          type="primary"
          icon={<DownloadOutlined style={{ fontSize: 15 }} />}
          loading={running}
          disabled={running || (clip && !clipReady)}
          onClick={onExport}
        >
          {i18n.t("layerPanel.export")}
        </Button>
      </Space>
    </Card>
  );
}

function defaultExportEpsg(items: ExportLayerItem[]) {
  for (const item of items) {
    const epsg = parseEpsg(item.sourceCrs);
    if (epsg) return epsg;
  }
  return 4326;
}

function parseEpsg(value: string | number | null | undefined) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const match = String(value ?? "").match(/EPSG[:\s-]*(\d{4,6})/i);
  return match ? Number(match[1]) : null;
}
