import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { PriceChart } from "./components/PriceChart";
import type {
  AlertMode,
  Category,
  HistoryPoint,
  Notification,
  Offer,
  PriceSummary,
  Status,
  Subscription,
  SubscriptionStats,
} from "./types";

const MODE_LABELS: Record<AlertMode, string> = {
  abs: "ниже порога",
  pct: "падение на %",
  lowest: "новый минимум",
};

function money(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value;
  }
  return number.toLocaleString("ru-RU", { maximumFractionDigits: 6 });
}

function moment(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString("ru-RU");
}

function SummaryCards({ summary }: { summary: PriceSummary | null }) {
  if (!summary) {
    return <p className="muted">Нет текущих предложений для выбранного среза.</p>;
  }
  return (
    <div className="cards">
      <div className="card">
        <span className="card-label">Минимум</span>
        <strong>{money(summary.min_price)} ₽</strong>
      </div>
      <div className="card">
        <span className="card-label">Медиана</span>
        <strong>{money(summary.median_price)} ₽</strong>
      </div>
      <div className="card">
        <span className="card-label">Предложений</span>
        <strong>{summary.offer_count}</strong>
      </div>
    </div>
  );
}

function OffersTable({ offers }: { offers: Offer[] }) {
  if (offers.length === 0) {
    return <p className="muted">Предложений нет.</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Цена</th>
            <th>Название</th>
            <th>Тип</th>
            <th>Количество</th>
            <th>Продавец</th>
          </tr>
        </thead>
        <tbody>
          {offers.map((offer) => (
            <tr key={offer.id}>
              <td className="price">{money(offer.price)} ₽</td>
              <td>{offer.title ?? "—"}</td>
              <td>{offer.item_type ?? "—"}</td>
              <td>{offer.amount ? money(offer.amount) : "—"}</td>
              <td>
                {offer.seller_name ?? "—"}
                {offer.is_online ? <span className="badge online">online</span> : null}
                {offer.is_promo ? <span className="badge promo">promo</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoryDetail({ category, onChanged }: { category: Category; onChanged: () => void }) {
  const [serverId, setServerId] = useState<string>("");
  const [itemType, setItemType] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [summary, setSummary] = useState<PriceSummary | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      server_id: serverId === "" ? null : Number(serverId),
      item_type: itemType || undefined,
      query: search.trim() || undefined,
    }),
    [serverId, itemType, search],
  );

  useEffect(() => {
    setServerId("");
    setItemType("");
    setSearch("");
    setNotice(null);
  }, [category.id]);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const [nextSummary, nextOffers, nextHistory] = await Promise.all([
          api.summary(category.id, filters),
          api.offers(category.id, { ...filters, limit: 100 }),
          api.history(category.id, { ...filters, days: 7 }),
        ]);
        if (!cancelled) {
          setSummary(nextSummary);
          setOffers(nextOffers);
          setHistory(nextHistory);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [category.id, filters]);

  const itemTypes = useMemo(
    () => Array.from(new Set(offers.map((offer) => offer.item_type).filter(Boolean))) as string[],
    [offers],
  );

  async function reparse() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.reparse(category.id);
      setNotice(
        `Прогон: ${result.status}, ${result.offers_found} предложений, уведомлений: ${result.alerts_sent}`,
      );
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>{category.title}</h2>
          <p className="muted">
            {category.game_title ?? category.type} · {category.url_path} · обновлено{" "}
            {moment(category.last_parsed_at)}
          </p>
        </div>
        <button className="ghost" onClick={reparse} disabled={busy}>
          {busy ? "Парсим…" : "Перепарсить"}
        </button>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}

      <div className="filters">
        <label>
          {category.server_label ?? "Сервер"}
          <select value={serverId} onChange={(event) => setServerId(event.target.value)}>
            <option value="">Любой</option>
            {category.servers.map((server) => (
              <option key={server.id} value={server.id}>
                {server.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Тип
          <select value={itemType} onChange={(event) => setItemType(event.target.value)}>
            <option value="">Все</option>
            {itemTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label>
          Название
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="например cosmic relic"
          />
        </label>
      </div>

      <SummaryCards summary={summary} />
      <h3>История за 7 дней</h3>
      <PriceChart points={history} />
      <h3>Самые дешёвые предложения</h3>
      <OffersTable offers={offers.slice(0, 10)} />
    </section>
  );
}

function CategoriesView() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function reload(select?: number) {
    const rows = await api.categories();
    setCategories(rows);
    if (select !== undefined) {
      setSelectedId(select);
    } else if (selectedId === null && rows.length > 0) {
      setSelectedId(rows[0].id);
    }
  }

  useEffect(() => {
    reload().catch((err) => setError(err instanceof Error ? err.message : String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function importCategory() {
    if (!url.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.importCategory(url.trim());
      setUrl("");
      setNotice(
        `Добавлено: ${result.category.title}, предложений ${result.offers_found}, снапшотов ${result.snapshots_created}`,
      );
      await reload(result.category.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const selected = categories.find((row) => row.id === selectedId) ?? null;

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>Категории</h2>
        <div className="import">
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://funpay.com/chips/30/"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void importCategory();
              }
            }}
          />
          <button onClick={importCategory} disabled={busy}>
            {busy ? "Читаем…" : "Добавить"}
          </button>
        </div>
        {notice ? <p className="notice">{notice}</p> : null}
        {error ? <p className="error">{error}</p> : null}
        <ul className="list">
          {categories.map((category) => (
            <li key={category.id}>
              <button
                className={category.id === selectedId ? "list-item active" : "list-item"}
                onClick={() => setSelectedId(category.id)}
              >
                <span>{category.title}</span>
                <small>{category.url_path}</small>
              </button>
            </li>
          ))}
          {categories.length === 0 ? <li className="muted">Пока ничего не отслеживается.</li> : null}
        </ul>
      </aside>
      <main className="content">
        {selected ? (
          <CategoryDetail category={selected} onChanged={() => void reload()} />
        ) : (
          <p className="muted">Добавьте ссылку на категорию FunPay, чтобы начать.</p>
        )}
      </main>
    </div>
  );
}

function SubscriptionsView() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [stats, setStats] = useState<SubscriptionStats | null>(null);
  const [categoryId, setCategoryId] = useState<string>("");
  const [serverId, setServerId] = useState<string>("");
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
    <div className="layout">
      <aside className="sidebar">
        <h2>Новая подписка</h2>
        <div className="form">
          <label>
            Категория
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
          <label>
            {selectedCategory?.server_label ?? "Сервер"}
            <select value={serverId} onChange={(event) => setServerId(event.target.value)}>
              <option value="">Любой</option>
              {(selectedCategory?.servers ?? []).map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Режим
            <select value={mode} onChange={(event) => setMode(event.target.value as AlertMode)}>
              {(Object.keys(MODE_LABELS) as AlertMode[]).map((value) => (
                <option key={value} value={value}>
                  {MODE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
          {mode !== "lowest" ? (
            <label>
              {mode === "pct" ? "Процент" : "Порог, ₽"}
              <input
                value={threshold}
                onChange={(event) => setThreshold(event.target.value)}
                inputMode="decimal"
                placeholder={mode === "pct" ? "5" : "1450"}
              />
            </label>
          ) : null}
          <label>
            Тип (необязательно)
            <input value={itemType} onChange={(event) => setItemType(event.target.value)} />
          </label>
          <label>
            Название (необязательно)
            <input value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <button onClick={create} disabled={busy}>
            {busy ? "Сохраняем…" : "Создать подписку"}
          </button>
          {error ? <p className="error">{error}</p> : null}
        </div>
      </aside>
      <main className="content">
        <section className="panel">
          <h2>Мои подписки</h2>
          {subscriptions.length === 0 ? <p className="muted">Подписок пока нет.</p> : null}
          <ul className="subscriptions">
            {subscriptions.map((subscription) => (
              <li key={subscription.id}>
                <div>
                  <strong>{subscription.category_title}</strong>
                  <p className="muted">
                    {MODE_LABELS[subscription.mode]}
                    {subscription.threshold ? ` · ${money(subscription.threshold)}` : ""}
                    {subscription.server_name ? ` · ${subscription.server_name}` : " · любой сервер"}
                    {subscription.item_type ? ` · ${subscription.item_type}` : ""}
                    {subscription.query ? ` · «${subscription.query}»` : ""}
                  </p>
                </div>
                <div className="actions">
                  <button className="ghost" onClick={() => void showStats(subscription.id)}>
                    Статистика
                  </button>
                  <button className="danger" onClick={() => void remove(subscription.id)}>
                    Удалить
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {stats ? (
          <section className="panel">
            <div className="panel-head">
              <h2>{stats.subscription.category_title}</h2>
              <button className="ghost" onClick={() => setStats(null)}>
                Закрыть
              </button>
            </div>
            <SummaryCards summary={stats.summary} />
            <PriceChart points={stats.history} />
            <OffersTable offers={stats.cheapest} />
          </section>
        ) : null}
      </main>
    </div>
  );
}

function NotificationsView() {
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
    <section className="panel">
      <div className="panel-head">
        <h2>Уведомления</h2>
        <button className="ghost" onClick={() => void reload()}>
          Обновить
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {notifications.length === 0 ? <p className="muted">Уведомлений пока не было.</p> : null}
      <ul className="notifications">
        {notifications.map((notification) => (
          <li key={notification.id}>
            <div>
              <strong>{notification.category_title}</strong>
              <p className="muted">
                {MODE_LABELS[notification.mode]} · {moment(notification.sent_at)}
              </p>
            </div>
            <span className="price">{money(notification.price)} ₽</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StatusView() {
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
    <section className="panel">
      <div className="panel-head">
        <h2>Состояние</h2>
        <button className="ghost" onClick={() => void reload()}>
          Обновить
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {status ? (
        <>
          <div className="cards">
            <div className="card">
              <span className="card-label">Категории</span>
              <strong>{status.categories}</strong>
            </div>
            <div className="card">
              <span className="card-label">Активные подписки</span>
              <strong>{status.active_subscriptions}</strong>
            </div>
            <div className="card">
              <span className="card-label">Предложения</span>
              <strong>{status.offers}</strong>
            </div>
          </div>
          <h3>Последние прогоны</h3>
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
                    <td>{moment(run.started_at)}</td>
                    <td>{run.offers_found}</td>
                    <td className="error">{run.error_text ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="muted">Загружаем…</p>
      )}
    </section>
  );
}

type Tab = "categories" | "subscriptions" | "notifications" | "status";

const TABS: { id: Tab; label: string }[] = [
  { id: "categories", label: "Категории" },
  { id: "subscriptions", label: "Подписки" },
  { id: "notifications", label: "Уведомления" },
  { id: "status", label: "Состояние" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("categories");
  const [health, setHealth] = useState<{ database: string; scheduler: boolean; version: string } | null>(
    null,
  );

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
        setHealth({ database: value.database, scheduler: value.scheduler, version: value.version });
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
      <header>
        <div>
          <h1>FunPay Monitor</h1>
          <p className="muted">Локальный мониторинг цен</p>
        </div>
        <div className={health ? "status ok" : "status down"}>
          {health
            ? `SQLite · ${health.scheduler ? "планировщик включён" : "планировщик выключен"} · v${health.version}`
            : "API недоступен"}
        </div>
      </header>

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
          </p>
        </section>
      ) : (
        <>
          {tab === "categories" ? <CategoriesView /> : null}
          {tab === "subscriptions" ? <SubscriptionsView /> : null}
          {tab === "notifications" ? <NotificationsView /> : null}
          {tab === "status" ? <StatusView /> : null}
        </>
      )}
    </div>
  );
}
