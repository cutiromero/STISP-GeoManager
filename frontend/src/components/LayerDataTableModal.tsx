import { DatabaseOutlined, EyeInvisibleOutlined } from "@ant-design/icons";
import type { TableColumnsType } from "antd";
import {
  Button,
  Checkbox,
  Descriptions,
  Dropdown,
  Empty,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type React from "react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { LoadedLayer, LoadedVectorLayer } from "../types";

interface Props {
  layer: LoadedLayer | null;
  open: boolean;
  onClose: () => void;
  onSelectionChange?: (featureIds: (string | number)[]) => void;
}

export default function LayerDataTableModal({
  layer,
  open,
  onClose,
  onSelectionChange,
}: Props) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  return (
    <Modal
      title={
        layer
          ? english
            ? `${layer.name} data table`
            : `${layer.name} 数据表`
          : english
            ? "Data table"
            : "数据表"
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width="min(1100px, calc(100vw - 48px))"
      styles={{ body: { padding: 0 } }}
      destroyOnHidden
    >
      {!layer ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={english ? "Select a layer" : "请选择图层"}
          style={{ padding: 24 }}
        />
      ) : layer.layerType === "vector" ? (
        <VectorAttributeTable
          layer={layer}
          onSelectionChange={onSelectionChange}
        />
      ) : (
        <Descriptions size="small" column={2} bordered style={{ padding: 16 }}>
          <Descriptions.Item label={english ? "Layer" : "图层"}>
            {layer.name}
          </Descriptions.Item>
          <Descriptions.Item label={english ? "Type" : "类型"}>
            {english ? "Raster" : "栅格"}
          </Descriptions.Item>
          <Descriptions.Item label={english ? "Band count" : "波段数"}>
            {layer.rasterMetadata?.bands.length ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label={english ? "Status" : "状态"}>
            {layer.renderStatus || (english ? "Default" : "默认")}
          </Descriptions.Item>
        </Descriptions>
      )}
    </Modal>
  );
}

interface RowData {
  __rowKey: string;
  __featureIndex: number;
}

const defaultDataColumnWidth = 160;
const minDataColumnWidth = 88;
const indexColumnPaddingWidth = 38;
const indexDigitWidth = 9;
const maxFilterFieldCount = 24;
const maxColumnFilterValues = 50;

function VectorAttributeTable({
  layer,
  onSelectionChange,
}: {
  layer: LoadedVectorLayer;
  onSelectionChange?: (featureIds: (string | number)[]) => void;
}) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const fieldNames = useMemo(
    () =>
      layer.fields.length
        ? layer.fields.map((field) => field.name)
        : inferPropertyNames(layer),
    [layer],
  );
  const rows = useMemo(() => buildTableRows(layer), [layer]);

  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set());
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  const toggleHidden = (key: string) => {
    setHiddenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const visibleFieldNames = useMemo(
    () => fieldNames.filter((n) => !hiddenKeys.has(n)),
    [fieldNames, hiddenKeys],
  );
  const indexColumnWidth = Math.max(
    48,
    String(Math.max(rows.length, 1)).length * indexDigitWidth +
      indexColumnPaddingWidth,
  );
  const resizeColumn = useCallback((key: string, width: number) => {
    setColumnWidths((prev) => ({ ...prev, [key]: width }));
  }, []);
  const selectedKeySet = useMemo(
    () => new Set(selectedRowKeys),
    [selectedRowKeys],
  );
  const fieldByName = useMemo(
    () => new Map(layer.fields.map((field) => [field.name, field])),
    [layer.fields],
  );
  const columnFilters = useMemo(
    () => buildColumnFilterMap(layer, visibleFieldNames),
    [layer, visibleFieldNames],
  );

  const handleSelectionChange = useCallback(
    (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys);

      if (onSelectionChange) {
        const featureIds = newSelectedRowKeys
          .map((key) => extractFeatureIdFromRowKey(String(key)))
          .filter((id): id is string | number => id !== null);
        onSelectionChange(featureIds);
      }
    },
    [onSelectionChange],
  );

  const rowSelection = {
    selectedRowKeys,
    onChange: handleSelectionChange,
    columnWidth: 40,
    selections: [
      Table.SELECTION_ALL,
      Table.SELECTION_INVERT,
      Table.SELECTION_NONE,
    ],
  };

  const columns: TableColumnsType<RowData> = useMemo(() => {
    const indexCol: TableColumnsType<RowData>[number] = {
      title: "#",
      key: "__index",
      width: indexColumnWidth,
      fixed: "left",
      rowSpan: 2,
      render: (_, __, index) => index + 1,
      onCell: (record) => ({
        className: selectedKeySet.has(record.__rowKey)
          ? "layer-table-cell-selected"
          : "",
      }),
    };

    const dataCols: TableColumnsType<RowData> = visibleFieldNames.map(
      (fieldName) => {
        const field = fieldByName.get(fieldName);
        const hasDescription =
          field?.description && field.description.trim() !== "";
        const sorter = (a: RowData, b: RowData) => {
          const va = String(getCellValue(layer, a, fieldName) ?? "");
          const vb = String(getCellValue(layer, b, fieldName) ?? "");
          return va.localeCompare(vb, "zh-CN", { numeric: true });
        };
        const onFilter = (value: boolean | React.Key, record: RowData) =>
          String(getCellValue(layer, record, fieldName) ?? "").includes(
            String(value),
          );
        const render = (_: unknown, record: RowData) =>
          String(getCellValue(layer, record, fieldName) ?? "-");

        return {
          title: fieldName,
          key: fieldName,
          width: columnWidths[fieldName] ?? defaultDataColumnWidth,
          ellipsis: true,
          onCell: (record: RowData) => ({
            className: selectedKeySet.has(record.__rowKey)
              ? "layer-table-cell-selected"
              : "",
          }),
          onHeaderCell: () =>
            ({
              width: columnWidths[fieldName] ?? defaultDataColumnWidth,
              onResize: (width: number) => resizeColumn(fieldName, width),
            }) as React.ThHTMLAttributes<HTMLTableCellElement>,
          // 如果有描述，使用children实现两层表头
          ...(hasDescription
            ? {
                children: [
                  {
                    title: field.description,
                    key: `${fieldName}__desc`,
                    width: columnWidths[fieldName] ?? defaultDataColumnWidth,
                    ellipsis: true,
                    sorter,
                    filters: columnFilters.get(fieldName) ?? [],
                    onFilter,
                    filterSearch: true,
                    render,
                    onCell: (record: RowData) => ({
                      className: selectedKeySet.has(record.__rowKey)
                        ? "layer-table-cell-selected"
                        : "",
                    }),
                  },
                ],
              }
            : {
                sorter,
                filters: columnFilters.get(fieldName) ?? [],
                onFilter,
                filterSearch: true,
                render,
              }),
        };
      },
    );

    return [indexCol, ...dataCols];
  }, [
    columnWidths,
    fieldByName,
    indexColumnWidth,
    layer,
    resizeColumn,
    selectedKeySet,
    visibleFieldNames,
    columnFilters,
  ]);
  const tableScrollX = Math.max(
    960,
    indexColumnWidth +
      visibleFieldNames.reduce(
        (total, name) => total + (columnWidths[name] ?? defaultDataColumnWidth),
        0,
      ),
  );
  const hasSelected = selectedRowKeys.length > 0;

  return (
    <div className="layer-table-modal-content">
      <div className="bottom-table-heading">
        <Space size={8}>
          <DatabaseOutlined style={{ fontSize: 15 }} />
          <Typography.Text strong>{layer.name}</Typography.Text>
          <Tag color="green">
            {english ? `${rows.length} records` : `${rows.length} 条`}
          </Tag>
          {hasSelected && (
            <Tag color="blue">
              {english
                ? `${selectedRowKeys.length} selected`
                : `已选 ${selectedRowKeys.length} 条`}
            </Tag>
          )}
        </Space>
        <Space size={8}>
          <Dropdown
            menu={{
              items: fieldNames.map((name) => ({
                key: name,
                label: (
                  <Checkbox
                    checked={!hiddenKeys.has(name)}
                    onChange={() => toggleHidden(name)}
                  >
                    {name}
                  </Checkbox>
                ),
              })),
            }}
            trigger={["click"]}
          >
            <Button
              size="small"
              icon={<EyeInvisibleOutlined style={{ fontSize: 14 }} />}
            >
              {english ? "Show/hide columns" : "列显隐"}
            </Button>
          </Dropdown>
          <Typography.Text type="secondary">{layer.summary}</Typography.Text>
        </Space>
      </div>
      <Table<RowData>
        virtual
        size="small"
        rowKey="__rowKey"
        dataSource={rows}
        columns={columns}
        rowSelection={rowSelection}
        rowClassName={(record) =>
          selectedKeySet.has(record.__rowKey) ? "layer-table-row-selected" : ""
        }
        components={{ header: { cell: ResizableHeaderCell } }}
        pagination={false}
        scroll={{ x: tableScrollX, y: 460 }}
        showSorterTooltip={{ target: "sorter-icon" }}
      />
    </div>
  );
}

function buildColumnFilters(
  layer: LoadedVectorLayer,
  fieldName: string,
): { text: string; value: string }[] {
  const unique = new Set<string>();
  for (const feature of layer.geojson.features) {
    const val = String(getFeatureProperties(feature)[fieldName] ?? "");
    if (val) unique.add(val);
    if (unique.size >= maxColumnFilterValues) break;
  }
  const values = Array.from(unique);
  return values.map((v) => ({ text: v, value: v }));
}

function buildColumnFilterMap(layer: LoadedVectorLayer, fieldNames: string[]) {
  const result = new Map<string, { text: string; value: string }[]>();
  for (const fieldName of fieldNames.slice(0, maxFilterFieldCount)) {
    result.set(fieldName, buildColumnFilters(layer, fieldName));
  }
  return result;
}

interface ResizableHeaderCellProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  width?: number;
  onResize?: (width: number) => void;
}

function ResizableHeaderCell({
  width,
  onResize,
  children,
  ...restProps
}: ResizableHeaderCellProps) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  // 如果没有onResize，直接使用默认的header cell（如checkbox列）
  if (!onResize) {
    return <th {...restProps}>{children}</th>;
  }

  function handleResizeStart(event: React.MouseEvent<HTMLSpanElement>) {
    if (!width) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = width;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    let resizeFrame: number | null = null;
    let pendingWidth = width;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const flushResize = () => {
      resizeFrame = null;
      onResize?.(pendingWidth);
    };
    const handleMouseMove = (moveEvent: MouseEvent) => {
      pendingWidth = Math.max(
        minDataColumnWidth,
        startWidth + moveEvent.clientX - startX,
      );
      if (resizeFrame === null) {
        resizeFrame = window.requestAnimationFrame(flushResize);
      }
    };
    const handleMouseUp = () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      if (resizeFrame !== null) {
        window.cancelAnimationFrame(resizeFrame);
        resizeFrame = null;
      }
      onResize?.(pendingWidth);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  }

  return (
    <th {...restProps} style={{ ...restProps.style, width }}>
      <div className="resizable-table-header">
        <span className="resizable-table-title">{children}</span>
        <Button
          type="text"
          aria-label={english ? "Resize column" : "调整列宽"}
          className="resizable-table-handle"
          onMouseDown={handleResizeStart}
        />
      </div>
    </th>
  );
}

function inferPropertyNames(layer: LoadedVectorLayer) {
  const names = new Set<string>();
  for (const feature of layer.geojson.features) {
    const properties = (feature as { properties?: Record<string, unknown> })
      .properties;
    for (const name of Object.keys(properties ?? {})) {
      names.add(name);
    }
  }
  return Array.from(names);
}

function buildTableRows(layer: LoadedVectorLayer) {
  const keyCounts = new Map<string, number>();
  return layer.geojson.features.map((feature, index) => {
    const baseKey = stableFeatureKey(feature, index);
    const count = keyCounts.get(baseKey) ?? 0;
    keyCounts.set(baseKey, count + 1);
    return {
      __rowKey: count ? `${baseKey}::${count}` : baseKey,
      __featureIndex: index,
    };
  });
}

function getFeatureProperties(feature: unknown): Record<string, unknown> {
  return (feature as { properties?: Record<string, unknown> }).properties ?? {};
}

function getCellValue(
  layer: LoadedVectorLayer,
  row: RowData,
  fieldName: string,
) {
  const feature = layer.geojson.features[row.__featureIndex];
  return feature ? getFeatureProperties(feature)[fieldName] : undefined;
}

function stableFeatureKey(feature: Record<string, unknown>, index: number) {
  const featureId = feature.id;
  if (typeof featureId === "string" || typeof featureId === "number") {
    return `feature-id-${featureId}`;
  }
  return `feature-index-${index}`;
}

function extractFeatureIdFromRowKey(rowKey: string): string | number | null {
  const normalizedRowKey = rowKey.split("::")[0] ?? rowKey;
  const match = normalizedRowKey.match(/^feature-id-(.+)$/);
  if (!match) return null;

  const idStr = match[1];
  if (!idStr) return null;
  // 尝试解析为数字
  const numId = Number(idStr);
  if (!Number.isNaN(numId) && String(numId) === idStr) {
    return numId;
  }
  // 否则作为字符串返回
  return idStr;
}
