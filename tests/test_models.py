from app.db.models import Base


def test_all_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "categories",
        "servers",
        "offers",
        "price_snapshots",
        "parse_runs",
        "subscriptions",
        "notifications",
    }


def test_offers_have_price_index() -> None:
    offers = Base.metadata.tables["offers"]
    index_names = {index.name for index in offers.indexes}
    assert "ix_offers_category_server_price" in index_names


def test_snapshot_has_history_index() -> None:
    snapshots = Base.metadata.tables["price_snapshots"]
    index_names = {index.name for index in snapshots.indexes}
    assert "ix_price_snapshots_category_server_time" in index_names
