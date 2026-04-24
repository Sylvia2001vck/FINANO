import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Card, Input, Segmented, Space, Spin, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import * as echarts from "echarts";
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { fetchFundLsjzJson, type LsjzPoint } from "../services/fundNav";
import { normalizeSixDigitFundCode } from "../utils/fundCode";

export type NavRangePreset = "1m" | "3m" | "6m" | "1y" | "3y" | "ytd" | "inception";

const PRESET_SEGMENTS: { label: string; value: NavRangePreset }[] = [
  { label: "近一月", value: "1m" },
  { label: "近三月", value: "3m" },
  { label: "近六月", value: "6m" },
  { label: "近一年", value: "1y" },
  { label: "近三年", value: "3y" },
  { label: "今年来", value: "ytd" },
  { label: "成立来", value: "inception" }
];

/** 首屏之后按序后台预取（近一月已在首屏拉过） */
const PREFETCH_PRESETS: NavRangePreset[] = ["3m", "6m", "1y", "3y", "ytd", "inception"];

const LSJZ_THROTTLE_MS = 220;

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

function cacheKey(fundCode: string, preset: NavRangePreset, panDays: number) {
  return `${fundCode}|${preset}|${panDays}`;
}

function computeDateRange(preset: NavRangePreset, panDays: number): { start: string; end: string } {
  if (preset === "ytd") {
    const y0 = dayjs().startOf("year");
    return { start: y0.format("YYYY-MM-DD"), end: dayjs().format("YYYY-MM-DD") };
  }
  if (preset === "inception") {
    return { start: "1990-01-01", end: dayjs().format("YYYY-MM-DD") };
  }
  const endBase = dayjs().subtract(panDays, "day");
  const endStr = endBase.format("YYYY-MM-DD");
  const e = endBase;
  switch (preset) {
    case "1m":
      return { start: e.subtract(1, "month").format("YYYY-MM-DD"), end: endStr };
    case "3m":
      return { start: e.subtract(3, "month").format("YYYY-MM-DD"), end: endStr };
    case "6m":
      return { start: e.subtract(6, "month").format("YYYY-MM-DD"), end: endStr };
    case "1y":
      return { start: e.subtract(1, "year").format("YYYY-MM-DD"), end: endStr };
    case "3y":
      return { start: e.subtract(3, "year").format("YYYY-MM-DD"), end: endStr };
    default:
      return { start: e.subtract(3, "month").format("YYYY-MM-DD"), end: endStr };
  }
}

function buildOption(points: LsjzPoint[]): echarts.EChartsOption {
  const data: [string, number][] = points.map((p) => [p.date, p.dwjz]);
  return {
    title: {
      text: "单位净值（历史）",
      left: "center",
      textStyle: { fontSize: 14 }
    },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v) => (typeof v === "number" ? v.toFixed(4) : String(v))
    },
    grid: { left: 56, right: 28, top: 56, bottom: 88 },
    xAxis: {
      type: "time",
      boundaryGap: [0, 0]
    },
    yAxis: {
      type: "value",
      scale: true,
      name: "DWJZ",
      axisLabel: { formatter: (v: number) => v.toFixed(4) }
    },
    dataZoom: [
      { type: "inside", start: 0, end: 100 },
      {
        type: "slider",
        start: 0,
        end: 100,
        height: 22,
        bottom: 16,
        labelFormatter: (_idx: number, value: string) => value?.slice(0, 10) ?? ""
      }
    ],
    series: [
      {
        name: "单位净值",
        type: "line",
        smooth: false,
        showSymbol: points.length < 120,
        symbolSize: 3,
        lineStyle: { width: 1.5 },
        data
      }
    ]
  };
}

export interface FundNavCurvePanelProps {
  linkedFundCode?: string | null;
  embedded?: boolean;
  chartHeight?: number;
  hideQueryButton?: boolean;
  onPrimaryLoaded?: (info: { fundCode: string; preset: NavRangePreset; panDays: number; points: number }) => void;
}

export type FundNavCurvePanelHandle = {
  reload: () => Promise<void>;
};

const FundNavCurvePanelInner = forwardRef<FundNavCurvePanelHandle, FundNavCurvePanelProps>(function FundNavCurvePanelInner(
  { linkedFundCode, embedded = false, chartHeight = 380, hideQueryButton = false, onPrimaryLoaded },
  ref
) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInst = useRef<echarts.ECharts | null>(null);
  const [code, setCode] = useState("510300");
  const [preset, setPreset] = useState<NavRangePreset>("1m");
  const [panDays, setPanDays] = useState(0);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<string>("");
  const [liveTagAt, setLiveTagAt] = useState<string | null>(null);
  /** 近一月已成功展示过，之后切换区间可走缓存或单拉 */
  const dataPrimedRef = useRef(false);
  const cacheRef = useRef<Map<string, { pts: LsjzPoint[]; meta: string }>>(new Map());
  const prefetchGenRef = useRef(0);
  const prevPrimedCodeRef = useRef<string | null>(null);

  const [prefetchLabels, setPrefetchLabels] = useState<string>("");
  const [prefetchBusy, setPrefetchBusy] = useState(false);

  useEffect(() => {
    if (linkedFundCode === undefined || linkedFundCode === null) return;
    const c = normalizeSixDigitFundCode(linkedFundCode);
    if (c) setCode(c);
  }, [linkedFundCode]);

  useEffect(() => {
    setPanDays(0);
  }, [preset]);

  const disposeChart = useCallback(() => {
    chartInst.current?.dispose();
    chartInst.current = null;
  }, []);

  useEffect(() => {
    const onResize = () => chartInst.current?.resize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const paintChart = useCallback(
    (pts: LsjzPoint[]) => {
      if (!chartRef.current) return;
      disposeChart();
      window.requestAnimationFrame(() => {
        if (!chartRef.current) return;
        const ch = echarts.init(chartRef.current);
        chartInst.current = ch;
        ch.setOption(buildOption(pts));
      });
    },
    [disposeChart]
  );

  const fetchOneRange = useCallback(async (fundCode: string, p: NavRangePreset, pan: number) => {
    const { start, end } = computeDateRange(p, pan);
    const res = await fetchFundLsjzJson(fundCode, { startDate: start, endDate: end });
    if (!res.ok) {
      return { ok: false as const, error: res.error || "拉取失败", pts: [] as LsjzPoint[], meta: "" };
    }
    const pts = res.points_asc?.length ? res.points_asc : [...(res.points_desc || [])].reverse();
    const trunc = res.range_truncated ? " · 区间数据量较大，已按服务端分页上限截取" : "";
    const pg = res.pages_fetched != null ? ` · 拉取 ${res.pages_fetched} 页` : "";
    const metaLine =
      pts.length > 0
        ? `共 ${pts.length} 个点（${start} ~ ${end}）${res.total_count != null ? ` · 接口 TotalCount=${res.total_count}` : ""}${pg}${trunc}`
        : "该区间内无净值数据";
    return { ok: true as const, pts, meta: metaLine, error: null as string | null };
  }, []);

  /** 当前展示区间：无缓存则打网 */
  const loadCurrentFromNetwork = useCallback(async () => {
    const c = normalizeSixDigitFundCode(code);
    if (!c) {
      if (!embedded) message.warning("请输入 6 位基金代码");
      return;
    }
    const key = cacheKey(c, preset, panDays);
    const hit = cacheRef.current.get(key);
    if (hit) {
      setMeta(hit.meta);
      paintChart(hit.pts);
      setLiveTagAt(dayjs().format("HH:mm:ss"));
      return;
    }
    setLoading(true);
    setMeta("");
    try {
      const out = await fetchOneRange(c, preset, panDays);
      if (!out.ok) {
        message.error(out.error);
        setMeta(out.error);
        disposeChart();
        return;
      }
      if (!out.pts.length) {
        message.warning("暂无净值数据");
        setMeta(out.meta);
        disposeChart();
        return;
      }
      cacheRef.current.set(key, { pts: out.pts, meta: out.meta });
      setMeta(out.meta);
      paintChart(out.pts);
      setLiveTagAt(dayjs().format("HH:mm:ss"));
      onPrimaryLoaded?.({ fundCode: c, preset, panDays, points: out.pts.length });
    } catch (e) {
      message.error(e instanceof Error ? e.message : "请求失败");
      disposeChart();
    } finally {
      setLoading(false);
    }
  }, [code, preset, panDays, embedded, fetchOneRange, paintChart, disposeChart, onPrimaryLoaded]);

  const reloadFull = useCallback(async () => {
    const c = normalizeSixDigitFundCode(code);
    if (!c) {
      if (!embedded) message.warning("请输入 6 位基金代码");
      return;
    }
    prefetchGenRef.current += 1;
    const gen = prefetchGenRef.current;
    cacheRef.current = new Map();
    dataPrimedRef.current = false;
    setPrefetchLabels("");
    setPrefetchBusy(false);

    setPreset("1m");
    setPanDays(0);

    setLoading(true);
    setMeta("");
    try {
      const out = await fetchOneRange(c, "1m", 0);
      if (!out.ok) {
        message.error(out.error);
        setMeta(out.error);
        disposeChart();
        return;
      }
      if (!out.pts.length) {
        message.warning("暂无净值数据");
        setMeta(out.meta);
        disposeChart();
        return;
      }
      const key = cacheKey(c, "1m", 0);
      cacheRef.current.set(key, { pts: out.pts, meta: out.meta });
      setMeta(out.meta);
      paintChart(out.pts);
      dataPrimedRef.current = true;
      setLiveTagAt(dayjs().format("HH:mm:ss"));
      onPrimaryLoaded?.({ fundCode: c, preset: "1m", panDays: 0, points: out.pts.length });
      setPrefetchBusy(true);
      setPrefetchLabels("近一月 ✓");

      void (async () => {
        const done: string[] = ["近一月"];
        for (const p of PREFETCH_PRESETS) {
          if (prefetchGenRef.current !== gen) return;
          await sleep(LSJZ_THROTTLE_MS);
          if (prefetchGenRef.current !== gen) return;
          const r = await fetchOneRange(c, p, 0);
          if (prefetchGenRef.current !== gen) return;
          const label = PRESET_SEGMENTS.find((s) => s.value === p)?.label ?? p;
          if (r.ok && r.pts.length) {
            cacheRef.current.set(cacheKey(c, p, 0), { pts: r.pts, meta: r.meta });
            done.push(label);
          } else {
            done.push(`${label}(失败)`);
          }
          setPrefetchLabels(done.join(" · "));
        }
        if (prefetchGenRef.current === gen) {
          setPrefetchBusy(false);
        }
      })();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "请求失败");
      disposeChart();
    } finally {
      setLoading(false);
    }
  }, [code, embedded, fetchOneRange, paintChart, disposeChart, onPrimaryLoaded]);

  useImperativeHandle(
    ref,
    () => ({
      reload: () => reloadFull()
    }),
    [reloadFull]
  );

  /** 切换区间 / 平移：优先缓存 */
  useEffect(() => {
    if (!dataPrimedRef.current) return;
    void loadCurrentFromNetwork();
  }, [preset, panDays, loadCurrentFromNetwork]);

  /** 已拉取过净值后，切换上方基金代码：整包重拉 */
  useEffect(() => {
    const c = normalizeSixDigitFundCode(code);
    if (!embedded || !c) return;
    if (!dataPrimedRef.current) return;
    if (prevPrimedCodeRef.current === null) {
      prevPrimedCodeRef.current = c;
      return;
    }
    if (prevPrimedCodeRef.current !== c) {
      prevPrimedCodeRef.current = c;
      void reloadFull();
    }
  }, [code, embedded, reloadFull]);

  useEffect(() => {
    return () => {
      disposeChart();
    };
  }, [disposeChart]);

  const panDisabled = preset === "ytd" || preset === "inception";
  const panStep = 28;

  return (
    <>
      {!embedded ? (
        <Space wrap align="start" style={{ marginBottom: 12 }}>
          <Input
            style={{ width: 120 }}
            placeholder="6 位代码"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          />
        </Space>
      ) : null}

      <div style={{ marginBottom: 12 }}>
        <Segmented<NavRangePreset>
          value={preset}
          onChange={(v) => setPreset(v)}
          options={PRESET_SEGMENTS}
          style={{ width: "100%", flexWrap: "wrap" }}
        />
        <Space style={{ marginTop: 10 }} wrap align="center">
          <Typography.Text type="secondary">时间窗口：</Typography.Text>
          <Button
            size="small"
            icon={<LeftOutlined />}
            disabled={panDisabled}
            onClick={() => setPanDays((d) => d + panStep)}
          >
            更早
          </Button>
          <Button
            size="small"
            icon={<RightOutlined />}
            disabled={panDisabled || panDays <= 0}
            onClick={() => setPanDays((d) => Math.max(0, d - panStep))}
          >
            更晚
          </Button>
          {!hideQueryButton ? (
            <Button type="primary" loading={loading} onClick={() => void reloadFull()}>
              查询基金净值
            </Button>
          ) : null}
        </Space>
        {hideQueryButton ? (
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
            工具栏「查询基金净值」将<strong>先加载近一月</strong>并立即出图，随后在后台预取三月～成立来；切换分段时优先用已缓存数据，减少卡顿。
          </Typography.Paragraph>
        ) : null}
      </div>

      <Card size="small" styles={{ body: { padding: 12 } }}>
        <Space style={{ marginBottom: 8 }} wrap align="center">
          {liveTagAt ? (
            <Tag color="processing">已对齐东财历史净值 · {liveTagAt}</Tag>
          ) : (
            <Tag>尚未拉取</Tag>
          )}
          {prefetchBusy ? <Tag color="default">后台预加载…</Tag> : prefetchLabels ? <Tag color="success">预加载 {prefetchLabels}</Tag> : null}
        </Space>
        <Spin spinning={loading} tip="加载首屏（近一月）…">
          <div ref={chartRef} style={{ height: chartHeight, width: "100%", minHeight: 200 }} />
        </Spin>
      </Card>

      {meta ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}>
          {meta}
        </Typography.Paragraph>
      ) : null}
    </>
  );
});

export const FundNavCurvePanel = memo(FundNavCurvePanelInner);
