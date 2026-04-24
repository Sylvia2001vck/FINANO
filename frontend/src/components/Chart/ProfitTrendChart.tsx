import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { TradeDailyPnlPoint } from "../../types/trade";

interface Props {
  dailyPnlSeries: TradeDailyPnlPoint[];
}

export function ProfitTrendChart({ dailyPnlSeries }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    const sortedSeries = [...dailyPnlSeries].sort((a, b) => a.date.localeCompare(b.date));
    chart.setOption({
      tooltip: { trigger: "axis" as const },
      xAxis: {
        type: "category",
        data: sortedSeries.map((item) => item.date)
      },
      yAxis: [{ type: "value", name: "累计盈亏" }, { type: "value", name: "当日盈亏" }],
      series: [
        {
          name: "累计盈亏",
          type: "line",
          smooth: true,
          areaStyle: {},
          data: sortedSeries.map((item) => item.cumulative_pnl)
        },
        {
          name: "当日盈亏",
          type: "bar",
          yAxisIndex: 1,
          opacity: 0.6,
          data: sortedSeries.map((item) => item.daily_pnl)
        }
      ]
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [dailyPnlSeries]);

  return <div ref={chartRef} style={{ height: 320 }} />;
}
