import { useEffect, useState } from "react";
import { api } from "../api";
import { moment } from "../format";
import type { Status } from "../types";

export function StatusView() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setStatus(await api.status());
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
            <h1>Состояние</h1>
            <p>Локальное ядро, база и последние прогоны парсера</p>
          </div>
          <button className="button ghost small" onClick={() => void reload()}>
            Обновить
          </button>
        </div>

        {error ? <p className="error">{error}</p> : null}

        {status ? (
          <>
            <div className="status-grid">
              <div className="metric">
                <span className="metric-label">Категории</span>
                <span className="metric-value">{status.categories}</span>
                <span className="metric-note">активных: {status.active_categories}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Активные подписки</span>
                <span className="metric-value">{status.active_subscriptions}</span>
                <span className="metric-note">пользователей: {status.users}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Предложения</span>
                <span className="metric-value">{status.offers}</span>
                <span className="metric-note">в локальной базе</span>
              </div>
            </div>

            <section className="panel">
              <div className="table-head">
                <h2>Последние прогоны</h2>
                <span>{status.parse_runs.length} записей</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Категория</th>
                      <th>Статус</th>
                      <th>Начало</th>
                      <th>Предложений</th>
                      <th>Ошибка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.parse_runs.map((run, index) => (
                      <tr key={`${run.category_id}-${index}`}>
                        <td>{run.category_title}</td>
                        <td>{run.status}</td>
                        <td className="muted">{moment(run.started_at)}</td>
                        <td>{run.offers_found}</td>
                        <td className="error">{run.error_text ?? "—"}</td>
                      </tr>
                    ))}
                    {status.parse_runs.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="muted">
                          Прогонов пока не было.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : (
          <p className="muted">Загружаем…</p>
        )}
      </main>
    </div>
  );
}
