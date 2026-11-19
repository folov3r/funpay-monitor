import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { LotCardModal } from "../components/LotCard";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { useToast } from "../components/Toast";
import { ago, money } from "../format";
import type { AlertMode, Notification, Offer } from "../types";

type Filter = "all" | "min" | "thr" | "jump";

const MODE_FILTER: Record<AlertMode, Filter> = {
  lowest: "min",
  abs: "thr",
  pct: "jump",
};

const MODE_TITLE: Record<AlertMode, string> = {
  lowest: "Новый минимум",
  abs: "Порог сработал",
  pct: "Скачок цены",
};

const MODE_COLOR: Record<AlertMode, string> = {
  lowest: "var(--teal)",
  abs: "var(--accent)",
  pct: "var(--amber)",
};

const MODE_BODY: Record<AlertMode, (price: string) => string> = {
  lowest: (price) => `${price} — цена обновила минимальное значение по категории`,
  abs: (price) => `${price} — цена опустилась ниже установленного порога`,
  pct: (price) => `${price} — резкое изменение цены за короткий промежуток`,
};

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "min", label: "Минимум" },
  { id: "thr", label: "Порог" },
  { id: "jump", label: "Скачок" },
];

const FILTER_TITLES: Record<Filter, string> = {
  all: "Все уведомления",
  min: "Новый минимум",
  thr: "Порог сработал",
  jump: "Скачок цены",
};

const READ_KEY = "funpay-read-notifications";

function loadRead(): Set<number> {
  try {
    const raw = window.localStorage.getItem(READ_KEY);
    if (!raw) {
      return new Set();
    }
    const values = JSON.parse(raw) as unknown;
    if (!Array.isArray(values)) {
      return new Set();
    }
    return new Set(values.filter((value): value is number => typeof value === "number"));
  } catch {
    return new Set();
  }
}

export function NotificationsView() {
  const toast = useToast();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [read, setRead] = useState<Set<number>>(() => loadRead());
  const [openNote, setOpenNote] = useState<Notification | null>(null);
  const [lotOffer, setLotOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload(announce = false) {
    try {
      const rows = await api.notifications(50);
      setNotifications(rows);
      setError(null);
      if (announce) {
        toast({ title: "Данные обновлены", subtitle: "Лента уведомлений обновлена", tone: "accent" });
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

  const counts = useMemo(() => {
    const result: Record<Filter, number> = { all: notifications.length, min: 0, thr: 0, jump: 0 };
    for (const note of notifications) {
      result[MODE_FILTER[note.mode]] += 1;
    }
    return result;
  }, [notifications]);

  const rows = useMemo(() => {
    let list = notifications;
    if (unreadOnly) {
      list = list.filter((note) => !read.has(note.id));
    }
    if (filter !== "all") {
      list = list.filter((note) => MODE_FILTER[note.mode] === filter);
    }
    return list;
  }, [notifications, unreadOnly, filter, read]);

  function openNotification(note: Notification) {
    setOpenNote(note);
    if (!read.has(note.id)) {
      const next = new Set(read);
      next.add(note.id);
      setRead(next);
      try {
        window.localStorage.setItem(READ_KEY, JSON.stringify(Array.from(next)));
      } catch {
        // Read state is a convenience; ignore storage failures.
      }
    }
  }

  async function openOrder(note: Notification) {
    try {
      const offers = await api.offers(note.category_id, { limit: 1 });
      if (offers.length === 0) {
        toast({ title: "Лот не найден", subtitle: "В категории пока нет предложений", tone: "amber" });
        return;
      }
      setOpenNote(null);
      setLotOffer(offers[0]);
    } catch (err) {
      toast({ title: "Не удалось открыть лот", subtitle: String(err), tone: "red" });
    }
  }

  const subtitle = useMemo(() => {
    if (unreadOnly) {
      return "только непрочитанные";
    }
    if (filter === "all") {
      return "сначала новые";
    }
    return `сначала новые · показано ${counts[filter]}`;
  }, [unreadOnly, filter, counts]);

  return (
    <>
      <PageHeader
        title="Уведомления"
        subtitle={`История срабатываний по всем подпискам · ${notifications.length} записей`}
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

      <div className="screen notifications-screen">
        {error ? <div className="banner error">{error}</div> : null}

        <div className="filter-row">
          <div className="chip-row">
            {FILTERS.map((row) => (
              <button
                key={row.id}
                type="button"
                className={row.id === filter ? "chip active" : "chip"}
                onClick={() => setFilter(row.id)}
              >
                {row.label} · {counts[row.id]}
              </button>
            ))}
          </div>
          <label className="toggle-row">
            <span>Только непрочитанные</span>
            <button
              type="button"
              className={unreadOnly ? "switch on" : "switch"}
              onClick={() => setUnreadOnly((value) => !value)}
              aria-pressed={unreadOnly}
              aria-label="Только непрочитанные"
            >
              <i />
            </button>
          </label>
        </div>

        <section className="panel feed-panel">
          <div className="panel-head">
            <div className="inline-title">
              <h2>{FILTER_TITLES[filter]}</h2>
              <span className="panel-sub">{subtitle}</span>
            </div>
          </div>
          <div className="soft-divider" />

          <div className="feed">
            {rows.map((note) => {
              const unread = !read.has(note.id);
              return (
                <button
                  key={note.id}
                  type="button"
                  className="feed-row"
                  onClick={() => openNotification(note)}
                >
                  <span className="feed-dot" style={{ background: MODE_COLOR[note.mode] }} />
                  <span className="feed-copy">
                    <strong>
                      {MODE_TITLE[note.mode]} · {note.category_title}
                    </strong>
                    <span>{MODE_BODY[note.mode](`${money(note.price)} ₽`)}</span>
                  </span>
                  <span className="feed-side">
                    <span className="feed-when">{ago(note.sent_at)}</span>
                    <span className="channel-chip">система</span>
                  </span>
                  {unread ? <span className="unread-dot" /> : null}
                </button>
              );
            })}
            {rows.length === 0 ? (
              <div className="empty-block">
                <strong>Уведомлений нет</strong>
                <span>Срабатывания появятся после проверки подписок</span>
              </div>
            ) : null}
          </div>
        </section>
      </div>

      {openNote ? (
        <Modal
          caption="УВЕДОМЛЕНИЕ"
          title={`${MODE_TITLE[openNote.mode]} · ${openNote.category_title}`}
          onClose={() => setOpenNote(null)}
          width={620}
          className="note-modal"
        >
          <p className="panel-sub">
            {ago(openNote.sent_at)} назад · канал: система
          </p>
          <p className="note-body">{MODE_BODY[openNote.mode](`${money(openNote.price)} ₽`)}</p>

          <div className="soft-divider" />

          <div className="info-list">
            <div>
              <span>Категория</span>
              <strong>{openNote.category_title}</strong>
            </div>
            <div>
              <span>Сервер</span>
              <strong>Все</strong>
            </div>
            <div>
              <span>Цена на момент события</span>
              <strong>{money(openNote.price)} ₽</strong>
            </div>
          </div>

          <div className="soft-divider" />
          <div className="mini-caption">ЛОТ</div>

          <div className="note-lot">
            <span className="avatar lg">
              {openNote.category_title.trim().charAt(0).toUpperCase() || "?"}
            </span>
            <div className="note-lot-copy">
              <strong>{openNote.category_title}</strong>
              <span>предложение на FunPay</span>
            </div>
            <strong className="note-lot-price">{money(openNote.price)} ₽</strong>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn primary" onClick={() => void openOrder(openNote)}>
              Перейти к заказу
            </button>
            <button type="button" className="btn ghost" onClick={() => setOpenNote(null)}>
              Закрыть
            </button>
          </div>
        </Modal>
      ) : null}

      {lotOffer ? (
        <LotCardModal
          offer={lotOffer}
          categoryTitle={openNote?.category_title ?? lotOffer.title ?? "FunPay"}
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
