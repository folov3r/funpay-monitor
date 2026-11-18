const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return String(value);
  }
  return number.toLocaleString("ru-RU", { maximumFractionDigits: 6 });
}

export function moment(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString("ru-RU");
}

/** Naive UTC timestamps from the core need a suffix before parsing. */
export function asDate(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function ago(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = asDate(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  const diff = Date.now() - date.getTime();
  if (diff < MINUTE) {
    return "только что";
  }
  if (diff < HOUR) {
    return `${Math.floor(diff / MINUTE)} мин`;
  }
  if (diff < DAY) {
    return `${Math.floor(diff / HOUR)} ч`;
  }
  return `${Math.floor(diff / DAY)} дн`;
}

export function lots(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return `${count} лот`;
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} лота`;
  }
  return `${count} лотов`;
}

export interface Delta {
  text: string;
  direction: "up" | "down" | "flat";
}

export function percentDelta(first: string, last: string, days: number): Delta {
  const start = Number(first);
  const end = Number(last);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start === 0) {
    return { text: "нет данных", direction: "flat" };
  }
  const change = ((end - start) / start) * 100;
  if (Math.abs(change) < 0.05) {
    return { text: `0% за ${days} дн`, direction: "flat" };
  }
  const sign = change > 0 ? "+" : "−";
  return {
    text: `${sign}${Math.abs(change).toFixed(1).replace(".", ",")}% за ${days} дн`,
    direction: change > 0 ? "up" : "down",
  };
}
