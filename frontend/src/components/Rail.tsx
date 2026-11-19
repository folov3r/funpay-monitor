import type { Health } from "../types";

export type Tab = "categories" | "subscriptions" | "notifications" | "status";

const NAV: { id: Tab; label: string; icon: "grid" | "stack" | "bell" | "pulse" }[] = [
  { id: "categories", label: "Категории", icon: "grid" },
  { id: "subscriptions", label: "Подписки", icon: "stack" },
  { id: "notifications", label: "Уведомления", icon: "bell" },
  { id: "status", label: "Состояние", icon: "pulse" },
];

function NavIcon({ kind }: { kind: "grid" | "stack" | "bell" | "pulse" }) {
  if (kind === "grid") {
    return (
      <span className="nav-icon">
        <i />
        <i />
        <i />
        <i />
      </span>
    );
  }
  if (kind === "stack") {
    return (
      <span className="nav-icon stack">
        <i />
        <i />
        <i />
      </span>
    );
  }
  if (kind === "bell") {
    return (
      <span className="nav-icon bell">
        <i />
        <i />
      </span>
    );
  }
  return (
    <span className="nav-icon pulse">
      <i />
      <i />
      <i />
    </span>
  );
}

export function Rail({
  active,
  onChange,
  health,
}: {
  active: Tab;
  onChange: (tab: Tab) => void;
  health: Health | null;
}) {
  return (
    <aside className="rail">
      <div className="rail-brand">
        <span className="rail-mark">F</span>
        <span className="rail-brand-text">
          <strong>FunPay Monitor</strong>
          <small>ценовой мониторинг</small>
        </span>
      </div>

      <nav className="rail-nav" aria-label="Разделы">
        <div className="rail-caption">НАВИГАЦИЯ</div>
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === active ? "nav-item active" : "nav-item"}
            onClick={() => onChange(item.id)}
            aria-current={item.id === active ? "page" : undefined}
          >
            <NavIcon kind={item.icon} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="rail-footer">
        <div className="rail-divider" />
        <div className={health ? "rail-status" : "rail-status down"}>
          <span className="rail-status-dot" />
          {health ? "API онлайн" : "API недоступен"}
        </div>
        <div className="rail-meta">
          <span>{health ? `v${health.version}` : "v0.3.0"}</span>
          <span>Windows · Linux</span>
        </div>
      </div>
    </aside>
  );
}
