import { useEffect, useMemo, useRef } from "react";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { HistoryPoint } from "../types";
import { asDate, money } from "../format";

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

export type ChartPeriod = "24h" | "7d" | "30d";

interface Props {
  points: HistoryPoint[];
  period?: ChartPeriod;
  height?: number;
}

interface Bucket {
  label: string;
  min: number;
  median: number;
}

function aggregate(points: HistoryPoint[], period: ChartPeriod): Bucket[] {
  const buckets = new Map<string, Bucket>();
  const sorted = [...points].sort((a, b) => asDate(a.captured_at).getTime() - asDate(b.captured_at).getTime());

  for (const point of sorted) {
    const date = asDate(point.captured_at);
    if (Number.isNaN(date.getTime())) {
      continue;
    }
    const day = date.toISOString().slice(0, 10);
    const hour = String(date.getHours()).padStart(2, "0");
    const key = period === "24h" ? `${day}T${hour}` : day;
    const label =
      period === "24h"
        ? `${hour}:00`
        : `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}`;
    buckets.set(key, {
      label,
      min: Number(point.min_price),
      median: Number(point.median_price),
    });
  }

  const rows = [...buckets.values()];
  const limit = period === "24h" ? 24 : period === "7d" ? 7 : 30;
  return rows.slice(-limit);
}

export function PriceChart({ points, period = "7d", height = 260 }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const buckets = useMemo(() => aggregate(points, period), [points, period]);

  useEffect(() => {
    if (!container.current || buckets.length === 0) {
      return;
    }
    const chart = init(container.current, undefined, { renderer: "canvas" });

    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 300,
      grid: { left: 62, right: 8, top: 10, bottom: 30 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#16233a",
        borderColor: "#24344f",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        axisPointer: { type: "shadow", shadowStyle: { color: "rgba(56,189,248,0.06)" } },
        valueFormatter: (value: unknown) => `${money(Number(value))} ₽`,
      },
      xAxis: {
        type: "category",
        data: buckets.map((bucket) => bucket.label),
        axisLabel: { color: "#64748b", fontSize: 10, margin: 12 },
        axisLine: { lineStyle: { color: "#24344f" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: {
          color: "#64748b",
          fontSize: 10,
          formatter: (value: number) => money(value),
        },
        splitLine: { lineStyle: { color: "rgba(36,52,79,0.65)" } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "минимум",
          type: "bar",
          data: buckets.map((bucket) => bucket.min),
          barWidth: 12,
          barGap: "35%",
          itemStyle: { color: "#34d399", borderRadius: [3, 3, 0, 0] },
        },
        {
          name: "медиана",
          type: "bar",
          data: buckets.map((bucket) => bucket.median),
          barWidth: 12,
          itemStyle: { color: "#60a5fa", borderRadius: [3, 3, 0, 0] },
        },
      ],
    });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [buckets]);

  if (buckets.length === 0) {
    return (
      <div className="chart-empty">
        История цен пока пуста.
        <br />
        Дождитесь следующего прогона парсера.
      </div>
    );
  }

  return <div ref={container} style={{ width: "100%", height }} />;
}
