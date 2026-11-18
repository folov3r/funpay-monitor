import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { PriceChart, type ChartPeriod } from "../components/PriceChart";
import { ago, lots, money, percentDelta } from "../format";
import type { Category, HistoryPoint, Notification, Offer, PriceSummary } from "../types";

const PERIODS: { id: ChartPeriod; label: string; days: number }[] = [
  { id: "24h", label: "24ч", days: 1 },
  { id: "7d", label: "7д", days: 7 },
  { id: "30d", label: "30д", days: 30 },
];

function eventLabel(notification: Notification): string {
  if (notification.mode === "lowest") {
    return `Минимум: ${money(notification.price)} ₽`;
  }
  if (notification.mode === "pct") {
    return `Скачок цены: ${money(notification.price)} ₽`;
  }
  return `Порог: ${money(notification.price)} ₽`;
}

const EVENT_COLORS: Record<Notification["mode"], string> = {
  lowest: "var(--green)",
  abs: "var(--blue)",
  pct: "var(--red)",
};

export function CategoriesView({ onOpenNotifications }: { onOpenNotifications: () => void }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [serverId, setServerId] = useState("");
  const [itemType, setItemType] = useState("");
  const [itemTypes, setItemTypes] = useState<string[]>([]);
  const [summary, setSummary] = useState<PriceSummary | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [counts, setCounts] = useState<Record<number, number>>({});
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [period, setPeriod] = useState<ChartPeriod>("7d");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const selected = categories.find((row) => row.id === selectedId) ?? null;
  const days = PERIODS.find((row) => row.id === period)?.days ?? 7;

  const loadCounts = useCallback(async (rows: Category[]) => {
    const results = await Promise.allSettled(
      rows.slice(0, 24).map(async (row) => ({ id: row.id, summary: await api.summary(row.id, {}) })),
    );
    const next: Record<number, number> = {};
    for (const result of results) {
      if (result.status === "fulfilled" && result.value.summary) {
        next[result.value.id] = result.value.summary.offer_count;
      }
    }
    setCounts(next);
  }, []);

  const loadSidebar = useCallback(async () => {
    try {
      const [nextCategories, nextNotifications] = await Promise.all([
        api.categories(),
        api.notifications(3),
      ]);
      setCategories(nextCategories);
      setNotifications(nextNotifications);
      setSelectedId((current) => current ?? nextCategories[0]?.id ?? null);
      setError(null);
      void loadCounts(nextCategories);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [loadCounts]);

  useEffect(() => {
    void loadSidebar();
  }, [loadSidebar]);

  useEffect(() => {
    if (selectedId === null) {
      return;
    }
    let cancelled = false;
    const filters = {
      server_id: serverId === "" ? null : Number(serverId),
      item_type: itemType || undefined,
    };
    Promise.all([
      api.summary(selectedId, filters),
      api.offers(selectedId, { ...filters, limit: 100 }),
      api.history(selectedId, { ...filters, days }),
    ])
      .then(([nextSummary, nextOffers, nextHistory]) => {
        if (cancelled) {
          return;
        }
        setSummary(nextSummary);
        setOffers(nextOffers);
        setHistory(nextHistory);
        setError(null);
        if (itemType === "") {
          setItemTypes(
            Array.from(new Set(nextOffers.map((offer) => offer.item_type).filter(Boolean))) as string[],
          );
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, serverId, itemType, days, reloadKey]);

  const sellerCount = useMemo(
    () => new Set(offers.map((offer) => offer.seller_name).filter(Boolean)).size,
    [offers],
  );

  const minDelta = useMemo(() => {
    if (history.length < 2) {
      return null;
    }
    return percentDelta(history[0].min_price, history[history.length - 1].min_price, days);
  }, [history, days]);

  const medianDelta = useMemo(() => {
    if (history.length < 2) {
      return null;
    }
    return percentDelta(history[0].median_price, history[history.length - 1].median_price, days);
  }, [history, days]);

  const totalOffers = useMemo(
    () => Object.values(counts).reduce((sum, value) => sum + value, 0),
    [counts],
  );

  function selectCategory(id: number) {
    if (id === selectedId) {
      return;
    }
    setSelectedId(id);
    setServerId("");
    setItemType("");
    setItemTypes([]);
    setNotice(null);
    setError(null);
  }

  async function reparse() {
    if (!selected) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.reparse(selected.id);
      setNotice(`Прогон: ${result.status}, ${result.offers_found} предложений`);
      setReloadKey((value) => value + 1);
      void loadSidebar();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const serverName = selected?.servers.find((server) => String(server.id) === serverId)?.name;

  return (
    <div className="workspace">
      <aside className="sidebar">
        <section className="panel">
          <div className="panel-title">
            <h2>Фильтры</h2>
          </div>
          <label className="field">
            <span>Игра</span>
            <select
              value={selectedId ?? ""}
              onChange={(event) => selectCategory(Number(event.target.value))}
            >
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.game_title ?? category.title}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{selected?.server_label ?? "Сервер"}</span>
            <select value={serverId} onChange={(event) => setServerId(event.target.value)}>
              <option value="">Любой</option>
              {(selected?.servers ?? []).map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Тип</span>
            <select value={itemType} onChange={(event) => setItemType(event.target.value)}>
              <option value="">Все</option>
              {itemTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
          <div className="filters-actions">
            <button className="button" onClick={() => setReloadKey((value) => value + 1)}>
              Применить
            </button>
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>Категории</h2>
            <span>{lots(totalOffers)}</span>
          </div>
          <div className="rows">
            {categories.map((category) => (
              <button
                key={category.id}
                className={category.id === selectedId ? "row active" : "row"}
                onClick={() => selectCategory(category.id)}
              >
                <span>{category.title}</span>
                <span className="count">{counts[category.id] ?? "—"}</span>
              </button>
            ))}
            {categories.length === 0 ? <p className="muted">Пока ничего не отслеживается.</p> : null}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>Последние события</h2>
          </div>
          <div className="events">
            {notifications.map((notification) => (
              <div className="event" key={notification.id}>
                <span
                  className="dot"
                  style={{ background: EVENT_COLORS[notification.mode] }}
                />
                <span className="label">{eventLabel(notification)}</span>
                <time>{ago(notification.sent_at)}</time>
              </div>
            ))}
            {notifications.length === 0 ? (
              <p className="muted">Событий пока нет.</p>
            ) : null}
          </div>
          <button className="link-button" onClick={onOpenNotifications}>
            Все уведомления →
          </button>
        </section>
      </aside>

      <main className="main">
        <div className="page-head">
          <div>
            <h1>
              {selected
                ? `${selected.game_title ?? selected.title}${serverName ? ` · ${serverName}` : ""}`
                : "Категории"}
            </h1>
            <p>
              {selected
                ? `обновлено ${ago(selected.last_parsed_at)} · ${summary?.offer_count ?? 0} предложений`
                : "Добавьте категорию FunPay, чтобы начать мониторинг"}
            </p>
          </div>
          <button className="button ghost small" onClick={() => void reparse()} disabled={busy || !selected}>
            {busy ? "Парсим…" : "Обновить"}
          </button>
        </div>

        {error ? <p className="error">{error}</p> : null}
        {notice ? <p className="notice">{notice}</p> : null}

        <div className="metrics">
          <div className="metric">
            <span className="metric-label">Минимум</span>
            <span className="metric-value">
              {summary ? `${money(summary.min_price)} ₽` : "—"}
            </span>
            <span className={minDelta ? `metric-note ${minDelta.direction}` : "metric-note"}>
              {minDelta ? minDelta.text : "нет истории"}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Медиана</span>
            <span className="metric-value">
              {summary ? `${money(summary.median_price)} ₽` : "—"}
            </span>
            <span className={medianDelta ? `metric-note ${medianDelta.direction}` : "metric-note"}>
              {medianDelta ? medianDelta.text : "нет истории"}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Предложений</span>
            <span className="metric-value">{summary?.offer_count ?? 0}</span>
            <span className="metric-note">{sellerCount} продавцов</span>
          </div>
        </div>

        <section className="panel">
          <div className="chart-head">
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
            <div className="spacer" />
            <div className="chips">
              {PERIODS.map((row) => (
                <button
                  key={row.id}
                  className={row.id === period ? "chip active" : "chip"}
                  onClick={() => setPeriod(row.id)}
                >
                  {row.label}
                </button>
              ))}
            </div>
          </div>
          <div className="chart-body">
            <PriceChart points={history} period={period} />
          </div>
        </section>

        <section className="panel">
          <div className="table-head">
            <h2>Лоты</h2>
            <span>
              {Math.min(offers.length, 5)} из {offers.length}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Продавец</th>
                  <th>Цена</th>
                  <th>Количество</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {offers.slice(0, 5).map((offer, index) => (
                  <tr key={offer.id} className={index === 0 ? "cheapest" : undefined}>
                    <td>
                      <span className="seller">{offer.seller_name ?? "—"}</span>
                      {offer.title ? <span className="seller-sub">{offer.title}</span> : null}
                    </td>
                    <td className="price">{money(offer.price)} ₽</td>
                    <td>{offer.amount ? money(offer.amount) : "—"}</td>
                    <td>
                      {offer.is_online ? <span className="badge online">онлайн</span> : null}
                      {offer.is_promo ? <span className="badge promo">промо</span> : null}
                      {!offer.is_online && !offer.is_promo ? <span className="dim">—</span> : null}
                    </td>
                  </tr>
                ))}
                {offers.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      Предложений нет.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
