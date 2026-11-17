"""Database column types shared by PostgreSQL and SQLite.

The desktop build uses SQLite, which has no native fixed-point numbers and no
timezone-aware timestamps. Money is stored as integer micro-units (or
hundredths for quantities) and timestamps as naive UTC, while PostgreSQL keeps
its native ``numeric`` and ``timestamptz`` types. The Python-facing API stays
the same: ``Decimal`` and timezone-aware ``datetime``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps in UTC and always return timezone-aware values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class _ScaledDecimal(TypeDecorator[Decimal]):
    """Store a Decimal as an integer scaled by ``scale`` digits."""

    impl = BigInteger
    cache_ok = True
    scale = 6

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._quantum = Decimal(1).scaleb(-self.scale)
        self._factor = 10**self.scale

    def process_bind_param(
        self, value: Decimal | int | float | str | None, dialect: object
    ) -> int | None:
        if value is None:
            return None
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        return int(decimal.quantize(self._quantum, rounding=ROUND_HALF_UP) * self._factor)

    def process_result_value(
        self, value: int | float | str | None, dialect: object
    ) -> Decimal | None:
        if value is None:
            return None
        return (Decimal(str(value)) / self._factor).quantize(self._quantum)


class SqliteMoney(_ScaledDecimal):
    """Money with six decimal places, stored as integer micro-units."""

    scale = 6


class SqliteAmount(_ScaledDecimal):
    """Quantities with two decimal places, stored as integer hundredths."""

    scale = 2


#: ``numeric(18,6)`` on PostgreSQL, integer micro-units on SQLite.
Money = Numeric(18, 6).with_variant(SqliteMoney(), "sqlite")
#: ``numeric(18,2)`` on PostgreSQL, integer hundredths on SQLite.
Amount = Numeric(18, 2).with_variant(SqliteAmount(), "sqlite")
#: Auto-incrementing primary key that works on both databases.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
