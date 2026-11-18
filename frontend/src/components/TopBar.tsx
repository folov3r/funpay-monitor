import type { Health } from "../types";

export function TopBar({ health }: { health: Health | null }) {
  return (
    <header className="topbar">
      <div className="logo">F</div>
      <div className="brand">
        <span className="brand-title">FunPay Monitor</span>
        <span className="brand-sub">мониторинг цен FunPay</span>
      </div>
      <div className="topbar-spacer" />
      <div
        className={health ? "status-pill ok" : "status-pill down"}
        title={
          health
            ? `${health.database} · ${health.scheduler ? "планировщик включён" : "планировщик выключен"}`
            : undefined
        }
      >
        <span className="status-dot" />
        {health ? "API онлайн" : "API недоступен"}
      </div>
      <span className="version">{health ? `v${health.version}` : "—"}</span>
    </header>
  );
}
