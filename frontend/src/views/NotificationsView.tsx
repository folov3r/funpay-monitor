import { useEffect, useState } from "react";
import { api } from "../api";
import { money, moment } from "../format";
import type { AlertMode, Notification } from "../types";

const MODE_LABELS: Record<AlertMode, string> = {
  abs: "ниже порога",
  pct: "падение на %",
  lowest: "новый минимум",
};

export function NotificationsView() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setNotifications(await api.notifications());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  return (
    <div className="workspace single">
      <main className="main">
        <div className="page-head">
          <div>
            <h1>Уведомления</h1>
            <p>История срабатываний по всем подпискам</p>
          </div>
          <button className="button ghost small" onClick={() => void reload()}>
            Обновить
          </button>
        </div>

        {error ? <p className="error">{error}</p> : null}

        <section className="panel">
          <div className="stack">
            {notifications.map((notification) => (
              <div className="stack-item" key={notification.id}>
                <div className="grow">
                  <strong>{notification.category_title}</strong>
                  <p>
                    {MODE_LABELS[notification.mode]} · {moment(notification.sent_at)}
                  </p>
                </div>
                <span className="price">{money(notification.price)} ₽</span>
              </div>
            ))}
            {notifications.length === 0 ? <p className="muted">Уведомлений пока не было.</p> : null}
          </div>
        </section>
      </main>
    </div>
  );
}
