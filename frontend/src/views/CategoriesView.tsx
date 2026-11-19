import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { LotCardModal } from "../components/LotCard";
import { PageHeader } from "../components/PageHeader";
import { PriceChart, type ChartPeriod } from "../components/PriceChart";
import { StatTile } from "../components/StatTile";
import { useToast } from "../components/Toast";
import { ago, agoLong, lots, money, offersLabel, percentDelta } from "../format";
import type { Category, HistoryPoint, Offer, PriceSummary } from "../types";

const PERIODS: { id: ChartPeriod; label: string; days: number; suffix: string }[] = [
  { id: "24h", label: "24ч", days: 1, suffix: " · 24 часа" },
  { id: "7d", label: "7д", days: 7, suffix: " · 7 дней" },
  { id: "30d", label: "30д", days: 30, suffix: " · 30 дней" },
];

function gamesWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return "игра";
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return "игры";
  }
  return "игр";
}

function categoryName(category: Category | null): string {
  if (!category) {
    return "Категории";
  }
  return category.game_title ?? category.title;
}

export function CategoriesView() {
  const toast = useToast();
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [serverId, setServerId] = useState("");
  const [summaries, setSummaries] = useState<Record<number, PriceSummary | null>>({});
  const [summary, setSummary] = useState<PriceSummary | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [period, setPeriod] = useState<ChartPeriod>("7d");
  const [sort, setSort] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lotOffer, setLotOffer] = useState<Offer | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const selected = categories.find((row) => row.id === selectedId) ?? null;
  const periodMeta = PERIODS.find((row) => row.id === period) ?? PERIODS[1];
  const days = periodMeta.days;

  const loadSidebar = useCallback(async () => {
    try {
      const rows = await api.categories();
      setCategories(rows);
      setSelectedId((current) => current ?? rows[0]?.id ?? null);
      setError(null);
      const results = await Promise.allSettled(
        rows.slice(0, 24).map(async (row) => ({ id: row.id, summary: await api.summary(row.id, {}) })),
      );
      const next: Record<number, PriceSummary | null> = {};
      for (const result of results) {
        if (result.status === "fulfilled") {
          next[result.value.id] = result.value.summary;
        }
      }
      setSummaries(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void loadSidebar();
  }, [loadSidebar]);

  useEffect(() => {
    if (selectedId === null) {
      return;
    }
    let cancelled = false;
    const filters = { server_id: serverId === "" ? null : Number(serverId) };
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
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, serverId, days, reloadKey]);

  const sellerCount = useMemo(
    () => new Set(offers.map((offer) => offer.seller_name).filter(Boolean)).size,
    [offers],
  );

  const totalOffers = useMemo(
    () =>
      Object.values(summaries).reduce((sum, row) => sum + (row?.offer_count ?? 0), 0),
    [summaries],
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

  const visibleOffers = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rows = query
      ? offers.filter((offer) =>
          `${offer.seller_name ?? ""} ${offer.title ?? ""}`.toLowerCase().includes(query),
        )
      : offers;
    return [...rows].sort((a, b) =>
      sort === "asc" ? Number(a.price) - Number(b.price) : Number(b.price) - Number(a.price),
    );
  }, [offers, search, sort]);

  const shownOffers = visibleOffers.slice(0, 5);
  const gameName = categoryName(selected);

  function selectCategory(id: number) {
    if (id === selectedId) {
      return;
    }
    setSelectedId(id);
    setServerId("");
    setError(null);
  }

  async function reparse() {
    if (!selected) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.reparse(selected.id);
      toast({
        title: "Данные обновлены",
        subtitle: `Прогон: ${result.status}, ${offersLabel(result.offers_found)}`,
        tone: "accent",
      });
      setReloadKey((value) => value + 1);
      void loadSidebar();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast({ title: "Не удалось обновить", subtitle: String(err), tone: "red" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Категории"
        subtitle={`${categories.length} ${gamesWord(categories.length)} · ${offersLabel(totalOffers)} · обновлено ${agoLong(selected?.last_parsed_at)}`}
        tools={
          <label className="search-field">
            <span className="search-glyph" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Найти игру или лот"
              aria-label="Найти игру или лот"
            />
          </label>
        }
        action={
          <button
            type="button"
            className="btn primary header-action"
            onClick={() => void reparse()}
            disabled={busy || !selected}
          >
            {busy ? "Парсим…" : "Обновить"}
          </button>
        }
      />

      <div className="screen">
        {error ? <div className="banner error">{error}</div> : null}

        <div className="kpi-row">
          <StatTile
            label="ИГРЫ"
            value={categories.length}
            hint={`${categories.filter((row) => row.is_active).length} активных`}
            hintTone="muted"
            dotTone="accent"
          />
          <StatTile
            label="ПРЕДЛОЖЕНИЯ"
            value={money(totalOffers)}
            hint={`${sellerCount} продавцов в выборке`}
            hintTone="mint"
            dotTone="mint"
          />
          <StatTile
            label="МИНИМАЛЬНАЯ ЦЕНА"
            value={summary ? `${money(summary.min_price)} ₽` : "—"}
            hint={minDelta ? minDelta.text : "нет истории"}
            hintTone="muted"
            dotTone="mint"
          />
          <StatTile
            label="МЕДИАНА"
            value={summary ? `${money(summary.median_price)} ₽` : "—"}
            hint={medianDelta ? medianDelta.text : "нет истории"}
            hintTone="amber"
            dotTone="amber"
          />
        </div>

        <div className="grid-320-648">
          <section className="panel games-panel">
            <div className="panel-head">
              <h2>Игры</h2>
              <span className="count-badge">{categories.length}</span>
            </div>

            <div className="game-list">
              {categories.map((category) => {
                const on = category.id === selectedId;
                const rowSummary = summaries[category.id];
                const delta = on ? medianDelta : null;
                return (
                  <button
                    key={category.id}
                    type="button"
                    className={on ? "game-row active" : "game-row"}
                    onClick={() => selectCategory(category.id)}
                  >
                    <span className="game-name">{categoryName(category)}</span>
                    <span className="game-meta">
                      {lots(rowSummary?.offer_count ?? 0)} ·{" "}
                      {category.is_active ? "активна" : "выключена"}
                    </span>
                    <span className="game-price">
                      {rowSummary ? `${money(rowSummary.median_price)} ₽` : "—"}
                    </span>
                    {delta && delta.direction !== "flat" ? (
                      <span className="delta-chip">{delta.text.split(" за ")[0]}</span>
                    ) : null}
                  </button>
                );
              })}
              {categories.length === 0 ? (
                <p className="empty-note">Пока ничего не отслеживается.</p>
              ) : null}
            </div>

            <div className="soft-divider" />
            <div className="mini-caption">СЕРВЕР</div>
            <div className="chip-row">
              <button
                type="button"
                className={serverId === "" ? "chip active" : "chip"}
                onClick={() => setServerId("")}
              >
                Все
              </button>
              {(selected?.servers ?? []).map((server) => (
                <button
                  key={server.id}
                  type="button"
                  className={String(server.id) === serverId ? "chip active" : "chip"}
                  onClick={() => setServerId(String(server.id))}
                >
                  {server.name}
                </button>
              ))}
            </div>
          </section>

          <section className="panel chart-panel">
            <div className="panel-head chart-head">
              <div>
                <h2>Динамика цен</h2>
                <p className="panel-sub">
                  {gameName} · минимум и медиана{periodMeta.suffix}
                </p>
              </div>
              <div className="segmented">
                {PERIODS.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    className={row.id === period ? "active" : ""}
                    onClick={() => setPeriod(row.id)}
                  >
                    {row.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="legend">
              <span>
                <i style={{ background: "var(--teal)" }} />
                минимум
              </span>
              <span>
                <i style={{ background: "var(--accent)" }} />
                медиана
              </span>
            </div>

            <PriceChart points={history} period={period} height={206} />
          </section>
        </div>

        <section className="panel lots-panel">
          <div className="panel-head">
            <div className="inline-title">
              <h2>Лоты</h2>
              <span className="panel-sub">
                {shownOffers.length} из {visibleOffers.length} · обновлено{" "}
                {agoLong(selected?.last_parsed_at)}
              </span>
            </div>
            <button
              type="button"
              className="chip sort-chip"
              onClick={() => setSort((value) => (value === "asc" ? "desc" : "asc"))}
            >
              {sort === "asc" ? "Сначала дешёвые" : "Сначала дорогие"}
              <span className="caret">▾</span>
            </button>
          </div>

          <div className="table-wrap">
            <table className="fixed">
              <colgroup>
                <col style={{ width: "39.8%" }} />
                <col style={{ width: "21.3%" }} />
                <col style={{ width: "25.1%" }} />
                <col style={{ width: "13.8%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>Продавец</th>
                  <th>Цена</th>
                  <th>Количество</th>
                  <th>Обновлено</th>
                </tr>
              </thead>
              <tbody>
                {shownOffers.map((offer) => {
                  const seller = offer.seller_name ?? "—";
                  return (
                    <tr
                      key={offer.id}
                      className="clickable"
                      onClick={() => setLotOffer(offer)}
                    >
                      <td>
                        <span className="seller-cell">
                          <span className="avatar">
                            {seller.trim().charAt(0).toUpperCase() || "?"}
                            {offer.is_online ? <i className="avatar-dot" /> : null}
                          </span>
                          <span className="seller">{seller}</span>
                        </span>
                      </td>
                      <td className="price">{money(offer.price)} ₽</td>
                      <td>{offer.amount ? `${money(offer.amount)} шт` : "—"}</td>
                      <td className="muted">{ago(offer.parsed_at)}</td>
                    </tr>
                  );
                })}
                {shownOffers.length === 0 ? (
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
      </div>

      {lotOffer ? (
        <LotCardModal
          offer={lotOffer}
          categoryTitle={gameName}
          onClose={() => setLotOffer(null)}
          onOpen={() => {
            setLotOffer(null);
            toast({
              title: "Открываем FunPay",
              subtitle: "В приложении откроется браузер",
              tone: "accent",
            });
          }}
        />
      ) : null}
    </>
  );
}
