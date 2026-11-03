import { DownloadOutlined, GlobalOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Space,
  Spin,
  Table,
  Tag,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { computeApi, downloadComputeFile } from "../api/compute";
import { sharingApi } from "../api/sharing";
import type {
  ComputePreview,
  ShareOpenResponse,
} from "../api/generated/types.gen";
import { useProjectContext } from "../projects/ProjectContext";
import { getActiveProject } from "../projects/session";
import { useShareText } from "./shareUi";
import { createUuid } from "../utils/uuid";
import { parseSharedPreview } from "./shareResponses";
import "./sharing.css";

export default function SharedOutputDrawer({
  invitationId,
  onClose,
}: {
  invitationId: number;
  onClose: () => void;
}) {
  const ui = useShareText();
  const navigate = useNavigate();
  const project = useProjectContext();
  const [data, setData] = useState<ShareOpenResponse | null>(null);
  const [preview, setPreview] = useState<ComputePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const currentProject = project?.current ?? getActiveProject();
  const matchingProject =
    data && currentProject === String(data.target.projectTagId);
  const rows = useMemo(
    () =>
      preview?.rows.map((row) => ({
        ...Object.fromEntries(
          preview.columns.map((field, i) => [field, row[i]]),
        ),
        _sharedRow: createUuid(),
      })) ?? [],
    [preview],
  );

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    setData(null);
    sharingApi
      .open(invitationId)
      .then((response) => {
        if (!live) return;
        if (!response.output)
          throw new Error(
            ui(
              "该邀请没有可查看的计算结果",
              "This invitation has no viewable compute output",
            ),
          );
        setData(response);
      })
      .catch((reason) => {
        if (live)
          setError(
            reason instanceof Error
              ? reason.message
              : ui("分享结果不可用", "The shared result is unavailable"),
          );
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [invitationId, currentProject]);

  useEffect(() => {
    let live = true;
    setPreview(null);
    setPreviewError("");
    if (data?.output && matchingProject && !data.output.expired) {
      computeApi
        .preview(data.output.id)
        .then(parseSharedPreview)
        .then((value) => {
          if (live) setPreview(value);
        })
        .catch((reason) => {
          if (live)
            setPreviewError(
              reason instanceof Error
                ? reason.message
                : ui(
                    "预览暂不可用，可下载后查看",
                    "Preview unavailable. Download the file to view it.",
                  ),
            );
        });
    }
    return () => {
      live = false;
    };
  }, [data, matchingProject]);

  async function download() {
    if (!data?.output || !matchingProject || downloading) return;
    setDownloading(true);
    setError("");
    try {
      await sharingApi.open(invitationId);
      await downloadComputeFile(data.output.downloadUrl, data.output.fileName);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : ui("下载失败", "Download failed"),
      );
    } finally {
      setDownloading(false);
    }
  }

  const output = data?.output;
  return (
    <Drawer
      title={data?.target.name || ui("分享的计算结果", "Shared compute output")}
      open
      onClose={onClose}
      size={760}
    >
      <Spin spinning={loading}>
        {error && <Alert type="error" showIcon title={error} />}
        {data && output && (
          <>
            <div className="share-output-summary">
              <div>
                <Space wrap>
                  <strong>{output.label || data.target.name}</strong>
                  <Tag color="blue">{ui("只读分享", "Read-only share")}</Tag>
                </Space>
                <span className="share-output-file">
                  {output.fileName} / {(output.sizeBytes / 1024).toFixed(1)} KiB
                </span>
                <span className="share-output-file">
                  {data.target.projectName}
                </span>
              </div>
              <Space wrap>
                <Button
                  icon={<DownloadOutlined />}
                  aria-label={ui("下载", "Download")}
                  loading={downloading}
                  disabled={!matchingProject || output.expired}
                  onClick={() => void download()}
                >
                  {ui("下载", "Download")}
                </Button>
                {["raster", "vector"].includes(output.kind) && (
                  <Button
                    type="primary"
                    icon={<GlobalOutlined />}
                    aria-label={ui("在地理工作台查看", "View on map")}
                    disabled={!matchingProject || output.expired}
                    onClick={() =>
                      navigate(
                        `/map?computeOutputId=${output.id}&projectTagId=${data.target.projectTagId}`,
                      )
                    }
                  >
                    {ui("在地理工作台查看", "View on map")}
                  </Button>
                )}
              </Space>
            </div>
            {!matchingProject && (
              <Alert
                type="info"
                showIcon
                title={ui(
                  "请切换到结果所属项目查看",
                  "Switch to the result's project to view it",
                )}
                action={
                  <Button
                    size="small"
                    aria-label={ui("切换项目", "Switch project")}
                    onClick={() =>
                      project?.choose(String(data.target.projectTagId))
                    }
                  >
                    {ui("切换项目", "Switch project")}
                  </Button>
                }
              />
            )}
            {output.expired && (
              <Alert
                type="warning"
                showIcon
                title={ui(
                  "该结果文件已过期，暂时无法预览或下载",
                  "This output file has expired and cannot be previewed or downloaded",
                )}
              />
            )}
            {previewError && (
              <Alert type="warning" showIcon title={previewError} />
            )}
            {matchingProject && preview && (
              <>
                <Descriptions
                  size="small"
                  column={2}
                  items={Object.entries(preview.metadata).map(
                    ([key, value]) => ({
                      key,
                      label: key,
                      children:
                        typeof value === "object"
                          ? JSON.stringify(value)
                          : String(value ?? ""),
                    }),
                  )}
                />
                {preview.columns.length > 0 && (
                  <Table
                    size="small"
                    rowKey="_sharedRow"
                    scroll={{ x: true }}
                    pagination={{ pageSize: 10 }}
                    columns={preview.columns.map((field) => ({
                      key: field,
                      title: field,
                      dataIndex: field,
                      render: (value: unknown) => String(value ?? ""),
                    }))}
                    dataSource={rows}
                  />
                )}
              </>
            )}
          </>
        )}
      </Spin>
    </Drawer>
  );
}
