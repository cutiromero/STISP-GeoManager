import {
  Alert,
  Button,
  Checkbox,
  Drawer,
  Select,
  Slider,
  Space,
  Spin,
} from "antd";
import { useState } from "react";
import {
  observationProducts,
  type MonitoringWorkspace,
} from "./useMonitoringWorkspace";
import "./monitor-workspace.css";

export default function MonitoringSourceControls({
  workspace: w,
  compact = false,
}: {
  workspace: MonitoringWorkspace;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (compact)
    return (
      <div className="monitor-source-summary">
        <Button size="small" block onClick={() => setOpen(true)}>
          选择资料与时相
        </Button>
        <span title={w.source?.resource.name}>
          {w.scene === "wildfire"
            ? w.time
              ? `${observationProducts.find((row) => row.value === w.product)?.label} · ${w.time.date} — ${w.time.endDate}`
              : "请选择观测时期"
            : `解译时相：${w.inputSet?.label ?? "请选择时相组合"}`}
        </span>
        <span className="monitor-source-name" title={w.source?.resource.name}>
          {w.source?.resource.name ?? "尚未选择原始资料"}
        </span>
        <Space wrap>
          <Checkbox
            checked={w.sourceVisible}
            onChange={(event) => w.setSourceVisible(event.target.checked)}
          >
            原始图层
          </Checkbox>
          <Checkbox
            checked={w.resultVisible}
            onChange={(event) => w.setResultVisible(event.target.checked)}
          >
            成果图层
          </Checkbox>
        </Space>
        {w.error && <span role="alert">{w.error}</span>}
        <Drawer
          open={open}
          title="原始资料与观测时相"
          size={480}
          onClose={() => setOpen(false)}
          destroyOnHidden
          className="monitor-task-drawer"
          footer={
            <Button type="primary" onClick={() => setOpen(false)}>
              完成选择
            </Button>
          }
        >
          <MonitoringSourceControls workspace={w} />
        </Drawer>
      </div>
    );
  return (
    <div className="monitor-source-controls">
      {w.error && (
        <Alert
          type="error"
          title={w.error}
          action={<Button onClick={w.refresh}>重试</Button>}
        />
      )}
      {w.loading && <Spin size="small" />}
      <label>
        资料集合
        <Select
          aria-label="资料集合"
          value={w.collection ?? ""}
          options={[
            { value: "", label: "全部资料集合" },
            ...(w.catalog?.collections.map((row) => ({
              value: row.key,
              label: `${row.label} · ${row.count}份`,
            })) ?? []),
          ]}
          onChange={w.selectCollection}
        />
      </label>
      {w.scene !== "wildfire" && (
        <label>
          解译时相组合
          <Select
            aria-label="解译时相组合"
            showSearch
            optionFilterProp="label"
            value={w.inputSet?.id}
            options={w.catalog?.inputSets.map((row) => ({
              value: row.id,
              label: row.label,
            }))}
            onChange={w.selectSet}
          />
        </label>
      )}
      <label>
        原始资料
        <Select
          aria-label="原始资料"
          showSearch
          optionFilterProp="label"
          value={w.source?.resource.id}
          onChange={w.setSourceId}
          options={w.catalog?.assets.map((row) => ({
            value: row.resource.id,
            label: `${row.metadata.period?.startsAt?.slice(0, row.metadata.period.precision === "month" ? 7 : 10) ?? "时间未登记"} · ${row.resource.name}`,
          }))}
        />
      </label>
      {w.scene === "wildfire" && (
        <>
          <label>
            监测内容
            <Select
              aria-label="监测内容"
              value={w.product}
              options={observationProducts}
              onChange={w.setProduct}
            />
          </label>
          <div className="monitor-source-dates">
            <label>
              年份
              <Select
                aria-label="观测年份"
                showSearch
                optionFilterProp="label"
                value={w.selectedYear}
                onChange={w.setYear}
                options={w.years.map((row) => ({
                  value: row.year,
                  label: `${row.year}年`,
                }))}
              />
            </label>
            <label>
              观测时期
              <Select
                aria-label="观测时期"
                showSearch
                optionFilterProp="label"
                value={w.time?.ordinal}
                onChange={w.setOrdinal}
                options={w.times.map((row) => ({
                  value: row.ordinal,
                  label:
                    w.product === "fcci_ba"
                      ? row.date.slice(0, 7)
                      : `${row.date} — ${row.endDate}`,
                }))}
              />
            </label>
          </div>
        </>
      )}
      {!w.loading && !w.catalog?.assets.length && (
        <p>请在数据目录中登记原始输入资料及观测时间。</p>
      )}
      {w.scene !== "wildfire" && w.catalog?.assets.length && !w.inputSet && (
        <p>
          当前方法需要{" "}
          {w.catalog.method?.inputs.filter((row) => row.required).length}{" "}
          期同网格资料，请补齐对应时相。
        </p>
      )}
      <Space>
        <Checkbox
          checked={w.sourceVisible}
          onChange={(event) => w.setSourceVisible(event.target.checked)}
        >
          原始图层
        </Checkbox>
        <Checkbox
          checked={w.resultVisible}
          onChange={(event) => w.setResultVisible(event.target.checked)}
        >
          成果图层
        </Checkbox>
      </Space>
      {w.sourceVisible && (
        <label>
          原始图层透明度
          <Slider
            aria-label="原始图层透明度"
            value={100 - w.sourceOpacity}
            onChange={(value) => w.setSourceOpacity(100 - value)}
          />
        </label>
      )}
      {(w.offset > 0 || w.catalog?.hasMoreSources) && (
        <Space>
          <Button disabled={!w.offset} onClick={w.previousPage}>
            上一页
          </Button>
          <Button disabled={!w.catalog?.hasMoreSources} onClick={w.nextPage}>
            更多资料
          </Button>
        </Space>
      )}
    </div>
  );
}
