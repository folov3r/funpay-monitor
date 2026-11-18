import { useEffect, useState } from "react";
import { api } from "./api";
import { TopBar } from "./components/TopBar";
import { CategoriesView } from "./views/CategoriesView";
import { NotificationsView } from "./views/NotificationsView";
import { StatusView } from "./views/StatusView";
import { SubscriptionsView } from "./views/SubscriptionsView";
import type { Health } from "./types";

type Tab = "categories" | "subscriptions" | "notifications" | "status";

const TABS: { id: Tab; label: string }[] = [
  { id: "categories", label: "Категории" },
  { id: "subscriptions", label: "Подписки" },
  { id: "notifications", label: "Уведомления" },
  { id: "status", label: "Состояние" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("categories");
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let active = true;
    let timer = 0;
    // The desktop window starts before the Python core is listening, so retry
    // quickly until the first successful response, then settle to a slow poll.
    const tick = async () => {
      try {
        const value = await api.health();
        if (!active) {
          return;
        }
        setHealth(value);
        timer = window.setTimeout(tick, 30000);
      } catch {
        if (!active) {
          return;
        }
        setHealth(null);
        timer = window.setTimeout(tick, 1500);
      }
    };
    void tick();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <div className="app">
      <TopBar health={health} />

      <nav className="tabs">
        {TABS.map((item) => (
          <button
            key={item.id}
            className={item.id === tab ? "tab active" : "tab"}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {health === null ? (
        <section className="panel boot">
          <h2>Запускаем локальное ядро…</h2>
          <p className="muted">
            Приложение подключается к локальному API. Обычно это занимает несколько секунд.
            Если сообщение не исчезает, закройте другой экземпляр программы и запустите её снова.
          </p>
        </section>
      ) : (
        <>
          {tab === "categories" ? (
            <CategoriesView onOpenNotifications={() => setTab("notifications")} />
          ) : null}
          {tab === "subscriptions" ? <SubscriptionsView /> : null}
          {tab === "notifications" ? <NotificationsView /> : null}
          {tab === "status" ? <StatusView /> : null}
        </>
      )}
    </div>
  );
}
