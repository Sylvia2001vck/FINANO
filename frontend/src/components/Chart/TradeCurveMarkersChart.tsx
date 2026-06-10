import { Empty, Spin } from "antd";
import * as echarts from "echarts";
import { useEffect, useMemo, useRef } from "react";
import { useT } from "../../hooks/useT";
import { TradeCurve } from "../../types/trade";

interface Props {
  curve?: TradeCurve | null;
  loading?: boolean;
  height?: number;
}

export function TradeCurveMarkersChart({ curve, loading = false, height = 260 }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const { t } = useT();

  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (!curve || !curve.points.length) return null;
    const navLabel = t("chart.nav");
    const buyLabel = t("chart.buy");
    const sellLabel = t("chart.sell");
    const buyPoint = t("chart.buyPoint");
    const sellPoint = t("chart.sellPoint");
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
              lines.push(`${item.axisValueLabel}<br/>${navLabel}：${Number(item.data?.[1] ?? 0).toFixed(4)}`);
            } else if (item?.data?.marker) {
              const m = item.data.marker;
              const action = m.action === "buy" ? buyLabel : sellLabel;
              lines.push(
                `${action} #${m.trade_id}<br/>Qty：${m.quantity}<br/>Amt：${
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
      legend: { data: [navLabel, buyPoint, sellPoint] },
      series: [
        {
          name: navLabel,
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.8 },
          data: lineData
        },
        {
          name: buyPoint,
          type: "scatter",
          symbol: "triangle",
          symbolSize: 12,
          itemStyle: { color: "#ff4d4f" },
          data: buyData
        },
        {
          name: sellPoint,
          type: "scatter",
          symbol: "diamond",
          symbolSize: 12,
          itemStyle: { color: "#1677ff" },
          data: sellData
        }
      ]
    };
  }, [curve, t]);

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

  if (loading) return <Spin />;
  if (!option) return <Empty description={t("chart.noNavData")} />;
  return <div ref={chartRef} style={{ height }} />;
}
