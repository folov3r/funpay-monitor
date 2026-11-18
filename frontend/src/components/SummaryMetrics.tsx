import type { PriceSummary } from "../types";
import { money } from "../format";

export function SummaryMetrics({ summary }: { summary: PriceSummary | null }) {
  return (
    <div className="metrics">
      <div className="metric">
        <span className="metric-label">Минимум</span>
        <span className="metric-value">{summary ? `${money(summary.min_price)} ₽` : "—"}</span>
      </div>
      <div className="metric">
        <span className="metric-label">Медиана</span>
        <span className="metric-value">{summary ? `${money(summary.median_price)} ₽` : "—"}</span>
      </div>
      <div className="metric">
        <span className="metric-label">Предложений</span>
        <span className="metric-value">{summary?.offer_count ?? 0}</span>
      </div>
    </div>
  );
}
