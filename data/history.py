"""Small sqlite cache for normalized daily usage history."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import config_manager

DB_PATH = config_manager.CONFIG_DIR / "usage.db"


@contextmanager
def _connect():
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
        CREATE TABLE IF NOT EXISTS daily_usage (
            usage_date TEXT NOT NULL,
            model TEXT NOT NULL,
            token_type TEXT NOT NULL,
            token_amount INTEGER NOT NULL DEFAULT 0,
            cost_cny TEXT NOT NULL DEFAULT '0',
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (usage_date, model, token_type)
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            provider TEXT PRIMARY KEY,
            last_success_at TEXT,
            last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS monthly_sync (
            provider TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            last_success_at TEXT NOT NULL,
            PRIMARY KEY (provider, year, month)
        );
            """
        )
        with connection:
            yield connection
    finally:
        # sqlite Connection 的 with 只提交事务，不会自动关闭文件句柄。
        connection.close()


def needs_initial_sync(provider: str = "deepseek") -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT last_success_at FROM sync_state WHERE provider = ?", (provider,)
        ).fetchone()
    return not row or not row[0]


def unsynced_months(
    months: list[tuple[int, int]], provider: str = "deepseek"
) -> list[tuple[int, int]]:
    """Return requested ``(month, year)`` pairs without a completed local sync."""
    if not months:
        return []
    with _connect() as connection:
        rows = connection.execute(
            "SELECT month, year FROM monthly_sync WHERE provider = ?", (provider,)
        ).fetchall()
    synced = {(int(month), int(year)) for month, year in rows}
    return [item for item in months if item not in synced]


def _rows(payloads: list[dict[str, Any]]):
    for payload in payloads:
        days = payload.get("days", [])
        if not isinstance(days, list):
            continue
        for day in days:
            if not isinstance(day, dict):
                continue
            usage_date = str(day.get("date", ""))
            try:
                date.fromisoformat(usage_date)
            except ValueError:
                continue
            items = day.get("data", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                model = str(item.get("model", "unknown")).strip() or "unknown"
                usages = item.get("usage", [])
                if not isinstance(usages, list):
                    continue
                for usage in usages:
                    if not isinstance(usage, dict):
                        continue
                    token_type = str(usage.get("type", "")).strip()
                    try:
                        amount = Decimal(str(usage.get("amount", "0")))
                    except (InvalidOperation, ValueError):
                        continue
                    if token_type:
                        yield usage_date, model, token_type, amount


def _aggregated_rows(payloads: list[dict[str, Any]]):
    totals: dict[tuple[str, str, str], Decimal] = {}
    for usage_date, model, token_type, amount in _rows(payloads):
        key = (usage_date, model, token_type)
        totals[key] = totals.get(key, Decimal("0")) + amount
    for (usage_date, model, token_type), amount in totals.items():
        yield usage_date, model, token_type, amount


def save_usage(
    amount_payloads: list[dict[str, Any]],
    cost_payloads: list[dict[str, Any]],
    synced_months: list[tuple[int, int]] | None = None,
    provider: str = "deepseek",
) -> None:
    fetched_at = datetime.now().isoformat(timespec="seconds")
    with _connect() as connection:
        for usage_date, model, token_type, amount in _aggregated_rows(amount_payloads):
            connection.execute(
                """INSERT INTO daily_usage
                   (usage_date, model, token_type, token_amount, fetched_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(usage_date, model, token_type) DO UPDATE SET
                     token_amount = excluded.token_amount,
                     fetched_at = excluded.fetched_at""",
                (usage_date, model, token_type, int(amount), fetched_at),
            )
        for usage_date, model, token_type, amount in _aggregated_rows(cost_payloads):
            connection.execute(
                """INSERT INTO daily_usage
                   (usage_date, model, token_type, cost_cny, fetched_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(usage_date, model, token_type) DO UPDATE SET
                     cost_cny = excluded.cost_cny,
                     fetched_at = excluded.fetched_at""",
                (usage_date, model, token_type, str(amount), fetched_at),
            )
        # 历史总金额依赖完整的本地账单；按日明细体量很小，因此不再按 400 天清理。
        connection.execute(
            """INSERT INTO sync_state(provider, last_success_at, last_error)
               VALUES ('deepseek', ?, NULL)
               ON CONFLICT(provider) DO UPDATE SET
                 last_success_at = excluded.last_success_at, last_error = NULL""",
            (fetched_at,),
        )
        for month, year in dict.fromkeys(synced_months or []):
            # 即使月份没有用量也要记录成功状态，避免定时刷新反复请求空月份。
            connection.execute(
                """INSERT INTO monthly_sync(provider, year, month, last_success_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(provider, year, month) DO UPDATE SET
                     last_success_at = excluded.last_success_at""",
                (provider, year, month, fetched_at),
            )


def total_cost() -> Decimal:
    """Return the cumulative cost represented by all locally cached bills."""
    with _connect() as connection:
        rows = connection.execute("SELECT cost_cny FROM daily_usage").fetchall()
    total = Decimal("0")
    for (cost,) in rows:
        try:
            total += Decimal(str(cost or "0"))
        except (InvalidOperation, ValueError):
            # 单条损坏记录不应让整个统计面板失效；后续同步会覆盖该记录。
            config_manager.logger().warning("Skipped malformed cached cost")
    return total


def recent_daily(days: int = 371) -> list[dict[str, Any]]:
    start = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            """SELECT usage_date, token_amount, cost_cny
               FROM daily_usage WHERE usage_date >= ? ORDER BY usage_date""",
            (start,),
        ).fetchall()
    daily: dict[str, dict[str, Any]] = {}
    for usage_date, tokens, cost in rows:
        item = daily.setdefault(
            usage_date, {"date": usage_date, "tokens": 0, "cost_cny": Decimal("0")}
        )
        item["tokens"] += int(tokens or 0)
        item["cost_cny"] += Decimal(cost)
    return list(daily.values())
