import type { Offer } from "../types";
import { ago, money } from "../format";
import { Modal } from "./Modal";

function initial(value: string): string {
  return value.trim().charAt(0).toUpperCase() || "?";
}

export function LotCardModal({
  offer,
  categoryTitle,
  onClose,
  onOpen,
}: {
  offer: Offer;
  categoryTitle: string;
  onClose: () => void;
  onOpen: () => void;
}) {
  const seller = offer.seller_name ?? "Продавец";
  return (
    <Modal caption="ЛОТ" title={`Лот · ${categoryTitle}`} onClose={onClose} width={560}>
      <div className="lot-seller">
        <span className="avatar lg">{initial(seller)}</span>
        <div className="lot-seller-copy">
          <strong>{seller}</strong>
          <span className={offer.is_online ? "online" : "offline"}>
            <i />
            {offer.is_online ? "онлайн" : "офлайн"}
          </span>
        </div>
      </div>

      <div className="lot-price">
        <strong>{money(offer.price)} ₽</strong>
        <span>за 1 шт</span>
      </div>

      <div className="soft-divider" />

      <div className="info-list">
        <div>
          <span>Количество</span>
          <strong>{offer.amount ? `${money(offer.amount)} шт` : "—"}</strong>
        </div>
        <div>
          <span>Обновлено</span>
          <strong>{ago(offer.parsed_at)} назад</strong>
        </div>
        <div>
          <span>Категория</span>
          <strong>{categoryTitle}</strong>
        </div>
        <div>
          <span>Ссылка</span>
          <strong>funpay.com/lots/offer</strong>
        </div>
      </div>

      <div className="modal-actions end">
        <button type="button" className="btn ghost" onClick={onClose}>
          Закрыть
        </button>
        <button type="button" className="btn primary" onClick={onOpen}>
          Открыть на FunPay
        </button>
      </div>
    </Modal>
  );
}
