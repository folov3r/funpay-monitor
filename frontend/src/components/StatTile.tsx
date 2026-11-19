export type TileTone = "muted" | "mint" | "amber" | "red" | "accent";

export function StatTile({
  label,
  value,
  hint,
  hintTone = "muted",
  dotTone = "accent",
}: {
  label: string;
  value: string | number;
  hint: string;
  hintTone?: TileTone;
  dotTone?: TileTone;
}) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      <span className={`kpi-hint tone-${hintTone}`}>{hint}</span>
      <span className={`kpi-dot tone-${dotTone}`} />
    </div>
  );
}
