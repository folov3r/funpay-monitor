"""Run the FunPay parser once and print a short summary (manual smoke test)."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from app.parsers.funpay import FunPayParser


def _format_money(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


async def run(url: str) -> None:
    parser = FunPayParser()
    try:
        parsed = await parser.fetch_category(url)
    finally:
        await parser.aclose()

    category = parsed.category
    print(f"{category.title} ({category.type} #{category.funpay_id})")
    print(f"URL: {category.url_path}")
    print(f"Offers: {len(parsed.offers)}")
    print(f"Min price: {_format_money(parsed.min_price)} RUB")
    print(f"Median price: {_format_money(parsed.median_price)} RUB")

    servers = {offer.server_name for offer in parsed.offers}
    print(f"Servers: {', '.join(sorted(servers)) or '—'}")

    print("\nCheapest offers:")
    for offer in sorted(parsed.offers, key=lambda item: item.price)[:10]:
        amount = f"{offer.amount:g}" if offer.amount is not None else "—"
        online = "online" if offer.is_online else "offline"
        promo = ", promo" if offer.is_promo else ""
        print(
            f"  {offer.price:>10.2f} {offer.currency} | amount {amount:>15} | "
            f"{offer.server_name:<24} | {offer.seller_name or '—'} ({online}{promo})"
        )


def main() -> None:
    arg_parser = argparse.ArgumentParser(description="Parse a FunPay category page once")
    arg_parser.add_argument(
        "url",
        nargs="?",
        default="/chips/30/",
        help="category URL or path, e.g. /chips/30/ or https://funpay.com/lots/13/",
    )
    args = arg_parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
