import { Empty, Spin } from "antd";
import * as echarts from "echarts";
import { useEffect, useMemo, useRef } from "react";
import { TradeCurve } from "../../types/trade";

interface Props {
  curve?: TradeCurve | null;
  loading?: boolean;
  height?: number;
}

function formatAction(action: "buy" | "sell") {
  return action === "buy" ? "买入" : "卖出";
}

export function TradeCurveMarkersChart({ curve, loading = false, height = 260 }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (!curve || !curve.points.length) return null;
    const lineData = curve.points.map((p) => [p.date, p.nav]);
    const buyData = curve.markers
      .filter((m) => m.action === "buy" && typeof m.nav === "number")
      .map((m) => ({
        name: m.label,
        value: [m.date, m.nav as number],
        marker: m
      }));
    const sellData = curve.markers
      .filter((m) => m.action === "sell" && typeof m.nav === "number")
      .map((m) => ({
        name: m.label,
        value: [m.date, m.nav as number],
        marker: m
      }));
    return {
      tooltip: {
        trigger: "axis",
        formatter: (params: any) => {
          const lines: string[] = [];
          const arr = Array.isArray(params) ? params : [params];
          for (const item of arr) {
            if (item?.seriesType === "line") {
              lines.push(`${item.axisValueLabel}<br/>净值：${Number(item.data?.[1] ?? 0).toFixed(4)}`);
            } else if (item?.data?.marker) {
              const m = item.data.marker;
              lines.push(
                `${formatAction(m.action)} #${m.trade_id}<br/>数量：${m.quantity}<br/>金额：${
                  typeof m.amount === "number" ? m.amount.toFixed(2) : "-"
                }`
              );
            }
          }
          return lines.join("<br/><br/>");
        }
      },
      grid: { left: 50, right: 18, top: 18, bottom: 36 },
      xAxis: { type: "time" },
      yAxis: { type: "value", scale: true },
      legend: { data: ["净值", "买入点", "卖出点"] },
      series: [
        {
          name: "净值",
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.8 },
          data: lineData
        },
        {
          name: "买入点",
          type: "scatter",
          symbol: "triangle",
          symbolSize: 12,
          itemStyle: { color: "#ff4d4f" },
          data: buyData
        },
        {
          name: "卖出点",
          type: "scatter",
          symbol: "diamond",
          symbolSize: 11,
          itemStyle: { color: "#1677ff" },
          data: sellData
        }
      ]
    };
  }, [curve]);

  useEffect(() => {
    if (!chartRef.current || !option) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);

  if (!curve?.points.length) {
    return (
      <Spin spinning={loading}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无净值曲线数据" />
      </Spin>
    );
  }
  return (
    <Spin spinning={loading}>
      <div ref={chartRef} style={{ height }} />
    </Spin>
  );
}
