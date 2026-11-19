import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ConfirmDialog } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { StatTile } from "../components/StatTile";
import { useToast } from "../components/Toast";
import { asDate, moment } from "../format";
import type { Health, Status } from "../types";

const CHANNEL_KEY = "funpay-channels";
const JOURNAL_KEY = "funpay-journal-cleared-at";

const STATUS_LABEL: Record<string, string> = {
  ok: "ok",
  warn: "медленно",
  error: "ошибка",
  running: "идёт",
};

const STATUS_TONE: Record<string, string> = {
  ok: "mint",
  warn: "amber",
  error: "red",
  running: "accent",
};

function loadChannels(): { system: boolean; inApp: boolean } {
  try {
    const raw = window.localStorage.getItem(CHANNEL_KEY);
    if (!raw) {
      return { system: true, inApp: true };
    }
    const parsed = JSON.parse(raw) as { system?: boolean; inApp?: boolean };
    return { system: parsed.system !== false, inApp: parsed.inApp !== false };
  } catch {
    return { system: true, inApp: true };
  }
}

function loadClearedAt(): number {
  try {
    const raw = window.localStorage.getItem(JOURNAL_KEY);
    const value = raw ? Number(raw) : 0;
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

function clock(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = asDate(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function day(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = asDate(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

export function StatusView({ health }: { health: Health | null }) {
  const toast = useToast();
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [channels, setChannels] = useState(loadChannels);
  const [clearedAt, setClearedAt] = useState(loadClearedAt);
  const [now, setNow] = useState(Date.now());

  async function reload(announce = false) {
    try {
      const value = await api.status();
      setStatus(value);
      setError(null);
      if (announce) {
        toast({ title: "Данные обновлены", subtitle: "Состояние ядра обновлено", tone: "accent" });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      if (announce) {
        toast({ title: "Не удалось обновить", subtitle: String(err), tone: "red" });
      }
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(timer);
  }, []);

  async function schedulerAction(action: "pause" | "resume" | "run") {
    setBusy(action);
    try {
      await api.scheduler(action);
      await reload();
      const messages: Record<typeof action, string> = {
        pause: "Планировщик поставлен на паузу",
        resume: "Планировщик возобновлён",
        run: "Прогон запущен",
      };
      toast({
        title: messages[action],
        subtitle: action === "run" ? "Результат появится в журнале" : "Изменение применено",
        tone: action === "pause" ? "amber" : "mint",
      });
    } catch (err) {
      toast({ title: "Действие не выполнено", subtitle: String(err), tone: "red" });
    } finally {
      setBusy(null);
    }
  }

  function toggleChannel(key: "system" | "inApp") {
    const next = { ...channels, [key]: !channels[key] };
    setChannels(next);
    try {
      window.localStorage.setItem(CHANNEL_KEY, JSON.stringify(next));
    } catch {
      // Channel switches are a local preference; ignore storage failures.
    }
    toast({
      title: key === "system" ? "Системные уведомления" : "Уведомления в приложении",
      subtitle: next[key] ? "включены" : "выключены",
      tone: next[key] ? "mint" : "amber",
    });
  }

  function clearJournal() {
    const value = Date.now();
    setClearedAt(value);
    try {
      window.localStorage.setItem(JOURNAL_KEY, String(value));
    } catch {
      // The journal is a local view; ignore storage failures.
    }
    setClearOpen(false);
    toast({ title: "Журнал очищен", subtitle: "История цен и подписки не тронуты", tone: "amber" });
  }

  const runs = status?.parse_runs.slice(0, 6) ?? [];

  const logRows = useMemo(
    () =>
      (status?.parse_runs ?? [])
        .filter((run) => asDate(run.started_at).getTime() > clearedAt)
        .slice(0, 5)
        .map((run) => ({
          id: `${run.category_id}-${run.started_at}`,
          when: clock(run.started_at),
          message:
            run.status === "ok"
              ? `${run.category_title} · прогон завершён: ${run.offers_found} предложений`
              : `${run.category_title} · ${run.error_text ?? "ошибка прогона"}`,
        })),
    [status, clearedAt],
  );

  const schedulerState = status?.scheduler_state ?? "off";
  const schedulerLabel =
    schedulerState === "running"
      ? "выполняется"
      : schedulerState === "paused"
        ? "на паузе"
        : schedulerState === "active"
          ? "активен"
          : "выключен";
  const schedulerTone =
    schedulerState === "running"
      ? "accent"
      : schedulerState === "paused"
        ? "amber"
        : schedulerState === "active"
          ? "mint"
          : "muted";

  const nextAt = status?.next_run_at ? asDate(status.next_run_at).getTime() : null;
  const intervalMs = Math.max(1, (status?.interval_minutes ?? 15) * 60_000);
  const progress =
    schedulerState === "running"
      ? 1
      : nextAt !== null
        ? Math.max(0.04, Math.min(1, 1 - (nextAt - now) / intervalMs))
        : 0;
  const nextLabel =
    schedulerState === "running"
      ? "Следующий прогон · выполняется сейчас"
      : schedulerState === "paused"
        ? "Следующий прогон · не запланирован"
        : schedulerState === "off"
          ? "Планировщик выключен"
          : nextAt !== null
            ? `Следующий прогон · через ${Math.max(1, Math.round((nextAt - now) / 60_000))} мин`
            : "Следующий прогон · —";

  const earliestRun = status?.parse_runs.reduce<string | null>((earliest, run) => {
    if (!earliest) {
      return run.started_at;
    }
    return asDate(run.started_at) < asDate(earliest) ? run.started_at : earliest;
  }, null);

  return (
    <>
      <PageHeader
        title="Состояние"
        subtitle="Локальное ядро, база и последние прогоны парсера"
        action={
          <button
            type="button"
            className="btn primary header-action"
            onClick={() => void reload(true)}
          >
            Обновить
          </button>
        }
      />

      <div className="screen status-screen">
        {error ? <div className="banner error">{error}</div> : null}

        {status ? (
          <>
            <div className="kpi-row">
              <StatTile
                label="КАТЕГОРИИ"
                value={status.categories}
                hint={`активных: ${status.active_categories}`}
                hintTone="muted"
                dotTone="accent"
              />
              <StatTile
                label="ПОДПИСКИ"
                value={status.active_subscriptions}
                hint={`пользователей: ${status.users}`}
                hintTone="muted"
                dotTone="mint"
              />
              <StatTile
                label="ПРЕДЛОЖЕНИЯ"
                value={status.offers.toLocaleString("ru-RU")}
                hint="в локальной базе"
                hintTone="muted"
                dotTone="accent"
              />
              <StatTile
                label="ПРОГОНЫ"
                value={status.parse_runs.length}
                hint="последние записи"
                hintTone="muted"
                dotTone="amber"
              />
            </div>

            <div className="grid-640-328">
              <div className="left-stack">
                <section className="panel runs-panel">
                  <div className="panel-head">
                    <h2>Последние прогоны</h2>
                    <span className="chip static">{status.parse_runs.length} записей</span>
                  </div>

                  <div className="runs-table">
                    <div className="runs-head">
                      <span>КАТЕГОРИЯ</span>
                      <span>СТАТУС</span>
                      <span>НАЧАЛО</span>
                      <span>ЛОТЫ</span>
                    </div>
                    {runs.map((run) => (
                      <div className="runs-row" key={`${run.category_id}-${run.started_at}`}>
                        <span>{run.category_title}</span>
                        <span>
                          <i className={`status-chip tone-${STATUS_TONE[run.status] ?? "muted"}`}>
                            {STATUS_LABEL[run.status] ?? run.status}
                          </i>
                        </span>
                        <span className="muted">{moment(run.started_at)}</span>
                        <span className="muted">{run.offers_found.toLocaleString("ru-RU")}</span>
                      </div>
                    ))}
                    {runs.length === 0 ? (
                      <p className="empty-note">Прогонов пока не было.</p>
                    ) : null}
                  </div>

                  <div className="soft-divider" />
                  <div className="runs-next">{nextLabel}</div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${progress * 100}%` }} />
                  </div>
                </section>

                <section className="panel log-panel">
                  <div className="panel-head">
                    <div className="inline-title">
                      <h2>Журнал</h2>
                      <span className="panel-sub">последние события ядра</span>
                    </div>
                    <button type="button" className="chip" onClick={() => setClearOpen(true)}>
                      Очистить
                    </button>
                  </div>

                  <div className="log-list">
                    {logRows.map((row) => (
                      <div className="log-row" key={row.id}>
                        <span className="log-dot" />
                        <span className="log-when">{row.when}</span>
                        <span className="log-message">{row.message}</span>
                      </div>
                    ))}
                    {logRows.length === 0 ? (
                      <div className="empty-block">
                        <strong>Журнал пуст</strong>
                        <span>События появятся после первого прогона парсера</span>
                      </div>
                    ) : null}
                  </div>
                </section>
              </div>

              <div className="right-stack">
                <section className="panel db-panel">
                  <div className="panel-head">
                    <h2>База данных</h2>
                    <span className="tone-mint status-inline">
                      <i />
                      ok
                    </span>
                  </div>
                  <div className="info-list">
                    <div>
                      <span>Движок</span>
                      <strong>
                        {health?.database === "postgresql" ? "PostgreSQL" : "SQLite 3"}
                      </strong>
                    </div>
                    <div>
                      <span>Файл</span>
                      <strong>
                        {health?.database === "postgresql" ? "—" : "data/monitor.db"}
                      </strong>
                    </div>
                    <div>
                      <span>Размер</span>
                      <strong>—</strong>
                    </div>
                    <div>
                      <span>История</span>
                      <strong>{earliestRun ? `с ${day(earliestRun)}` : "—"}</strong>
                    </div>
                  </div>
                  <div className="soft-divider" />
                  <p className="footnote">
                    {status.offers.toLocaleString("ru-RU")} предложений ·{" "}
                    {status.categories} категорий
                  </p>
                </section>

                <section className="panel sched-panel">
                  <div className="panel-head">
                    <h2>Планировщик</h2>
                    <button
                      type="button"
                      className={schedulerState === "active" || schedulerState === "running" ? "switch on" : "switch"}
                      onClick={() =>
                        void schedulerAction(
                          schedulerState === "paused" ? "resume" : "pause",
                        )
                      }
                      disabled={schedulerState === "off" || busy !== null}
                      aria-label="Пауза планировщика"
                      aria-pressed={schedulerState === "active" || schedulerState === "running"}
                    >
                      <i />
                    </button>
                    <span className={`status-inline tone-${schedulerTone}`}>
                      {schedulerLabel}
                    </span>
                  </div>

                  <div className="info-list">
                    <div>
                      <span>Интервал</span>
                      <strong>{status.interval_minutes} минут</strong>
                    </div>
                    <div>
                      <span>Следующий запуск</span>
                      <strong>
                        {schedulerState === "paused" || schedulerState === "off"
                          ? "—"
                          : nextAt !== null
                            ? clock(new Date(nextAt).toISOString())
                            : "—"}
                      </strong>
                    </div>
                    <div>
                      <span>Последний запуск</span>
                      <strong>{status.last_run_at ? moment(status.last_run_at) : "—"}</strong>
                    </div>
                    <div>
                      <span>Потоков</span>
                      <strong>1</strong>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="chip sched-action"
                    disabled={schedulerState === "off" || schedulerState === "running" || busy !== null}
                    onClick={() =>
                      void schedulerAction(schedulerState === "paused" ? "resume" : "run")
                    }
                  >
                    {schedulerState === "running"
                      ? "Выполняется…"
                      : schedulerState === "paused"
                        ? "Возобновить"
                        : schedulerState === "off"
                          ? "Недоступно"
                          : "Запустить сейчас"}
                  </button>
                </section>

                <section className="panel channels-panel">
                  <div className="panel-head">
                    <h2>Каналы уведомлений</h2>
                  </div>

                  <div className="channel-list">
                    <div className="channel-row">
                      <span>Системные уведомления</span>
                      <small className={channels.system ? "tone-mint" : "tone-dim"}>
                        {channels.system ? "включены" : "выключены"}
                      </small>
                      <button
                        type="button"
                        className={channels.system ? "switch small on" : "switch small"}
                        onClick={() => toggleChannel("system")}
                        aria-pressed={channels.system}
                        aria-label="Системные уведомления"
                      >
                        <i />
                      </button>
                    </div>
                    <div className="channel-row">
                      <span>Внутри приложения</span>
                      <small className={channels.inApp ? "tone-mint" : "tone-dim"}>
                        {channels.inApp ? "включены" : "выключены"}
                      </small>
                      <button
                        type="button"
                        className={channels.inApp ? "switch small on" : "switch small"}
                        onClick={() => toggleChannel("inApp")}
                        aria-pressed={channels.inApp}
                        aria-label="Внутри приложения"
                      >
                        <i />
                      </button>
                    </div>
                    <div className="channel-row disabled">
                      <span>VK-бот</span>
                      <small className="tone-dim">позже</small>
                      <button
                        type="button"
                        className="switch small"
                        disabled
                        aria-label="VK-бот появится позже"
                      >
                        <i />
                      </button>
                    </div>
                  </div>
                </section>
              </div>
            </div>
          </>
        ) : (
          <p className="empty-note">Загружаем…</p>
        )}
      </div>

      {clearOpen ? (
        <ConfirmDialog
          title="Очистить журнал?"
          lines={["Записи журнала будут удалены.", "История цен и подписки останутся."]}
          confirm="Очистить"
          onCancel={() => setClearOpen(false)}
          onConfirm={clearJournal}
        />
      ) : null}
    </>
  );
}
