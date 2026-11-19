"""HTTP routes consumed by the desktop window and the local web UI."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apscheduler.schedulers.base import STATE_PAUSED
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_alerts,
    get_local_user_vk_id,
    get_monitoring,
    get_session,
)
from app.api.schemas import (
    CategoryOut,
    HealthOut,
    HistoryPointOut,
    ImportRequest,
    ImportResultOut,
    NotificationOut,
    OfferOut,
    ParseRunOut,
    PriceSummaryOut,
    ReparseOut,
    StatusOut,
    SubscriptionIn,
    SubscriptionOut,
    SubscriptionStatsOut,
    SubscriptionUpdate,
)
from app.db.repositories import (
    PARSE_RUN_OK,
    cheapest_offers,
    current_price_summary,
    deactivate_subscription,
    get_admin_stats,
    get_category,
    get_or_create_user,
    get_user_subscription,
    list_aggregated_snapshots,
    list_categories,
    list_notifications,
    list_price_snapshots,
    list_recent_parse_runs,
    list_user_subscriptions,
    set_subscription_active,
    upsert_subscription,
)
from app.parsers.funpay import normalize_category_path
from app.services.alerts import AlertService
from app.services.monitoring import MonitoringService

router = APIRouter(prefix="/api")


def _subscription_out(subscription: object) -> SubscriptionOut:
    server = subscription.server  # type: ignore[attr-defined]
    return SubscriptionOut(
        id=subscription.id,  # type: ignore[attr-defined]
        category_id=subscription.category_id,  # type: ignore[attr-defined]
        category_title=subscription.category.title,  # type: ignore[attr-defined]
        category_path=subscription.category.url_path,  # type: ignore[attr-defined]
        server_id=subscription.server_id,  # type: ignore[attr-defined]
        server_name=server.name if server is not None else None,
        item_type=subscription.item_type,  # type: ignore[attr-defined]
        query=subscription.query,  # type: ignore[attr-defined]
        mode=subscription.mode,  # type: ignore[attr-defined]
        threshold=subscription.threshold,  # type: ignore[attr-defined]
        is_active=subscription.is_active,  # type: ignore[attr-defined]
        created_at=subscription.created_at,  # type: ignore[attr-defined]
    )


def _summary_out(summary: object) -> PriceSummaryOut | None:
    if summary is None:
        return None
    return PriceSummaryOut(
        min_price=summary.min_price,  # type: ignore[attr-defined]
        median_price=summary.median_price,  # type: ignore[attr-defined]
        offer_count=summary.offer_count,  # type: ignore[attr-defined]
    )


def _validate_threshold(mode: str, threshold: Decimal | None) -> Decimal | None:
    if mode == "lowest":
        return None
    if threshold is None:
        raise HTTPException(status_code=422, detail="threshold is required for this mode")
    if threshold <= 0:
        raise HTTPException(status_code=422, detail="threshold must be positive")
    if mode == "pct" and threshold > 100:
        raise HTTPException(status_code=422, detail="percent threshold cannot exceed 100")
    return threshold


@router.get("/health", response_model=HealthOut)
async def health(request: Request) -> HealthOut:
    app = request.app
    return HealthOut(
        status="ok",
        version=app.state.version,
        database=app.state.database_backend,
        scheduler=app.state.scheduler is not None,
    )


@router.get("/status", response_model=StatusOut)
async def status(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StatusOut:
    stats = await get_admin_stats(session)
    runs = await list_recent_parse_runs(session, limit=10)
    scheduler = getattr(request.app.state, "scheduler", None)
    runtime = getattr(request.app.state, "runtime", None) or {}
    settings = request.app.state.settings
    if scheduler is None:
        scheduler_state = "off"
    elif runtime.get("running"):
        scheduler_state = "running"
    elif scheduler.state == STATE_PAUSED:
        scheduler_state = "paused"
    else:
        scheduler_state = "active"
    next_run_at = None
    if scheduler is not None:
        job = scheduler.get_job("parse-all-categories")
        if job is not None:
            next_run_at = job.next_run_time
    return StatusOut(
        categories=stats.categories,
        active_categories=stats.active_categories,
        users=stats.users,
        active_subscriptions=stats.active_subscriptions,
        offers=stats.offers,
        parse_runs=[
            ParseRunOut(
                category_id=run.category_id,
                category_title=run.category_title,
                category_path=run.category_path,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                offers_found=run.offers_found,
                error_text=run.error_text,
            )
            for run in runs
        ],
        scheduler_state=scheduler_state,
        next_run_at=next_run_at,
        last_run_at=runtime.get("last_run_at"),
        interval_minutes=settings.parse_interval_minutes,
    )


@router.post("/scheduler/{action}")
async def scheduler_action(action: str, request: Request) -> dict[str, str]:
    """Pause, resume or trigger the background parse job from the status screen."""
    if action not in {"pause", "resume", "run"}:
        raise HTTPException(status_code=404, detail="unknown scheduler action")
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=409, detail="scheduler is disabled")
    runtime = getattr(request.app.state, "runtime", None)
    if action == "pause":
        scheduler.pause()
        return {"state": "paused"}
    if action == "resume":
        scheduler.resume()
        return {"state": "active"}
    if runtime is not None and runtime.get("running"):
        raise HTTPException(status_code=409, detail="parse run already in progress")
    job = getattr(request.app.state, "parse_job", None)
    if job is None:
        raise HTTPException(status_code=409, detail="parse job is not available")
    asyncio.create_task(job())
    return {"state": "running"}


@router.get("/categories", response_model=list[CategoryOut])
async def categories(session: AsyncSession = Depends(get_session)) -> list[CategoryOut]:
    rows = await list_categories(session)
    return [CategoryOut.model_validate(row) for row in rows]


@router.get("/categories/{category_id}", response_model=CategoryOut)
async def category_detail(
    category_id: int,
    session: AsyncSession = Depends(get_session),
) -> CategoryOut:
    row = await get_category(session, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="category not found")
    return CategoryOut.model_validate(row)


@router.post("/categories/import", response_model=ImportResultOut)
async def import_category(
    payload: ImportRequest,
    session: AsyncSession = Depends(get_session),
    monitoring: MonitoringService = Depends(get_monitoring),
) -> ImportResultOut:
    try:
        url_path = normalize_category_path(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        imported = await monitoring.import_category(url_path)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"could not parse FunPay: {exc}") from exc

    row = await get_category(session, imported.category_id)
    if row is None:
        raise HTTPException(status_code=500, detail="category disappeared after import")
    summary = await current_price_summary(session, imported.category_id)
    return ImportResultOut(
        category=CategoryOut.model_validate(row),
        item_types=list(imported.item_types),
        offers_found=imported.offers_found,
        snapshots_created=imported.snapshots_created,
        summary=_summary_out(summary),
    )


@router.get("/categories/{category_id}/summary", response_model=PriceSummaryOut | None)
async def category_summary(
    category_id: int,
    server_id: int | None = None,
    item_type: str | None = None,
    query: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PriceSummaryOut | None:
    summary = await current_price_summary(
        session,
        category_id,
        server_id,
        item_type=item_type,
        query=query,
    )
    return _summary_out(summary)


@router.get("/categories/{category_id}/offers", response_model=list[OfferOut])
async def category_offers(
    category_id: int,
    server_id: int | None = None,
    item_type: str | None = None,
    query: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[OfferOut]:
    rows = await cheapest_offers(
        session,
        category_id,
        server_id=server_id,
        item_type=item_type,
        query=query,
        limit=limit,
    )
    return [OfferOut.model_validate(row) for row in rows]


@router.get("/categories/{category_id}/history", response_model=list[HistoryPointOut])
async def category_history(
    category_id: int,
    server_id: int | None = None,
    item_type: str | None = None,
    query: str | None = None,
    days: int = Query(default=7, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> list[HistoryPointOut]:
    since = datetime.now(UTC) - timedelta(days=days)
    if server_id is None:
        aggregates = await list_aggregated_snapshots(
            session,
            category_id,
            item_type=item_type,
            query=query,
            since=since,
        )
        return [
            HistoryPointOut(
                captured_at=point.captured_at,
                min_price=point.min_price,
                median_price=point.median_price,
                offer_count=point.offer_count,
            )
            for point in aggregates
        ]

    snapshots = await list_price_snapshots(
        session,
        category_id,
        server_id=server_id,
        item_type=item_type,
        query=query,
        since=since,
    )
    return [
        HistoryPointOut(
            captured_at=row.captured_at,
            min_price=row.min_price,
            median_price=row.median_price,
            offer_count=row.offer_count,
        )
        for row in snapshots
    ]


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def subscriptions(
    session: AsyncSession = Depends(get_session),
    local_user_vk_id: int = Depends(get_local_user_vk_id),
) -> list[SubscriptionOut]:
    user = await get_or_create_user(session, local_user_vk_id, "Локальный пользователь")
    await session.commit()
    rows = await list_user_subscriptions(session, user.id, include_inactive=True)
    return [_subscription_out(row) for row in rows]


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    payload: SubscriptionIn,
    session: AsyncSession = Depends(get_session),
    local_user_vk_id: int = Depends(get_local_user_vk_id),
) -> SubscriptionOut:
    category = await get_category(session, payload.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="category not found")
    if payload.server_id is not None and all(
        server.id != payload.server_id for server in category.servers
    ):
        raise HTTPException(status_code=422, detail="server does not belong to the category")

    threshold = _validate_threshold(payload.mode, payload.threshold)
    user = await get_or_create_user(session, local_user_vk_id, "Локальный пользователь")
    subscription = await upsert_subscription(
        session,
        user_id=user.id,
        category_id=payload.category_id,
        server_id=payload.server_id,
        mode=payload.mode,
        threshold=threshold,
        item_type=payload.item_type.strip().lower() if payload.item_type else None,
        query=payload.query.strip() if payload.query else None,
    )
    await session.commit()
    loaded = await get_user_subscription(session, subscription.id, user.id)
    if loaded is None:
        raise HTTPException(status_code=500, detail="subscription disappeared after save")
    return _subscription_out(loaded)


@router.patch("/subscriptions/{subscription_id}", response_model=SubscriptionOut)
async def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    session: AsyncSession = Depends(get_session),
    local_user_vk_id: int = Depends(get_local_user_vk_id),
) -> SubscriptionOut:
    """Pause or resume a rule without removing it from the list."""
    user = await get_or_create_user(session, local_user_vk_id, "Локальный пользователь")
    subscription = await set_subscription_active(
        session,
        subscription_id,
        user.id,
        payload.is_active,
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    await session.commit()
    return _subscription_out(subscription)


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: int,
    session: AsyncSession = Depends(get_session),
    local_user_vk_id: int = Depends(get_local_user_vk_id),
) -> None:
    user = await get_or_create_user(session, local_user_vk_id, "Локальный пользователь")
    subscription = await deactivate_subscription(session, subscription_id, user.id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    await session.commit()


@router.get("/subscriptions/{subscription_id}/stats", response_model=SubscriptionStatsOut)
async def subscription_stats(
    subscription_id: int,
    days: int = Query(default=7, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    local_user_vk_id: int = Depends(get_local_user_vk_id),
) -> SubscriptionStatsOut:
    user = await get_or_create_user(session, local_user_vk_id, "Локальный пользователь")
    subscription = await get_user_subscription(session, subscription_id, user.id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="subscription not found")

    summary = await current_price_summary(
        session,
        subscription.category_id,
        subscription.server_id,
        item_type=subscription.item_type,
        query=subscription.query,
    )
    offers = await cheapest_offers(
        session,
        subscription.category_id,
        server_id=subscription.server_id,
        item_type=subscription.item_type,
        query=subscription.query,
        limit=3,
    )
    since = datetime.now(UTC) - timedelta(days=days)
    if subscription.server_id is None:
        aggregates = await list_aggregated_snapshots(
            session,
            subscription.category_id,
            item_type=subscription.item_type,
            query=subscription.query,
            since=since,
        )
        history = [
            HistoryPointOut(
                captured_at=point.captured_at,
                min_price=point.min_price,
                median_price=point.median_price,
                offer_count=point.offer_count,
            )
            for point in aggregates
        ]
    else:
        snapshots = await list_price_snapshots(
            session,
            subscription.category_id,
            server_id=subscription.server_id,
            item_type=subscription.item_type,
            query=subscription.query,
            since=since,
        )
        history = [
            HistoryPointOut(
                captured_at=row.captured_at,
                min_price=row.min_price,
                median_price=row.median_price,
                offer_count=row.offer_count,
            )
            for row in snapshots
        ]

    return SubscriptionStatsOut(
        subscription=_subscription_out(subscription),
        summary=_summary_out(summary),
        history=history,
        cheapest=[OfferOut.model_validate(row) for row in offers],
    )


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationOut]:
    rows = await list_notifications(session, limit=limit)
    return [
        NotificationOut(
            id=row.id,
            subscription_id=row.subscription_id,
            category_id=row.subscription.category_id,
            category_title=row.subscription.category.title,
            mode=row.reason,
            price=row.price,
            sent_at=row.sent_at,
        )
        for row in rows
    ]


@router.post("/categories/{category_id}/reparse", response_model=ReparseOut)
async def reparse_category(
    category_id: int,
    monitoring: MonitoringService = Depends(get_monitoring),
    alerts: AlertService = Depends(get_alerts),
) -> ReparseOut:
    outcome = await monitoring.run_category_by_id(category_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="category not found")

    sent = 0
    if outcome.status == PARSE_RUN_OK:
        sent = len(await alerts.process_category(category_id))

    return ReparseOut(
        category_id=outcome.category_id,
        title=outcome.title,
        status=outcome.status,
        offers_found=outcome.offers_found,
        snapshots_created=outcome.snapshots_created,
        alerts_sent=sent,
        error_text=outcome.error_text,
    )
