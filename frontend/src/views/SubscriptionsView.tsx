import { useEffect, useState } from "react";
import { api } from "../api";
import { OffersTable } from "../components/OffersTable";
import { PriceChart } from "../components/PriceChart";
import { SummaryMetrics } from "../components/SummaryMetrics";
import { money } from "../format";
import type { AlertMode, Category, Subscription, SubscriptionStats } from "../types";

const MODE_LABELS: Record<AlertMode, string> = {
  abs: "ниже порога",
  pct: "падение на %",
  lowest: "новый минимум",
};

export function SubscriptionsView() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [stats, setStats] = useState<SubscriptionStats | null>(null);
  const [categoryId, setCategoryId] = useState("");
  const [serverId, setServerId] = useState("");
  const [mode, setMode] = useState<AlertMode>("abs");
  const [threshold, setThreshold] = useState("");
  const [itemType, setItemType] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    const [nextCategories, nextSubscriptions] = await Promise.all([
      api.categories(),
      api.subscriptions(),
    ]);
    setCategories(nextCategories);
    setSubscriptions(nextSubscriptions);
  }

  useEffect(() => {
    reload().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const selectedCategory = categories.find((row) => row.id === Number(categoryId)) ?? null;

  async function create() {
    if (!selectedCategory) {
      setError("Сначала выберите категорию.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createSubscription({
        category_id: selectedCategory.id,
        server_id: serverId === "" ? null : Number(serverId),
        mode,
        threshold: mode === "lowest" ? null : threshold || null,
        item_type: itemType.trim() || null,
        query: search.trim() || null,
      });
      setThreshold("");
      setItemType("");
      setSearch("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    await api.deleteSubscription(id);
    if (stats?.subscription.id === id) {
      setStats(null);
    }
    await reload();
  }

  async function showStats(id: number) {
    setError(null);
    try {
      setStats(await api.subscriptionStats(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <section className="panel">
          <div className="panel-title">
            <h2>Новая подписка</h2>
          </div>
          <label className="field">
            <span>Категория</span>
            <select
              value={categoryId}
              onChange={(event) => {
                setCategoryId(event.target.value);
                setServerId("");
              }}
            >
              <option value="">Выберите…</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.title}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{selectedCategory?.server_label ?? "Сервер"}</span>
            <select value={serverId} onChange={(event) => setServerId(event.target.value)}>
              <option value="">Любой</option>
              {(selectedCategory?.servers ?? []).map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Режим</span>
            <select value={mode} onChange={(event) => setMode(event.target.value as AlertMode)}>
              {(Object.keys(MODE_LABELS) as AlertMode[]).map((value) => (
                <option key={value} value={value}>
                  {MODE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
          {mode !== "lowest" ? (
            <label className="field">
              <span>{mode === "pct" ? "Процент" : "Порог, ₽"}</span>
              <input
                value={threshold}
                onChange={(event) => setThreshold(event.target.value)}
                inputMode="decimal"
                placeholder={mode === "pct" ? "5" : "1450"}
              />
            </label>
          ) : null}
          <label className="field">
            <span>Тип (необязательно)</span>
            <input value={itemType} onChange={(event) => setItemType(event.target.value)} />
          </label>
          <label className="field">
            <span>Название (необязательно)</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <div className="filters-actions">
            <button className="button" onClick={() => void create()} disabled={busy}>
              {busy ? "Сохраняем…" : "Создать подписку"}
            </button>
          </div>
          {error ? <p className="error">{error}</p> : null}
        </section>
      </aside>

      <main className="main">
        <div className="page-head">
          <div>
            <h1>Подписки</h1>
            <p>{subscriptions.length} активных правил уведомлений</p>
          </div>
        </div>

        <section className="panel">
          <div className="panel-title">
            <h2>Мои подписки</h2>
          </div>
          <div className="stack">
            {subscriptions.map((subscription) => (
              <div className="stack-item" key={subscription.id}>
                <div className="grow">
                  <strong>{subscription.category_title}</strong>
                  <p>
                    {MODE_LABELS[subscription.mode]}
                    {subscription.threshold ? ` · ${money(subscription.threshold)}` : ""}
                    {subscription.server_name ? ` · ${subscription.server_name}` : " · любой сервер"}
                    {subscription.item_type ? ` · ${subscription.item_type}` : ""}
                    {subscription.query ? ` · «${subscription.query}»` : ""}
                  </p>
                </div>
                <div className="actions">
                  <button className="button ghost tiny" onClick={() => void showStats(subscription.id)}>
                    Статистика
                  </button>
                  <button className="button danger tiny" onClick={() => void remove(subscription.id)}>
                    Удалить
                  </button>
                </div>
              </div>
            ))}
            {subscriptions.length === 0 ? <p className="muted">Подписок пока нет.</p> : null}
          </div>
        </section>

        {stats ? (
          <section className="panel">
            <div className="page-head">
              <div>
                <h1>{stats.subscription.category_title}</h1>
                <p>
                  {MODE_LABELS[stats.subscription.mode]}
                  {stats.subscription.threshold ? ` · ${money(stats.subscription.threshold)}` : ""}
                </p>
              </div>
              <button className="button ghost small" onClick={() => setStats(null)}>
                Закрыть
              </button>
            </div>
            <div style={{ marginTop: 16 }}>
              <SummaryMetrics summary={stats.summary} />
            </div>
            <div className="chart-head" style={{ marginTop: 20 }}>
              <h2>Динамика цен</h2>
              <div className="legend">
                <span>
                  <i style={{ background: "var(--green)" }} />
                  минимум
                </span>
                <span>
                  <i style={{ background: "var(--blue)" }} />
                  медиана
                </span>
              </div>
            </div>
            <div className="chart-body">
              <PriceChart points={stats.history} period="7d" />
            </div>
            <div className="table-head" style={{ marginTop: 20 }}>
              <h2>Самые дешёвые предложения</h2>
            </div>
            <OffersTable offers={stats.cheapest} />
          </section>
        ) : null}
      </main>
    </div>
  );
}
