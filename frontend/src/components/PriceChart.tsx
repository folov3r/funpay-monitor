import { useEffect, useRef } from "react";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { HistoryPoint } from "../types";

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

interface Props {
  points: HistoryPoint[];
  height?: number;
}

export function PriceChart({ points, height = 320 }: Props) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) {
      return;
    }
    const chart = init(container.current, undefined, { renderer: "canvas" });
    const minSeries = points.map((point) => [point.captured_at, Number(point.min_price)]);
    const medianSeries = points.map((point) => [point.captured_at, Number(point.median_price)]);

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 56, right: 24, top: 36, bottom: 48 },
      tooltip: { trigger: "axis" },
      legend: { top: 0, textStyle: { color: "#cbd5e1" } },
      xAxis: {
        type: "time",
        axisLabel: { color: "#94a3b8" },
        axisLine: { lineStyle: { color: "#334155" } },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: "Цена, RUB",
        nameTextStyle: { color: "#94a3b8" },
        axisLabel: { color: "#94a3b8" },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [
        {
          name: "Минимум",
          type: "line",
          showSymbol: points.length < 40,
          smooth: false,
          data: minSeries,
          lineStyle: { color: "#34d399", width: 2 },
          itemStyle: { color: "#34d399" },
        },
        {
          name: "Медиана",
          type: "line",
          showSymbol: points.length < 40,
          smooth: false,
          data: medianSeries,
          lineStyle: { color: "#60a5fa", width: 2, type: "dashed" },
          itemStyle: { color: "#60a5fa" },
        },
      ],
    });

    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [points]);

  if (points.length === 0) {
    return <p className="muted">История цен пока пуста. Дождитесь следующего прогона парсера.</p>;
  }

  return <div ref={container} style={{ width: "100%", height }} />;
}
