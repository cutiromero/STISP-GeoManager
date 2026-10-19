import { ProjectLabel } from "../projects/ProjectLabel";
import { useProjectContext } from "../projects/ProjectContext";
import {
  CheckCircleOutlined,
  FileSearchOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  Descriptions,
  Empty,
  Form,
  Input,
  Result,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type {
  DataDomainType,
  DataSchemaSummary,
  ImportValidationIssue,
  VectorImportCommitResult,
  VectorImportPreview,
  VectorImportValidateResult,
} from "../types";

type DomainDefinition = DataSchemaSummary["domains"][number];

type AccessGroup = {
  id: number;
  name: string;
  isGuest?: boolean;
};

type VectorImportFormValues = {
  name: string;
  domainType: DataDomainType;
  categoryCode: string;
  sourceLayerName: string;
  tableName: string;
  encoding?: string;
  sourceCrs?: string;
  repairInvalidGeometries: boolean;
  skipInvalidGeometries: boolean;
  accessGroupIds: number[];
  duplicateConfirmed: boolean;
};

export default function VectorImportWorkflow({
  projectTagId = 1,
  file,
  categoryOptions,
  onReset,
  onCompleted,
}: {
  projectTagId?: number;
  file: File;
  domainDefinitions: DomainDefinition[];
  categoryOptions: Array<{ value: string; label: string }>;
  availableAccessGroups: AccessGroup[];
  onReset: () => void;
  onCompleted: (result: VectorImportCommitResult) => void;
}) {
  const { message } = AntApp.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const l = (zh: string, en: string) => (english ? en : zh);
  const navigate = useNavigate();
  const projectContext = useProjectContext();
  const [form] = Form.useForm<VectorImportFormValues>();
  const [preview, setPreview] = useState<VectorImportPreview | null>(null);
  const [validation, setValidation] =
    useState<VectorImportValidateResult | null>(null);
  const [result, setResult] = useState<VectorImportCommitResult | null>(null);
  const [fieldMetadata, setFieldMetadata] = useState<Record<string, string>>(
    {},
  );
  const [previewing, setPreviewing] = useState(true);
  const [validating, setValidating] = useState(false);
  const [importing, setImporting] = useState(false);
  const selectedLayerName = Form.useWatch("sourceLayerName", form);
  const selectedLayer = useMemo(
    () =>
      preview?.layers.find(
        (layer) => layer.sourceLayerName === selectedLayerName,
      ) ?? preview?.layers[0],
    [preview, selectedLayerName],
  );
  const blockingIssues =
    validation?.validationIssues.filter((issue) => issue.blocking) ?? [];

  useEffect(() => {
    let ignore = false;
    setPreviewing(true);
    api
      .previewVectorImport(file, undefined, projectTagId)
      .then((value) => {
        if (ignore) return;
        setPreview(value);
        const layer = value.layers[0];
        if (!layer) return;
        setFieldMetadata(
          Object.fromEntries(layer.fields.map((field) => [field.name, ""])),
        );
        form.setFieldsValue({
          name: layer.suggestedName,
          domainType: "vector",
          categoryCode: "spatial",
          sourceLayerName: layer.sourceLayerName,
          tableName: layer.suggestedTableName,
          encoding: layer.encoding ?? undefined,
          sourceCrs: undefined,
          repairInvalidGeometries: false,
          skipInvalidGeometries: false,
          accessGroupIds: [],
          duplicateConfirmed: false,
        });
      })
      .catch((error) => {
        if (!ignore) {
          setPreview(null);
          setValidation(null);
          form.setFields([
            {
              name: "sourceLayerName",
              errors: [
                error instanceof Error
                  ? error.message
                  : l("矢量预检失败", "Vector preflight failed"),
              ],
            },
          ]);
          message.error(
            error instanceof Error
              ? error.message
              : l("矢量预检失败", "Vector preflight failed"),
          );
        }
      })
      .finally(() => {
        if (!ignore) setPreviewing(false);
      });
    return () => {
      ignore = true;
    };
  }, [file, form, message, projectTagId]);

  function handleLayerChange(sourceLayerName: string) {
    const layer = preview?.layers.find(
      (item) => item.sourceLayerName === sourceLayerName,
    );
    if (!layer) return;
    setValidation(null);
    setFieldMetadata(
      Object.fromEntries(layer.fields.map((field) => [field.name, ""])),
    );
    form.setFieldsValue({
      sourceLayerName,
      name: layer.suggestedName,
      tableName: layer.suggestedTableName,
      encoding: layer.encoding ?? undefined,
      sourceCrs: undefined,
      duplicateConfirmed: false,
    });
  }

  async function handleEncodingPreview() {
    const encoding = form.getFieldValue("encoding");
    setPreviewing(true);
    setValidation(null);
    try {
      const value = await api.previewVectorImport(file, encoding, projectTagId);
      setPreview(value);
      const preferred =
        value.layers.find(
          (layer) => layer.sourceLayerName === selectedLayerName,
        ) ?? value.layers[0];
      if (preferred) {
        setFieldMetadata(
          Object.fromEntries(preferred.fields.map((field) => [field.name, ""])),
        );
        form.setFieldsValue({
          sourceLayerName: preferred.sourceLayerName,
          name: preferred.suggestedName,
          tableName: preferred.suggestedTableName,
          encoding: preferred.encoding ?? encoding ?? undefined,
          sourceCrs: undefined,
          duplicateConfirmed: false,
        });
      }
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l(
              "按指定编码预检失败",
              "Preflight with the specified encoding failed",
            ),
      );
    } finally {
      setPreviewing(false);
    }
  }

  async function handleValidate() {
    const values = await form.validateFields();
    setValidating(true);
    try {
      const value = await api.validateVectorImport(
        file,
        {
          name: values.name.trim(),
          sourceLayerName: values.sourceLayerName,
          tableName: values.tableName.trim(),
          encoding: values.encoding?.trim() || null,
          sourceCrs: values.sourceCrs?.trim() || null,
          repairInvalidGeometries: values.repairInvalidGeometries,
          skipInvalidGeometries: values.skipInvalidGeometries,
        },
        projectTagId,
      );
      setValidation(value);
      form.setFieldValue("duplicateConfirmed", false);
      if (value.validationIssues.some((issue) => issue.blocking)) {
        message.warning(
          l(
            "校验完成，仍存在阻断导入的问题",
            "Validation completed with issues that block import",
          ),
        );
      } else {
        message.success(
          l(
            "矢量数据校验通过，可以提交导入",
            "Vector validation passed; the import can be submitted",
          ),
        );
      }
    } catch (error) {
      const issues = vectorIssuesFromError(error);
      if (issues.length && selectedLayer) {
        setValidation({
          layer: selectedLayer,
          validationIssues: issues,
          duplicateTarget: null,
        });
      }
      message.error(
        error instanceof Error
          ? error.message
          : l("矢量校验失败", "Vector validation failed"),
      );
    } finally {
      setValidating(false);
    }
  }

  async function handleCommit() {
    const values = await form.validateFields();
    if (!validation) {
      await handleValidate();
      return;
    }
    if (blockingIssues.length > 0) {
      return;
    }
    if (validation.duplicateTarget && !values.duplicateConfirmed) {
      form.setFields([
        {
          name: "duplicateConfirmed",
          errors: [
            l(
              "请确认创建同名数据资源",
              "Confirm creation of a data resource with the same name",
            ),
          ],
        },
      ]);
      return;
    }
    setImporting(true);
    try {
      const imported = await api.commitVectorImport(
        file,
        {
          name: values.name.trim(),
          domainType: "vector",
          categoryCode: values.categoryCode,
          sourceLayerName: values.sourceLayerName,
          tableName: values.tableName.trim(),
          encoding: values.encoding?.trim() || null,
          sourceCrs: values.sourceCrs?.trim() || null,
          repairInvalidGeometries: values.repairInvalidGeometries,
          skipInvalidGeometries: values.skipInvalidGeometries,
          duplicateConfirmed: values.duplicateConfirmed,
          accessGroupIds: values.accessGroupIds ?? [],
          fieldMetadata,
        },
        projectTagId,
      );
      setResult(imported);
      onCompleted(imported);
      message.success(l("矢量数据导入完成", "Vector data import completed"));
    } catch (error) {
      const issues = vectorIssuesFromError(error);
      if (issues.length && selectedLayer) {
        setValidation({
          layer: selectedLayer,
          validationIssues: issues,
          duplicateTarget: validation?.duplicateTarget ?? null,
        });
      }
      message.error(
        error instanceof Error
          ? error.message
          : l("矢量导入失败", "Vector import failed"),
      );
    } finally {
      setImporting(false);
    }
  }

  if (result) {
    return (
      <Result
        status="success"
        title={l("矢量数据导入完成", "Vector data import completed")}
        subTitle={l(
          `${result.resourceName} 已写入 GeoPackage，共导入 ${result.importedFeatures} 个要素，跳过 ${result.skippedFeatures} 个要素。`,
          `${result.resourceName} was written to GeoPackage. ${result.importedFeatures} features were imported and ${result.skippedFeatures} were skipped.`,
        )}
        extra={[
          <Button key="again" icon={<ReloadOutlined />} onClick={onReset}>
            {l("继续导入", "Import another file")}
          </Button>,
          <Button
            key="map"
            type="primary"
            onClick={() => {
              const open = () => navigate("/map");
              if (projectContext)
                projectContext.choose(String(projectTagId), open);
              else open();
            }}
          >
            {l("进入地理数据界面", "Open geo workspace")}
          </Button>,
        ]}
      />
    );
  }

  return (
    <div className="import-config-form">
      <Space className="import-actions import-actions-top">
        <Button onClick={onReset}>
          {l("重新选择文件", "Choose another file")}
        </Button>
        <Button
          icon={<FileSearchOutlined />}
          loading={validating}
          disabled={!preview || previewing}
          onClick={handleValidate}
        >
          {l("校验矢量数据", "Validate vector data")}
        </Button>
        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          loading={importing}
          disabled={!validation || blockingIssues.length > 0}
          onClick={handleCommit}
        >
          {l("提交导入", "Submit import")}
        </Button>
      </Space>

      <Alert
        type="info"
        showIcon
        title={l(
          "矢量文件将保留原始归档，并标准化写入统一 GeoPackage",
          "Vector source files are archived and standardized in the shared GeoPackage",
        )}
        description={l(
          "Shapefile ZIP 会检查组件完整性和中文编码；所有可上图几何统一转换为 EPSG:4326，导入成功后自动创建数据资源和地图图层。",
          "Shapefile ZIP packages are checked for component completeness and attribute encoding. Mappable geometry is converted to EPSG:4326, and a data resource and map layer are created after a successful import.",
        )}
      />

      {previewing && (
        <Alert
          type="info"
          showIcon
          title={l(
            "正在解析矢量图层和几何质量…",
            "Inspecting vector layers and geometry quality…",
          )}
        />
      )}

      {preview && selectedLayer ? (
        <Form<VectorImportFormValues>
          form={form}
          layout="vertical"
          onValuesChange={(changed) => {
            if (!("duplicateConfirmed" in changed)) {
              setValidation(null);
            }
          }}
        >
          <section className="import-section">
            <Typography.Title level={5}>
              {l("源文件与图层", "Source file and layer")}
            </Typography.Title>
            <Descriptions bordered size="small" column={3}>
              <Descriptions.Item label={l("文件名", "File name")}>
                {preview.sourceFileName}
              </Descriptions.Item>
              <Descriptions.Item label={l("源格式", "Source format")}>
                {preview.sourceFormat}
              </Descriptions.Item>
              <Descriptions.Item label={l("图层数量", "Layer count")}>
                {preview.layers.length}
              </Descriptions.Item>
            </Descriptions>
            <Form.Item
              name="sourceLayerName"
              label={l("选择源图层", "Source layer")}
              rules={[
                {
                  required: true,
                  message: l("请选择源图层", "Select a source layer"),
                },
              ]}
            >
              <Select
                options={preview.layers.map((layer) => ({
                  value: layer.sourceLayerName,
                  label: l(
                    `${layer.sourceLayerName} / ${layer.geometryType} / ${layer.featureCount} 要素`,
                    `${layer.sourceLayerName} / ${layer.geometryType} / ${layer.featureCount} features`,
                  ),
                }))}
                onChange={handleLayerChange}
              />
            </Form.Item>
          </section>

          <section className="import-section">
            <Typography.Title level={5}>
              {l("技术预检", "Technical preflight")}
            </Typography.Title>
            <Descriptions bordered size="small" column={4}>
              <Descriptions.Item label={l("几何类型", "Geometry type")}>
                {selectedLayer.geometryType || "-"}
              </Descriptions.Item>
              <Descriptions.Item label={l("要素数", "Features")}>
                {selectedLayer.featureCount}
              </Descriptions.Item>
              <Descriptions.Item label={l("顶点数", "Vertices")}>
                {selectedLayer.vertexCount}
              </Descriptions.Item>
              <Descriptions.Item label={l("坐标系", "CRS")}>
                {selectedLayer.coordinateSystem ?? l("未声明", "Not declared")}
              </Descriptions.Item>
              <Descriptions.Item label={l("有效几何", "Valid geometry")}>
                {selectedLayer.quality.validCount}
              </Descriptions.Item>
              <Descriptions.Item label={l("无效几何", "Invalid geometry")}>
                {selectedLayer.quality.invalidCount}
              </Descriptions.Item>
              <Descriptions.Item label={l("空几何", "Empty geometry")}>
                {selectedLayer.quality.emptyCount}
              </Descriptions.Item>
              <Descriptions.Item label={l("null 几何", "Null geometry")}>
                {selectedLayer.quality.nullCount}
              </Descriptions.Item>
            </Descriptions>
          </section>

          <section className="import-section">
            <Typography.Title level={5}>
              {l("入库配置", "Storage configuration")}
            </Typography.Title>
            <div className="import-config-grid">
              <Form.Item
                name="name"
                label={l("数据资源名称", "Data resource name")}
                rules={[
                  {
                    required: true,
                    message: l(
                      "请输入数据资源名称",
                      "Enter a data resource name",
                    ),
                  },
                ]}
              >
                <Input />
              </Form.Item>
              <Form.Item
                name="tableName"
                label={l("GeoPackage 图层标识", "GeoPackage layer identifier")}
                rules={[
                  {
                    required: true,
                    message: l("请输入图层标识", "Enter a layer identifier"),
                  },
                ]}
              >
                <Input />
              </Form.Item>
              <Form.Item
                name="categoryCode"
                label={l("数据分类", "Data category")}
                rules={[
                  {
                    required: true,
                    message: l(
                      "请选择数据分类",
                      "Select an authoritative category",
                    ),
                  },
                ]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  disabled
                  options={categoryOptions}
                />
              </Form.Item>

              <ProjectLabel id={projectTagId} />
              <Form.Item
                name="encoding"
                label={l("Shapefile 属性编码", "Shapefile attribute encoding")}
              >
                <Input
                  placeholder={l(
                    "例如 GB18030；GeoJSON/GPKG 可留空",
                    "Example: GB18030; leave empty for GeoJSON/GPKG",
                  )}
                />
              </Form.Item>
              <Form.Item
                label={l(
                  "按当前编码重新预检",
                  "Repeat preflight with this encoding",
                )}
              >
                <Button loading={previewing} onClick={handleEncodingPreview}>
                  {l("重新解析属性", "Reparse attributes")}
                </Button>
              </Form.Item>
              <Form.Item
                name="sourceCrs"
                label={l("人工指定源坐标系", "Override source CRS")}
                tooltip={l(
                  "仅在文件没有 .prj 或无法识别 CRS 时填写，例如 EPSG:4326",
                  "Only set this when the file has no .prj or its CRS cannot be identified, for example EPSG:4326",
                )}
              >
                <Input
                  placeholder={l("例如 EPSG:4326", "Example: EPSG:4326")}
                />
              </Form.Item>
            </div>
            <Space orientation="vertical">
              <Form.Item name="repairInvalidGeometries" valuePropName="checked">
                <Checkbox>
                  {l(
                    "尝试使用 make_valid 修复无效几何",
                    "Attempt to repair invalid geometry with make_valid",
                  )}
                </Checkbox>
              </Form.Item>
              <Form.Item name="skipInvalidGeometries" valuePropName="checked">
                <Checkbox>
                  {l(
                    "跳过修复后仍无效、空或 null 的几何",
                    "Skip geometry that remains invalid, empty, or null after repair",
                  )}
                </Checkbox>
              </Form.Item>
            </Space>
          </section>

          <section className="import-section">
            <Typography.Title level={5}>
              {l(
                "字段说明与属性预览",
                "Field descriptions and attribute preview",
              )}
            </Typography.Title>
            <Table
              size="small"
              pagination={false}
              rowKey="name"
              dataSource={selectedLayer.fields}
              columns={[
                { title: l("字段", "Field"), dataIndex: "name", key: "name" },
                { title: l("类型", "Type"), dataIndex: "type", key: "type" },
                {
                  title: l("样例", "Samples"),
                  key: "samples",
                  render: (_, field) => field.sampleValues.join("、") || "-",
                },
                {
                  title: l("中文说明", "Field description"),
                  key: "description",
                  render: (_, field) => (
                    <Input
                      value={fieldMetadata[field.name] ?? ""}
                      onChange={(event) =>
                        setFieldMetadata((current) => ({
                          ...current,
                          [field.name]: event.target.value,
                        }))
                      }
                    />
                  ),
                },
              ]}
            />
          </section>

          {validation && (
            <section className="import-section">
              <Typography.Title level={5}>
                {l("校验结果", "Validation results")}
              </Typography.Title>
              {validation.validationIssues.length === 0 ? (
                <Alert
                  type="success"
                  showIcon
                  title={l("矢量数据校验通过", "Vector validation passed")}
                />
              ) : (
                <Space orientation="vertical" style={{ width: "100%" }}>
                  {validation.validationIssues.map((issue) => (
                    <Alert
                      key={`${issue.code}-${issue.message}`}
                      type={issue.blocking ? "error" : "warning"}
                      showIcon
                      title={issue.message}
                      description={
                        <Tag color={issue.blocking ? "red" : "gold"}>
                          {issue.blocking
                            ? l("阻断导入", "Blocks import")
                            : l("提示", "Notice")}
                        </Tag>
                      }
                    />
                  ))}
                </Space>
              )}
              {validation.duplicateTarget && (
                <Alert
                  type="warning"
                  showIcon
                  title={validation.duplicateTarget.message}
                  description={
                    <Form.Item
                      name="duplicateConfirmed"
                      valuePropName="checked"
                      style={{ marginBottom: 0 }}
                    >
                      <Checkbox>
                        {l(
                          "确认新建同名资源，不覆盖已有数据",
                          "Create a new resource with the same name without overwriting existing data",
                        )}
                      </Checkbox>
                    </Form.Item>
                  }
                />
              )}
            </section>
          )}
        </Form>
      ) : previewing ? null : (
        <Empty
          description={l(
            "未能解析矢量图层，请检查文件格式和 Shapefile 组件",
            "Could not parse a vector layer. Check the file format and Shapefile components.",
          )}
        />
      )}
    </div>
  );
}

export function vectorIssuesFromError(error: unknown): ImportValidationIssue[] {
  if (!(error instanceof ApiError)) return [];
  const data = error.data as { issues?: ImportValidationIssue[] } | null;
  return Array.isArray(data?.issues) ? data.issues : [];
}
