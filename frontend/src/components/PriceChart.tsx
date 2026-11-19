import { useEffect, useMemo, useRef } from "react";
import { LineChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { HistoryPoint } from "../types";
import { asDate, money } from "../format";

use([LineChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

export type ChartPeriod = "24h" | "7d" | "30d";

interface Props {
  points: HistoryPoint[];
  period?: ChartPeriod;
  height?: number;
  threshold?: number | null;
  thresholdLabel?: string;
  compact?: boolean;
}

interface Bucket {
  label: string;
  min: number | null;
  median: number | null;
}

const ACCENT = "#66fcf1";
const TEAL = "#45a29e";
const GRID = "#232c36";
const LABEL = "#78828b";
const AMBER = "#e8b44a";

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
  const sorted = [...points].sort(
    (a, b) => asDate(a.captured_at).getTime() - asDate(b.captured_at).getTime(),
  );

  for (const point of sorted) {
    const date = asDate(point.captured_at);
    if (Number.isNaN(date.getTime())) {
      continue;
    }
    const key = period === "24h" ? hourKey(date) : dayKey(date);
    buckets.set(key, {
      label:
        period === "24h"
          ? `${pad(date.getHours())}:00`
          : `${pad(date.getDate())}.${pad(date.getMonth() + 1)}`,
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
      result.push(
        buckets.get(key) ?? { label: `${pad(date.getHours())}:00`, min: null, median: null },
      );
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

export function PriceChart({
  points,
  period = "7d",
  height = 220,
  threshold = null,
  thresholdLabel,
  compact = false,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const buckets = useMemo(() => aggregate(points, period), [points, period]);
  const empty = buckets.every((bucket) => bucket.min === null && bucket.median === null);

  useEffect(() => {
    if (!container.current || empty) {
      return;
    }
    const chart = init(container.current, undefined, { renderer: "canvas" });

    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 300,
      grid: {
        left: compact ? 12 : 44,
        right: compact ? 8 : 10,
        top: 8,
        bottom: 22,
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#26313d",
        borderColor: "#2e3a47",
        textStyle: { color: "#c5c6c7", fontSize: 12 },
        axisPointer: { type: "line", lineStyle: { color: "rgba(102,252,241,0.3)", width: 1 } },
        valueFormatter: (value: unknown) =>
          value === null || value === undefined ? "—" : `${money(Number(value))} ₽`,
      },
      xAxis: {
        type: "category",
        data: buckets.map((bucket) => bucket.label),
        boundaryGap: false,
        axisLabel: {
          color: LABEL,
          fontSize: 10,
          margin: 12,
          interval: period === "30d" ? 4 : "auto",
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: {
          color: LABEL,
          fontSize: 10,
          formatter: (value: number) => `${money(value)} ₽`,
        },
        splitLine: { lineStyle: { color: GRID } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "минимум",
          type: "line",
          data: buckets.map((bucket) => bucket.min),
          smooth: false,
          connectNulls: true,
          symbol: "circle",
          symbolSize: 6,
          showSymbol: true,
          lineStyle: { color: TEAL, width: 2 },
          itemStyle: { color: TEAL, borderColor: "#1f2833", borderWidth: 1 },
          z: 3,
        },
        {
          name: "медиана",
          type: "line",
          data: buckets.map((bucket) => bucket.median),
          smooth: false,
          connectNulls: true,
          symbol: "circle",
          symbolSize: 6,
          showSymbol: true,
          lineStyle: { color: ACCENT, width: 2 },
          itemStyle: { color: ACCENT, borderColor: "#1f2833", borderWidth: 1 },
          areaStyle: { color: "rgba(102,252,241,0.07)" },
          z: 4,
          markLine:
            threshold !== null
              ? {
                  silent: true,
                  symbol: "none",
                  lineStyle: { color: AMBER, width: 1, type: "dashed", opacity: 0.7 },
                  label: {
                    color: AMBER,
                    fontSize: 10,
                    position: "insideEndTop",
                    formatter: thresholdLabel ?? `порог ${money(threshold)} ₽`,
                  },
                  data: [{ yAxis: threshold }],
                }
              : undefined,
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
  }, [buckets, compact, empty, period, threshold, thresholdLabel]);

  if (empty) {
    return (
      <div className="chart-empty" style={{ height }}>
        История цен пока пуста.
        <br />
        Дождитесь следующего прогона парсера.
      </div>
    );
  }

  return <div ref={container} style={{ width: "100%", height }} />;
}
