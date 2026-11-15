import { Alert, Button, Checkbox, Select, Slider, Space, Spin } from "antd";
import {
  observationProducts,
  type MonitoringWorkspace,
} from "./useMonitoringWorkspace";
import "./monitor-workspace.css";

export default function MonitoringSourceControls({
  workspace: w,
}: {
  workspace: MonitoringWorkspace;
}) {
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
