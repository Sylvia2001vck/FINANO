import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useT } from "../../hooks/useT";
import { TradeDailyPnlPoint } from "../../types/trade";

interface Props {
  dailyPnlSeries: TradeDailyPnlPoint[];
}

export function ProfitTrendChart({ dailyPnlSeries }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const { t } = useT();

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    const sortedSeries = [...dailyPnlSeries].sort((a, b) => a.date.localeCompare(b.date));
    const cumulative = t("chart.cumulativePnl");
    const daily = t("chart.dailyPnl");
    chart.setOption({
      tooltip: { trigger: "axis" as const },
      xAxis: {
        type: "category",
        data: sortedSeries.map((item) => item.date)
      },
      yAxis: [{ type: "value", name: cumulative }, { type: "value", name: daily }],
      series: [
        {
          name: cumulative,
          type: "line",
          smooth: true,
          areaStyle: {},
          data: sortedSeries.map((item) => item.cumulative_pnl)
        },
        {
          name: daily,
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
  }, [dailyPnlSeries, t]);

  return <div ref={chartRef} style={{ height: 320 }} />;
}
