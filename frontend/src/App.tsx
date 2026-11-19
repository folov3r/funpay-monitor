import { useEffect, useState } from "react";
import { api } from "./api";
import { Rail, type Tab } from "./components/Rail";
import { ToastProvider } from "./components/Toast";
import { CategoriesView } from "./views/CategoriesView";
import { NotificationsView } from "./views/NotificationsView";
import { StatusView } from "./views/StatusView";
import { SubscriptionsView } from "./views/SubscriptionsView";
import type { Health } from "./types";

const TABS: Tab[] = ["categories", "subscriptions", "notifications", "status"];

function tabFromHash(): Tab {
  const value = window.location.hash.replace("#", "");
  return TABS.includes(value as Tab) ? (value as Tab) : "categories";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function changeTab(next: Tab) {
    setTab(next);
    window.location.hash = next;
  }

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
    <ToastProvider>
      <div className="app">
        <Rail active={tab} onChange={changeTab} health={health} />

        <main className="stage">
          <div className="stage-inner">
            {health === null ? (
              <section className="panel boot">
                <h2>Запускаем локальное ядро…</h2>
                <p className="muted">
                  Приложение подключается к локальному API. Обычно это занимает несколько секунд.
                  Если сообщение не исчезает, закройте другой экземпляр программы и запустите её
                  снова.
                </p>
              </section>
            ) : (
              <>
                {tab === "categories" ? <CategoriesView /> : null}
                {tab === "subscriptions" ? <SubscriptionsView /> : null}
                {tab === "notifications" ? <NotificationsView /> : null}
                {tab === "status" ? <StatusView health={health} /> : null}
              </>
            )}
          </div>
        </main>
      </div>
    </ToastProvider>
  );
}
