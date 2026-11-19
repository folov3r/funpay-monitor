import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ConfirmDialog, Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { PriceChart } from "../components/PriceChart";
import { useToast } from "../components/Toast";
import { money, moment } from "../format";
import type {
  AlertMode,
  Category,
  Notification,
  Subscription,
  SubscriptionStats,
} from "../types";

const MODES: {
  mode: AlertMode;
  caption: string;
  label: string;
  unit: string;
  value: string;
  hint: string;
}[] = [
  {
    mode: "abs",
    caption: "порог",
    label: "ПОРОГ, ₽",
    unit: "₽",
    value: "0,80",
    hint: "сработает при цене ниже 0,80 ₽",
  },
  {
    mode: "pct",
    caption: "падение %",
    label: "ПАДЕНИЕ, %",
    unit: "%",
    value: "15",
    hint: "сработает при падении цены на 15%",
  },
  {
    mode: "lowest",
    caption: "минимум",
    label: "ИСТОРИЯ, ДНЕЙ",
    unit: "дн",
    value: "30",
    hint: "сработает при новом минимуме за 30 дней",
  },
];

const MODE_CAPTION: Record<AlertMode, string> = {
  abs: "порог",
  pct: "падение",
  lowest: "минимум",
};

const MODE_EVENT: Record<AlertMode, string> = {
  abs: "Порог сработал",
  pct: "Скачок цены",
  lowest: "Новый минимум",
};

function rulesWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return "активное правило";
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return "активных правила";
  }
  return "активных правил";
}

function categoriesWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return "категория";
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return "категории";
  }
  return "категорий";
}

function defaultThreshold(mode: AlertMode): string {
  return MODES.find((row) => row.mode === mode)?.value ?? "";
}

function ruleName(subscription: Subscription): string {
  return `${subscription.category_title} · ${MODE_CAPTION[subscription.mode]}`;
}

function ruleLine(subscription: Subscription): string {
  const server = subscription.server_name ?? "любой сервер";
  if (subscription.mode === "lowest") {
    return `новый минимум · ${server}`;
  }
  const suffix = subscription.mode === "pct" ? "%" : " ₽";
  return `${MODE_CAPTION[subscription.mode]} ${money(subscription.threshold)}${suffix} · ${server}`;
}

function ruleHint(subscription: Subscription): string {
  return `${subscription.category_title} · создана ${moment(subscription.created_at)}`;
}

function SelectBox({
  label,
  value,
  placeholder,
  options,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  placeholder: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  hint?: string;
}) {
  const [open, setOpen] = useState(false);
  const current = options.find((row) => row.value === value);

  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="select-wrap">
        <button type="button" className="select-control" onClick={() => setOpen((v) => !v)}>
          <span className={current ? "" : "placeholder"}>{current?.label ?? placeholder}</span>
          <span className="caret">▾</span>
        </button>
        {open ? (
          <>
            <div className="select-overlay" onClick={() => setOpen(false)} />
            <div className="dropdown">
              {options.map((row) => (
                <button
                  key={row.value}
                  type="button"
                  className={row.value === value ? "dropdown-item active" : "dropdown-item"}
                  onClick={() => {
                    onChange(row.value);
                    setOpen(false);
                  }}
                >
                  <span>{row.label}</span>
                  {row.value === value ? <span className="check">✓</span> : null}
                </button>
              ))}
            </div>
          </>
        ) : null}
      </div>
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

function shortMoment(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function downloadCsv(subscription: Subscription, notifications: Notification[]) {
  const lines = ["дата;событие;цена"];
  for (const note of notifications) {
    lines.push(`${shortMoment(note.sent_at)};${MODE_EVENT[note.mode]};${money(note.price)}`);
  }
  const blob = new Blob([`\uFEFF${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${subscription.category_title}-${subscription.id}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export function SubscriptionsView() {
  const toast = useToast();
  const [categories, setCategories] = useState<Category[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [stats, setStats] = useState<SubscriptionStats | null>(null);
  const [statsOpen, setStatsOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const [categoryId, setCategoryId] = useState("");
  const [serverId, setServerId] = useState("");
  const [mode, setMode] = useState<AlertMode>("abs");
  const [threshold, setThreshold] = useState(defaultThreshold("abs"));
  const [itemType, setItemType] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCategory = categories.find((row) => row.id === Number(categoryId)) ?? null;
  const selectedSub = subscriptions.find((row) => row.id === selectedId) ?? null;
  const modeMeta = MODES.find((row) => row.mode === mode) ?? MODES[0];
  const selectedThreshold = useMemo(() => {
    const value = Number(String(selectedSub?.threshold ?? "").replace(",", "."));
    return selectedSub?.mode === "abs" && Number.isFinite(value) && value > 0 ? value : null;
  }, [selectedSub]);

  const subNotifications = useMemo(
    () => notifications.filter((note) => note.subscription_id === selectedSub?.id),
    [notifications, selectedSub],
  );

  const reload = useCallback(async () => {
    const [nextCategories, nextSubscriptions, nextNotifications] = await Promise.all([
      api.categories(),
      api.subscriptions(),
      api.notifications(50),
    ]);
    setCategories(nextCategories);
    setSubscriptions(nextSubscriptions);
    setNotifications(nextNotifications);
    setSelectedId((current) => {
      if (current !== null && nextSubscriptions.some((row) => row.id === current)) {
        return current;
      }
      return nextSubscriptions[0]?.id ?? null;
    });
    setCategoryId((current) => current || String(nextCategories[0]?.id ?? ""));
  }, []);

  useEffect(() => {
    reload().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [reload]);

  useEffect(() => {
    if (selectedId === null) {
      setStats(null);
      setStatsOpen(false);
      return;
    }
    let cancelled = false;
    api
      .subscriptionStats(selectedId, 30)
      .then((value) => {
        if (!cancelled) {
          setStats(value);
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
  }, [selectedId]);

  const categoryOptions = useMemo(
    () =>
      categories.map((row) => ({
        value: String(row.id),
        label: row.game_title ?? row.title,
      })),
    [categories],
  );

  const serverOptions = useMemo(
    () => [
      { value: "", label: "Любой сервер" },
      ...(selectedCategory?.servers ?? []).map((server) => ({
        value: String(server.id),
        label: server.name,
      })),
    ],
    [selectedCategory],
  );

  function resetForm(announce = false) {
    setCategoryId(String(categories[0]?.id ?? ""));
    setServerId("");
    setMode("abs");
    setThreshold(defaultThreshold("abs"));
    setItemType("");
    setName("");
    setError(null);
    if (announce) {
      toast({ title: "Форма очищена", subtitle: "Можно создать новую подписку", tone: "accent" });
    }
  }

  function duplicateSelected() {
    if (!selectedSub) {
      return;
    }
    setCategoryId(String(selectedSub.category_id));
    setServerId(selectedSub.server_id ? String(selectedSub.server_id) : "");
    setMode(selectedSub.mode);
    setThreshold(
      selectedSub.threshold ? String(selectedSub.threshold).replace(".", ",") : defaultThreshold(selectedSub.mode),
    );
    setItemType(selectedSub.item_type ?? "");
    setName(selectedSub.query ? `${selectedSub.query} (копия)` : "");
    toast({
      title: "Подписка скопирована",
      subtitle: "Проверьте условия и сохраните",
      tone: "mint",
    });
  }

  async function create() {
    if (!selectedCategory) {
      setError("Сначала выберите категорию.");
      return;
    }
    if (mode !== "lowest" && !threshold.trim()) {
      setError("Укажите значение условия.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await api.createSubscription({
        category_id: selectedCategory.id,
        server_id: serverId === "" ? null : Number(serverId),
        mode,
        threshold:
          mode === "lowest" ? null : threshold.trim().replace(",", "."),
        item_type: itemType.trim() || null,
        query: name.trim() || null,
      });
      setThreshold(defaultThreshold(mode));
      setItemType("");
      setName("");
      await reload();
      setSelectedId(created.id);
      toast({
        title: "Подписка создана",
        subtitle: ruleName(created),
        tone: "mint",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast({ title: "Не удалось сохранить", subtitle: String(err), tone: "red" });
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(subscription: Subscription) {
    try {
      const next = await api.setSubscriptionActive(subscription.id, !subscription.is_active);
      setSubscriptions((rows) =>
        rows.map((row) => (row.id === next.id ? next : row)),
      );
      toast({
        title: next.is_active ? "Подписка включена" : "Подписка выключена",
        subtitle: ruleName(next),
        tone: next.is_active ? "mint" : "amber",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast({ title: "Не удалось изменить", subtitle: String(err), tone: "red" });
    }
  }

  async function remove() {
    if (deleteId === null) {
      return;
    }
    try {
      await api.deleteSubscription(deleteId);
      setDeleteId(null);
      setStatsOpen(false);
      await reload();
      toast({ title: "Подписка удалена", subtitle: "История осталась в базе", tone: "amber" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast({ title: "Не удалось удалить", subtitle: String(err), tone: "red" });
    }
  }

  async function importFromFile(file: File) {
    setMenuOpen(false);
    try {
      const text = await file.text();
      const urls = Array.from(text.matchAll(/https?:\/\/[^\s,"']+/g)).map((match) => match[0]);
      if (urls.length === 0) {
        toast({ title: "В файле нет ссылок", subtitle: "Нужны адреса FunPay", tone: "amber" });
        return;
      }
      let imported = 0;
      for (const url of urls) {
        try {
          await api.importCategory(url);
          imported += 1;
        } catch {
          // Keep importing the rest; the toast reports how many succeeded.
        }
      }
      await reload();
      toast({
        title: imported > 0 ? "Импорт завершён" : "Импорт не удался",
        subtitle: `${imported} из ${urls.length} ссылок`,
        tone: imported > 0 ? "mint" : "red",
      });
    } catch (err) {
      toast({ title: "Не удалось прочитать файл", subtitle: String(err), tone: "red" });
    } finally {
      if (fileInput.current) {
        fileInput.current.value = "";
      }
    }
  }

  const activeCount = subscriptions.filter((row) => row.is_active).length;

  return (
    <>
      <PageHeader
        title="Подписки"
        subtitle={`${activeCount} ${rulesWord(activeCount)} · ${categories.length} ${categoriesWord(categories.length)} под наблюдением`}
        action={
          <div className="menu-anchor">
            <button
              type="button"
              className="btn primary header-action"
              onClick={() => setMenuOpen((value) => !value)}
            >
              Действия
            </button>
            {menuOpen ? (
              <>
                <div className="menu-overlay" onClick={() => setMenuOpen(false)} />
                <div className="menu" role="menu">
                  <div className="menu-caption">ДЕЙСТВИЯ</div>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      resetForm(true);
                    }}
                  >
                    Новая подписка
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!selectedSub}
                    onClick={() => {
                      setMenuOpen(false);
                      duplicateSelected();
                    }}
                  >
                    Дублировать выбранную
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => fileInput.current?.click()}
                  >
                    Импорт из файла
                  </button>
                  <div className="menu-divider" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      resetForm(true);
                    }}
                  >
                    Очистить форму
                  </button>
                </div>
              </>
            ) : null}
            <input
              ref={fileInput}
              type="file"
              accept=".txt,.csv,.json"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  void importFromFile(file);
                }
              }}
            />
          </div>
        }
      />

      <div className="screen">
        {error ? <div className="banner error">{error}</div> : null}

        <div className="grid-360-608">
          <section className="panel form-panel">
            <h2>Новая подписка</h2>
            <p className="panel-sub">Правило сработает, когда цена пересечёт условие</p>

            <SelectBox
              label="КАТЕГОРИЯ"
              value={categoryId}
              placeholder="Выберите категорию"
              options={categoryOptions}
              onChange={(value) => {
                setCategoryId(value);
                setServerId("");
              }}
            />
            <SelectBox
              label="СЕРВЕР"
              value={serverId}
              placeholder="Любой сервер"
              options={serverOptions}
              onChange={setServerId}
            />

            <div className="field">
              <span className="field-label">РЕЖИМ</span>
              <div className="mode-switch">
                {MODES.map((row) => (
                  <button
                    key={row.mode}
                    type="button"
                    className={row.mode === mode ? "active" : ""}
                    onClick={() => {
                      setMode(row.mode);
                      setThreshold(defaultThreshold(row.mode));
                    }}
                  >
                    {row.caption}
                  </button>
                ))}
              </div>
            </div>

            <div className="field threshold-field">
              <span className="field-label">{modeMeta.label}</span>
              <div className="threshold-box">
                <input
                  value={mode === "lowest" ? "30" : threshold}
                  onChange={(event) => setThreshold(event.target.value)}
                  inputMode="decimal"
                  disabled={mode === "lowest"}
                  aria-label={modeMeta.label}
                />
                <span className="threshold-unit">{modeMeta.unit}</span>
              </div>
              <span className="field-hint">{modeMeta.hint}</span>
            </div>

            <div className="field">
              <span className="field-label">ТИП ЛОТА</span>
              <input
                className="text-control"
                value={itemType}
                onChange={(event) => setItemType(event.target.value)}
                placeholder="Любой"
              />
            </div>

            <div className="field">
              <span className="field-label">НАЗВАНИЕ</span>
              <input
                className="text-control"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Например, Robux"
              />
            </div>

            <button
              type="button"
              className="btn primary submit"
              onClick={() => void create()}
              disabled={busy}
            >
              {busy ? "Сохраняем…" : "Создать подписку"}
            </button>

            <p className="footnote">Уведомление придёт в систему и внутрь приложения.</p>
            <p className="footnote">Проверка выполняется после каждого прогона парсера.</p>
          </section>

          <div className="right-stack">
            <section className="panel subs-panel">
              <div className="panel-head">
                <h2>Мои подписки</h2>
                <span className="count-badge">{activeCount}</span>
              </div>

              <div className="sub-list">
                {subscriptions.map((subscription) => (
                  <div
                    key={subscription.id}
                    className={[
                      "sub-row",
                      subscription.id === selectedId ? "active" : "",
                      subscription.is_active ? "" : "off",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedId(subscription.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        setSelectedId(subscription.id);
                      }
                    }}
                  >
                    <div className="sub-copy">
                      <strong>{ruleName(subscription)}</strong>
                      <span>{ruleLine(subscription)}</span>
                      <small>
                        {ruleHint(subscription)} ·{" "}
                        {subscription.is_active ? "включена" : "выключена"}
                      </small>
                    </div>
                    <div className="sub-actions">
                      <button
                        type="button"
                        className="chip accent"
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedId(subscription.id);
                          setStatsOpen(true);
                        }}
                      >
                        Статистика
                      </button>
                      <button
                        type="button"
                        className={subscription.is_active ? "chip" : "chip accent"}
                        onClick={(event) => {
                          event.stopPropagation();
                          void toggleActive(subscription);
                        }}
                      >
                        {subscription.is_active ? "Выключить" : "Включить"}
                      </button>
                      <button
                        type="button"
                        className="chip danger"
                        onClick={(event) => {
                          event.stopPropagation();
                          setDeleteId(subscription.id);
                        }}
                      >
                        Удалить
                      </button>
                    </div>
                  </div>
                ))}
                {subscriptions.length === 0 ? (
                  <div className="empty-block">
                    <strong>Пока нет подписок</strong>
                    <span>Создайте правило в форме слева — оно появится здесь</span>
                  </div>
                ) : null}
              </div>

              <p className="footnote">
                Подписки хранятся локально: пользователь VK 0 — этот компьютер.
              </p>
            </section>

            <section className="panel stats-panel">
              <h2>Статистика подписки</h2>

              {!selectedSub ? (
                <div className="empty-block">
                  <strong>Нет выбранной подписки</strong>
                  <span>Статистика появится после создания первой подписки</span>
                </div>
              ) : (
                <>
                  <p className="panel-sub">
                    {ruleName(selectedSub)} · последние 30 дней
                  </p>

                  <div className="stat-boxes">
                    <div className="stat-box">
                      <span>СРАБАТЫВАНИЙ</span>
                      <strong>{subNotifications.length}</strong>
                      <small className="tone-mint">
                        {
                          subNotifications.filter(
                            (note) =>
                              Date.now() - new Date(note.sent_at).getTime() < 7 * 86_400_000,
                          ).length
                        }{" "}
                        за неделю
                      </small>
                    </div>
                    <div className="stat-box">
                      <span>СРЕДНЯЯ ЦЕНА</span>
                      <strong>
                        {stats?.summary ? `${money(stats.summary.median_price)} ₽` : "—"}
                      </strong>
                      <small className="tone-muted">за 30 дней</small>
                    </div>
                    <div className="stat-box">
                      <span>МИНИМУМ</span>
                      <strong>
                        {stats?.summary ? `${money(stats.summary.min_price)} ₽` : "—"}
                      </strong>
                      <small className="tone-mint">в локальной базе</small>
                    </div>
                  </div>

                  <div className="mini-caption spaced">Цена и порог</div>
                  <div className="stats-chart">
                    <PriceChart
                      points={stats?.history ?? []}
                      period="7d"
                      height={116}
                      threshold={selectedThreshold}
                      thresholdLabel={
                        selectedThreshold !== null
                          ? `порог ${money(selectedThreshold)} ₽`
                          : undefined
                      }
                      compact
                    />
                  </div>

                  <div className="mini-caption spaced">ПОСЛЕДНИЕ СРАБАТЫВАНИЯ</div>
                  <div className="event-list">
                    {subNotifications.slice(0, 3).map((note) => (
                      <div className="event-row" key={note.id}>
                        <span>{shortMoment(note.sent_at)}</span>
                        <strong>
                          {MODE_EVENT[note.mode]} — {money(note.price)} ₽
                        </strong>
                        <small>система</small>
                      </div>
                    ))}
                    {subNotifications.length === 0 ? (
                      <p className="empty-note">Срабатываний пока не было.</p>
                    ) : null}
                  </div>
                </>
              )}
            </section>
          </div>
        </div>
      </div>

      {statsOpen && stats && selectedSub ? (
        <Modal
          caption={`ПОДПИСКА · ${selectedSub.category_title.toUpperCase()} · ${MODE_CAPTION[selectedSub.mode].toUpperCase()}`}
          title="Статистика подписки"
          onClose={() => setStatsOpen(false)}
          width={760}
          className="stats-modal"
        >
          <p className="panel-sub">
            {ruleLine(selectedSub)} · последние 30 дней · срабатываний:{" "}
            {subNotifications.length}
          </p>

          <div className="stat-boxes wide">
            <div className="stat-box">
              <span>СРАБАТЫВАНИЙ</span>
              <strong>{subNotifications.length}</strong>
              <small className="tone-mint">
                {
                  subNotifications.filter(
                    (note) => Date.now() - new Date(note.sent_at).getTime() < 7 * 86_400_000,
                  ).length
                }{" "}
                за неделю
              </small>
            </div>
            <div className="stat-box">
              <span>СРЕДНЯЯ ЦЕНА</span>
              <strong>{stats.summary ? `${money(stats.summary.median_price)} ₽` : "—"}</strong>
              <small className="tone-muted">за 30 дней</small>
            </div>
            <div className="stat-box">
              <span>МИНИМУМ</span>
              <strong>{stats.summary ? `${money(stats.summary.min_price)} ₽` : "—"}</strong>
              <small className="tone-mint">в локальной базе</small>
            </div>
          </div>

          <div className="mini-caption spaced">Цена и порог</div>
          <div className="stats-chart">
            <PriceChart
              points={stats.history}
              period="7d"
              height={116}
              threshold={selectedThreshold}
              thresholdLabel={
                selectedThreshold !== null ? `порог ${money(selectedThreshold)} ₽` : undefined
              }
            />
          </div>

          <div className="mini-caption spaced">ИСТОРИЯ СРАБАТЫВАНИЙ</div>
          <div className="event-list">
            {subNotifications.slice(0, 6).map((note) => (
              <div className="event-row" key={note.id}>
                <span>{shortMoment(note.sent_at)}</span>
                <strong>
                  {MODE_EVENT[note.mode]} — {money(note.price)} ₽
                </strong>
                <small>система</small>
              </div>
            ))}
            {subNotifications.length === 0 ? (
              <p className="empty-note">Срабатываний пока не было.</p>
            ) : null}
          </div>

          <div className="modal-actions end">
            <button
              type="button"
              className="btn ghost"
              onClick={() => downloadCsv(selectedSub, subNotifications)}
            >
              Экспорт CSV
            </button>
            <button type="button" className="btn primary" onClick={() => setStatsOpen(false)}>
              Закрыть
            </button>
          </div>
        </Modal>
      ) : null}

      {deleteId !== null ? (
        <ConfirmDialog
          title="Удалить подписку?"
          lines={[
            "Подписка перестанет отслеживать цену.",
            "История срабатываний останется в базе.",
          ]}
          confirm="Удалить"
          onCancel={() => setDeleteId(null)}
          onConfirm={() => void remove()}
        />
      ) : null}
    </>
  );
}
