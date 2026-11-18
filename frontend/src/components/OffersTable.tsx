import type { Offer } from "../types";
import { money } from "../format";

export function OffersTable({ offers, limit = 10 }: { offers: Offer[]; limit?: number }) {
  return (
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
          {offers.slice(0, limit).map((offer, index) => (
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
  );
}
