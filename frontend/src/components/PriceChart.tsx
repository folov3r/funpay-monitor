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
  min: number | null;
  median: number | null;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function hourKey(date: Date): string {
  return `${dayKey(date)}T${pad(date.getHours())}`;
}

function aggregate(points: HistoryPoint[], period: ChartPeriod): Bucket[] {
  const buckets = new Map<string, Bucket>();
  const sorted = [...points].sort((a, b) => asDate(a.captured_at).getTime() - asDate(b.captured_at).getTime());

  for (const point of sorted) {
    const date = asDate(point.captured_at);
    if (Number.isNaN(date.getTime())) {
      continue;
    }
    const key = period === "24h" ? hourKey(date) : dayKey(date);
    buckets.set(key, {
      label: period === "24h" ? `${pad(date.getHours())}:00` : `${pad(date.getDate())}.${pad(date.getMonth() + 1)}`,
      min: Number(point.min_price),
      median: Number(point.median_price),
    });
  }

  // Keep the axis fixed to the selected window, like the mockup, even when
  // some days have no snapshots yet.
  const now = new Date();
  const result: Bucket[] = [];
  if (period === "24h") {
    for (let i = 23; i >= 0; i -= 1) {
      const date = new Date(now);
      date.setHours(now.getHours() - i, 0, 0, 0);
      const key = hourKey(date);
      result.push(buckets.get(key) ?? { label: `${pad(date.getHours())}:00`, min: null, median: null });
    }
    return result;
  }

  const days = period === "7d" ? 7 : 30;
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = new Date(now);
    date.setDate(now.getDate() - i);
    const key = dayKey(date);
    result.push(
      buckets.get(key) ?? {
        label: `${pad(date.getDate())}.${pad(date.getMonth() + 1)}`,
        min: null,
        median: null,
      },
    );
  }
  return result;
}

export function PriceChart({ points, period = "7d", height = 260 }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const buckets = useMemo(() => aggregate(points, period), [points, period]);

  useEffect(() => {
    if (!container.current || buckets.every((bucket) => bucket.min === null && bucket.median === null)) {
      return;
    }
    const chart = init(container.current, undefined, { renderer: "canvas" });

    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 300,
      grid: { left: 44, right: 8, top: 0, bottom: 20 },
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
          formatter: (value: number) => `${money(value)} ₽`,
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
          barMaxWidth: 18,
          barGap: "30%",
          itemStyle: { color: "#34d399", borderRadius: [3, 3, 0, 0] },
        },
        {
          name: "медиана",
          type: "bar",
          data: buckets.map((bucket) => bucket.median),
          barMaxWidth: 18,
          itemStyle: { color: "#60a5fa", borderRadius: [3, 3, 0, 0] },
        },
      ],
    });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    if (import.meta.env.DEV) {
      (window as Window & { __priceChart?: unknown }).__priceChart = chart;
    }
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [buckets]);

  if (buckets.every((bucket) => bucket.min === null && bucket.median === null)) {
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
