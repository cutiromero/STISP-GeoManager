import {
  Alert,
  App,
  Button,
  Collapse,
  Empty,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { requestJson } from "../api/client";
import { downloadComputeFile } from "../api/compute";
import { requestScope } from "../projects/session";
import type {
  CatalogueComputeResult,
  CatalogueComputeResultGroups,
  RegisterMonitoringOutputResponse,
} from "../api/generated/types.gen";
import "./task-result-catalogue.css";

export default function TaskResultCatalogue({
  projectId,
  groupId,
}: {
  projectId: string;
  groupId?: string;
}) {
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<CatalogueComputeResultGroups>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [selection, setSelection] = useState<CatalogueComputeResult>();
  const [publishing, setPublishing] = useState(false);
  const [failure, setFailure] = useState("");
  const { message } = App.useApp();
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ page: String(page) });
    if (groupId) query.set("groupId", groupId);
    setLoading(true);
    setError("");
    void requestJson<CatalogueComputeResultGroups>(
      `/api/compute/result-groups/?${query}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setResult(value);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setResult(undefined);
        setError(reason instanceof Error ? reason.message : "目录暂时无法打开");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [page, groupId, projectId, refresh]);
  const publish = async () => {
    if (!selection || publishing) return;
    const scope = requestScope();
    setPublishing(true);
    setFailure("");
    try {
      await requestJson<RegisterMonitoringOutputResponse>(
        "/api/ecology/monitoring/registration/",
        {
          method: "POST",
          body: { outputId: selection.id },
        },
      );
      scope();
      setSelection(undefined);
      setRefresh((value) => value + 1);
      message.success("已正式登记。大屏刷新后展示当前区域的最新成果。");
    } catch (reason) {
      if (!(reason instanceof Error && reason.name === "AbortError"))
        setFailure(reason instanceof Error ? reason.message : "登记未完成");
    } finally {
      setPublishing(false);
    }
  };
  const rows = result?.items ?? [];
  return (
    <section
      className="task-result-catalogue"
      aria-label="按任务归档的计算成果"
    >
      <header>
        <div>
          <Typography.Title level={3}>任务成果</Typography.Title>
          <p>
            按业务流或独立计算任务归档；最新任务在前。正式登记不会改变原件或访问权限。
          </p>
        </div>
        <Space>
          {groupId && (
            <Link
              to={`/resources/catalog?view=task-results&projectTagId=${projectId}`}
            >
              查看全部任务成果
            </Link>
          )}
          <Button
            loading={loading}
            onClick={() => setRefresh((value) => value + 1)}
          >
            刷新
          </Button>
        </Space>
      </header>
      <Spin spinning={loading}>
        {error ? (
          <Alert showIcon type="error" title={error} />
        ) : rows.length ? (
          <Collapse
            defaultActiveKey={groupId ? [groupId] : []}
            items={rows.map((group) => ({
              key: group.id,
              label: (
                <div className="task-result-heading">
                  <strong>{group.name}</strong>
                  <span>
                    {new Date(group.createdAt).toLocaleString("zh-CN", {
                      hour12: false,
                    })}
                  </span>
                  <Tag>{group.total} 项成果</Tag>
                </div>
              ),
              children: (
                <>
                  <ul className="task-result-files">
                    {group.items.map((item) => (
                      <li key={item.id}>
                        <div>
                          <strong>{item.name}</strong>
                          <small>
                            {item.taskName} · {item.kind}
                          </small>
                        </div>
                        <Space wrap>
                          {item.registered && <Tag color="green">正式成果</Tag>}
                          {item.kind === "raster" || item.kind === "vector" ? (
                            <Link
                              to={`/map?resourceId=${item.resourceId}&projectTagId=${projectId}`}
                            >
                              查看地图
                            </Link>
                          ) : item.kind === "table" ? (
                            <Link
                              to={`/nongeo?resourceQ=${encodeURIComponent(item.name)}&projectTagId=${projectId}`}
                            >
                              查看表格
                            </Link>
                          ) : null}
                          {item.downloadUrl && (
                            <Button
                              size="small"
                              onClick={() =>
                                void downloadComputeFile(
                                  item.downloadUrl!,
                                  item.fileName,
                                ).catch(() => message.error("暂时无法下载成果"))
                              }
                            >
                              下载
                            </Button>
                          )}
                          {!item.registered && item.canRegister && (
                            <Button
                              size="small"
                              type="primary"
                              onClick={() => {
                                setSelection(item);
                                setFailure("");
                              }}
                            >
                              登记为正式成果
                            </Button>
                          )}
                        </Space>
                      </li>
                    ))}
                  </ul>
                  {group.total > group.items.length && (
                    <Alert
                      type="info"
                      title="此处预览前 100 项。其余文件可从所属计算任务查看。"
                    />
                  )}
                  {group.workflowId && (
                    <Link
                      to={`/business-flows?run=${group.workflowId}&projectTagId=${projectId}`}
                    >
                      查看业务流任务
                    </Link>
                  )}
                </>
              ),
            }))}
          />
        ) : (
          !loading && <Empty description="没有可见的已入库任务成果" />
        )}
      </Spin>
      {!groupId && (page > 1 || result?.hasMore) && (
        <Space className="task-result-pagination">
          <Button
            disabled={loading || page <= 1}
            onClick={() => setPage((value) => value - 1)}
          >
            上一页
          </Button>
          <span>第 {page} 页</span>
          <Button
            disabled={loading || !result?.hasMore}
            onClick={() => setPage((value) => value + 1)}
          >
            下一页
          </Button>
        </Space>
      )}
      <Modal
        open={Boolean(selection)}
        title="确认登记为正式成果"
        okText="正式登记"
        cancelText="取消"
        confirmLoading={publishing}
        onOk={() => void publish()}
        onCancel={() => {
          if (!publishing) setSelection(undefined);
        }}
        mask={{ closable: !publishing }}
      >
        <p>{selection?.name}</p>
        <p>
          大屏将按区域、实际观测期与登记顺序展示最新正式版本。原有成果和访问权限不变。
        </p>
        {failure && <Alert showIcon type="error" title={failure} />}
      </Modal>
    </section>
  );
}
