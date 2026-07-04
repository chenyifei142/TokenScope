"""Data models and fault-tolerant DeepSeek usage aggregation."""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import api.deepseek as ds
import api.deepseek_official as official
import config_manager
from data import history

TOKEN_TYPES = {
    "PROMPT_CACHE_HIT_TOKEN",
    "PROMPT_CACHE_MISS_TOKEN",
    "RESPONSE_TOKEN",
}
ACTIVITY_DAYS = 365
HISTORY_SYNC_BATCH_SIZE = 2


@dataclass(frozen=True)
class FetchError:
    code: str
    source: str
    message: str


@dataclass
class ModelUsage:
    model: str
    tokens: int = 0
    cost_cny: Decimal = Decimal("0")


def top_model_stats(
    stats: dict[str, ModelUsage], limit: int = 3
) -> list[ModelUsage]:
    models = sorted(stats.values(), key=lambda value: value.tokens, reverse=True)
    if len(models) <= limit:
        return copy.deepcopy(models)
    shown = copy.deepcopy(models[: limit - 1])
    other = ModelUsage("其他")
    for model in models[limit - 1 :]:
        other.tokens += model.tokens
        other.cost_cny += model.cost_cny
    return shown + [other]


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"无效数值：{value!r}") from None


def _safe_int(value: Any) -> int:
    try:
        return int(_decimal(value))
    except ValueError:
        return 0


def sum_usage_amount(item: dict[str, Any], allowed_types: set[str] = TOKEN_TYPES) -> Decimal:
    """汇总一条模型记录；坏字段只跳过当前 usage，避免丢弃整批响应。"""
    total = Decimal("0")
    usages = item.get("usage", [])
    if not isinstance(usages, list):
        config_manager.logger().warning("Skipped usage with invalid list type")
        return total
    for usage in usages:
        if not isinstance(usage, dict) or usage.get("type") not in allowed_types:
            continue
        try:
            total += _decimal(usage.get("amount"))
        except ValueError:
            config_manager.logger().warning("Skipped malformed usage amount")
    return total


def months_for_week(today: date) -> list[tuple[int, int]]:
    week_start = today - timedelta(days=today.weekday())
    months = [(today.month, today.year)]
    if (week_start.year, week_start.month) != (today.year, today.month):
        months.insert(0, (week_start.month, week_start.year))
    return months


def months_for_activity(today: date) -> list[tuple[int, int]]:
    """Return newest-first months intersecting the 365-day activity window."""
    earliest = today - timedelta(days=ACTIVITY_DAYS - 1)
    current = today.replace(day=1)
    first = earliest.replace(day=1)
    months: list[tuple[int, int]] = []
    while current >= first:
        months.append((current.month, current.year))
        current = (current - timedelta(days=1)).replace(day=1)
    return months


def _error_from_exception(source: str, exc: Exception) -> FetchError:
    if isinstance(exc, ds.APIError):
        return FetchError(exc.code, source, exc.message)
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        config_manager.logger().warning("Invalid response in %s: %s", source, exc)
        return FetchError("INVALID_RESPONSE", source, "DeepSeek 返回结构已变化")
    config_manager.logger().exception("Unexpected fetch error in %s", source)
    return FetchError("UNKNOWN_ERROR", source, "读取用量时发生未知错误")


def _validate_days(payload: dict[str, Any]) -> list[dict[str, Any]]:
    days = payload.get("days", [])
    if not isinstance(days, list):
        raise ValueError("days 字段不是列表")
    return days


def _daily_totals(
    payloads: list[dict[str, Any]], today: date
) -> tuple[Decimal, Decimal]:
    today_total = Decimal("0")
    week_total = Decimal("0")
    week_start = today - timedelta(days=today.weekday())
    seen: set[tuple[date, int]] = set()
    for payload in payloads:
        for day_entry in _validate_days(payload):
            if not isinstance(day_entry, dict):
                continue
            try:
                usage_date = date.fromisoformat(str(day_entry.get("date", "")))
            except ValueError:
                config_manager.logger().warning("Skipped usage row with invalid date")
                continue
            items = day_entry.get("data", [])
            if not isinstance(items, list):
                config_manager.logger().warning("Skipped day with invalid data list")
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict) or (usage_date, index) in seen:
                    continue
                seen.add((usage_date, index))
                amount = sum_usage_amount(item)
                if usage_date == today:
                    today_total += amount
                if week_start <= usage_date <= today:
                    week_total += amount
    return today_total, week_total


def _model_totals(payload: dict[str, Any]) -> dict[str, Decimal]:
    rows = payload.get("total", [])
    if not isinstance(rows, list):
        raise ValueError("total 字段不是列表")
    result: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model", "")).strip()
        if not model:
            config_manager.logger().warning("Skipped model row without model id")
            continue
        result[model] = result.get(model, Decimal("0")) + sum_usage_amount(row)
    return result


@dataclass
class TokenData:
    """Aggregated view plus explicit freshness/error state."""

    balance_cny: float = 0.0
    balance_tokens: int = 0
    monthly_usage_tokens: int = 0
    monthly_cost_cny: float = 0.0
    today_tokens: int = 0
    today_cost_cny: float = 0.0
    weekly_tokens: int = 0
    weekly_cost_cny: float = 0.0
    total_cost_cny: float = 0.0
    per_model_amount: list[dict[str, Any]] = field(default_factory=list)
    per_model_cost: list[dict[str, Any]] = field(default_factory=list)
    model_stats: dict[str, ModelUsage] = field(default_factory=dict)
    status: str = "loading"
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    errors: list[FetchError] = field(default_factory=list)
    is_stale: bool = False
    last_updated: str = ""
    official_status: str = "not_configured"
    platform_status: str = "unknown"
    daily_usage: list[dict[str, Any]] = field(default_factory=list)

    _last_snapshot: ClassVar["TokenData | None"] = None
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def _base_snapshot(cls) -> "TokenData":
        with cls._cache_lock:
            return copy.deepcopy(cls._last_snapshot) if cls._last_snapshot else cls()

    @classmethod
    def fetch(cls, today: date | None = None) -> "TokenData":
        current_day = today or date.today()
        data = cls._base_snapshot()
        data.status = "loading"
        data.errors = []
        data.last_attempt_at = datetime.now()
        successes = 0
        platform_requests_stopped = False

        official_balance_loaded = False
        if config_manager.get("DEEPSEEK_API_KEY", "").strip():
            try:
                balance = official.get_balance()
                infos = balance.get("balance_infos", [])
                if not isinstance(infos, list):
                    raise ValueError("balance_infos 字段不是列表")
                for info in infos:
                    if isinstance(info, dict) and info.get("currency") == "CNY":
                        data.balance_cny = float(_decimal(info.get("total_balance")))
                        official_balance_loaded = True
                        break
                data.official_status = "ok"
                successes += 1
            except Exception as exc:
                data.official_status = "error"
                data.errors.append(_error_from_exception("官方余额", exc))

        try:
            summary = ds.get_user_summary()
            wallets = summary.get("normal_wallets", [])
            if not isinstance(wallets, list):
                raise ValueError("normal_wallets 字段不是列表")
            for wallet in wallets:
                if not isinstance(wallet, dict) or wallet.get("currency") != "CNY":
                    continue
                if not official_balance_loaded:
                    data.balance_cny = float(_decimal(wallet.get("balance")))
                data.balance_tokens = _safe_int(wallet.get("token_estimation"))
            monthly_costs = summary.get("monthly_costs", [])
            if isinstance(monthly_costs, list) and monthly_costs:
                first = monthly_costs[0]
                if isinstance(first, dict):
                    data.monthly_cost_cny = float(_decimal(first.get("amount")))
            data.monthly_usage_tokens = _safe_int(summary.get("monthly_token_usage"))
            successes += 1
            data.platform_status = "ok"
        except Exception as exc:
            data.platform_status = "error"
            data.errors.append(_error_from_exception("账户摘要", exc))
            platform_requests_stopped = (
                isinstance(exc, ds.APIError)
                and exc.code in {"RATE_LIMITED", "PLATFORM_BLOCKED"}
            )

        amount_payloads: list[dict[str, Any]] = []
        amount_failed = False
        token_models: dict[str, Decimal] | None = None
        request_months = months_for_week(current_day)
        try:
            backfill_count = 0
            for missing_month in history.unsynced_months(
                months_for_activity(current_day)
            ):
                if missing_month in request_months:
                    continue
                request_months.append(missing_month)
                backfill_count += 1
                if backfill_count >= HISTORY_SYNC_BATCH_SIZE:
                    break
        except Exception:
            config_manager.logger().exception("History sync state read failed")
            data.errors.append(
                FetchError("LOCAL_STORAGE", "历史缓存", "本地历史同步状态读取失败")
            )
        if not platform_requests_stopped:
            for month, year in request_months:
                try:
                    amount_payloads.append(ds.get_usage_amount(month, year))
                    successes += 1
                except Exception as exc:
                    amount_failed = True
                    data.errors.append(_error_from_exception("Token 明细", exc))
                    if isinstance(exc, ds.APIError) and exc.code in {
                        "RATE_LIMITED", "PLATFORM_BLOCKED"
                    }:
                        # 同一轮继续请求只会放大限流或风控；保留已取得的数据并等待下次刷新。
                        platform_requests_stopped = True
                        break
        if amount_payloads and not amount_failed:
            try:
                today_tokens, weekly_tokens = _daily_totals(amount_payloads, current_day)
                data.today_tokens, data.weekly_tokens = int(today_tokens), int(weekly_tokens)
                # 回填月份追加在请求列表末尾，当前模型统计必须仍取本月响应。
                current_index = request_months.index(
                    (current_day.month, current_day.year)
                )
                current_amount = amount_payloads[current_index]
                data.per_model_amount = copy.deepcopy(current_amount.get("total", []))
                token_models = _model_totals(current_amount)
            except Exception as exc:
                data.errors.append(_error_from_exception("Token 解析", exc))

        cost_payloads: list[dict[str, Any]] = []
        cost_failed = False
        cost_models: dict[str, Decimal] | None = None
        if not platform_requests_stopped:
            for month, year in request_months:
                try:
                    cost_payloads.append(ds.get_usage_cost(month, year))
                    successes += 1
                except Exception as exc:
                    cost_failed = True
                    data.errors.append(_error_from_exception("费用明细", exc))
                    if isinstance(exc, ds.APIError) and exc.code in {
                        "RATE_LIMITED", "PLATFORM_BLOCKED"
                    }:
                        platform_requests_stopped = True
                        break
        if cost_payloads and not cost_failed:
            try:
                today_cost, weekly_cost = _daily_totals(cost_payloads, current_day)
                # 费用先用 Decimal 聚合，最后才转成兼容现有 UI 的 float。
                data.today_cost_cny = float(today_cost)
                data.weekly_cost_cny = float(weekly_cost)
                current_index = request_months.index(
                    (current_day.month, current_day.year)
                )
                current_cost = cost_payloads[current_index]
                data.per_model_cost = copy.deepcopy(current_cost.get("total", []))
                cost_models = _model_totals(current_cost)
            except Exception as exc:
                data.errors.append(_error_from_exception("费用解析", exc))

        if token_models is not None and cost_models is not None:
            # 两类模型明细都成功时才整体替换，既移除已下线模型，也避免部分失败清空缓存。
            data.model_stats = {
                model: ModelUsage(
                    model,
                    int(token_models.get(model, Decimal("0"))),
                    cost_models.get(model, Decimal("0")),
                )
                for model in token_models.keys() | cost_models.keys()
            }

        platform_calls_succeeded = bool(amount_payloads or cost_payloads)
        if amount_failed or cost_failed:
            data.platform_status = "partial" if platform_calls_succeeded else "error"
        elif data.platform_status != "error":
            data.platform_status = "ok"

        if amount_payloads and cost_payloads and not amount_failed and not cost_failed:
            try:
                # 当前月仍在增长，不能标记为完整历史；跨月后需再补拉一次最终账单。
                current_month = (current_day.month, current_day.year)
                completed_months = [
                    month for month in request_months if month != current_month
                ]
                history.save_usage(
                    amount_payloads,
                    cost_payloads,
                    synced_months=completed_months,
                )
            except Exception as exc:
                config_manager.logger().exception("History save failed")
                data.errors.append(FetchError("LOCAL_STORAGE", "历史缓存", "本地历史数据保存失败"))

        try:
            # 图表只消费本地规范化日数据，避免 UI 重新理解不稳定的上游响应结构。
            # UI 只读取年度窗口；历史总金额则独立汇总全部本地账单。
            data.daily_usage = history.recent_daily(371)
            data.total_cost_cny = float(history.total_cost())
        except Exception:
            config_manager.logger().exception("History read failed")
            data.errors.append(FetchError("LOCAL_STORAGE", "历史缓存", "本地历史数据读取失败"))

        if successes:
            data.last_success_at = datetime.now()
            data.last_updated = data.last_success_at.strftime("%H:%M:%S")
            data.status = "partial" if data.errors else "ok"
            data.is_stale = bool(data.errors)
            with cls._cache_lock:
                cls._last_snapshot = copy.deepcopy(data)
        else:
            data.status = "error"
            data.is_stale = data.last_success_at is not None
        for error in data.errors:
            config_manager.logger().warning(
                "Fetch failed: source=%s code=%s message=%s",
                error.source, error.code, error.message,
            )
        return data

    @property
    def display_message(self) -> str:
        if self.status == "loading":
            return "正在刷新…"
        if self.errors:
            suffix = f"，显示 {self.last_updated} 的缓存" if self.is_stale and self.last_updated else ""
            return f"{self.errors[0].message}{suffix}"
        return f"更新于 {self.last_updated}" if self.last_updated else "等待首次刷新"
