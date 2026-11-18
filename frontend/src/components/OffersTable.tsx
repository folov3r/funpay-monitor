import type { Offer } from "../types";
import { ago, money } from "../format";

export function OffersTable({ offers, limit = 10 }: { offers: Offer[]; limit?: number }) {
  return (
    <div className="table-wrap">
      <table className="fixed">
        <colgroup>
          <col style={{ width: "43.4%" }} />
          <col style={{ width: "18.9%" }} />
          <col style={{ width: "22.6%" }} />
          <col style={{ width: "15.1%" }} />
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
          {offers.slice(0, limit).map((offer, index) => (
            <tr key={offer.id} className={index === 0 ? "cheapest" : undefined}>
              <td>
                <span className="seller">{offer.seller_name ?? "—"}</span>
              </td>
              <td className="price">{money(offer.price)} ₽</td>
              <td>{offer.amount ? money(offer.amount) : "—"}</td>
              <td className="muted">{ago(offer.parsed_at)}</td>
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
  );
}
