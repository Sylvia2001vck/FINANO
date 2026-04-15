import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { Trade } from "../../types/trade";

interface Props {
  trades: Trade[];
}

export function ProfitTrendChart({ trades }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    const sortedTrades = [...trades].sort((a, b) => a.trade_date.localeCompare(b.trade_date));
    let cumulative = 0;
    const series = sortedTrades.map((item) => {
      cumulative += item.profit;
      return cumulative;
    });
    chart.setOption({
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: sortedTrades.map((item) => item.trade_date)
      },
      yAxis: { type: "value" },
      series: [
        {
          type: "line",
          smooth: true,
          areaStyle: {},
          data: series
        }
      ]
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [trades]);

  return <div ref={chartRef} style={{ height: 320 }} />;
}
