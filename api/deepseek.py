"""DeepSeek platform internal API adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config_manager


@dataclass(frozen=True)
class APIError(Exception):
    code: str
    endpoint: str
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.message


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=2,
        read=2,
        backoff_factor=0.5,
        # 429 表示平台已要求降速；立即重试只会延长限流，应交给下一轮定时刷新。
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        # 否则 urllib3 遇到带 Retry-After 的 429 仍会隐式重试。
        respect_retry_after_header=False,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


_SESSION = _build_session()


def _headers() -> dict[str, str]:
    base = config_manager.get("DEEPSEEK_BASE", "https://platform.deepseek.com")
    # 该私有接口会通过浏览器标识做风控；缺少这些兼容头时会返回 HTML 429，而非正常 API 限流。
    # 版本集中保留在适配器中，平台策略变化时只需更新这里。
    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "authorization": config_manager.get("DEEPSEEK_AUTH", ""),
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "x-app-version": "20240425.0",
        "cookie": config_manager.get("DEEPSEEK_COOKIE", ""),
        "referer": f"{base}/usage",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }


def _error_code(status_code: int) -> str:
    if status_code in (401, 403):
        return "AUTH_EXPIRED"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code >= 500:
        return "SERVER_ERROR"
    return "UNKNOWN_ERROR"


def _get(path: str, *, params: dict[str, int] | None = None) -> Any:
    auth = str(config_manager.get("DEEPSEEK_AUTH", "")).strip()
    cookie = str(config_manager.get("DEEPSEEK_COOKIE", "")).strip()
    if not auth and not cookie:
        # 在发起网络请求前区分“未配置”和“凭据失效”，让面板能给出准确设置引导。
        raise APIError(
            "NOT_CONFIGURED", path.rsplit("/", 1)[-1],
            "尚未配置 Token/Cookie，请先打开设置"
        )
    base = config_manager.get("DEEPSEEK_BASE", "https://platform.deepseek.com").rstrip("/")
    endpoint = path.rsplit("/", 1)[-1]
    try:
        response = _SESSION.get(
            f"{base}{path}", headers=_headers(), params=params, timeout=(5, 15)
        )
    except requests.Timeout as exc:
        raise APIError("NETWORK_TIMEOUT", endpoint, "连接 DeepSeek 超时") from exc
    except requests.RequestException as exc:
        raise APIError("NETWORK_ERROR", endpoint, "无法连接 DeepSeek") from exc

    if not response.ok:
        content_type = response.headers.get("Content-Type", "").lower()
        # 平台风控也使用 429，但返回 HTML 且没有 Retry-After，不能误报为普通限流。
        blocked_by_platform = response.status_code == 429 and "json" not in content_type
        code = "PLATFORM_BLOCKED" if blocked_by_platform else _error_code(response.status_code)
        messages = {
            "AUTH_EXPIRED": "凭证已失效，请重新填写 Token/Cookie",
            "RATE_LIMITED": "请求过于频繁，请稍后重试",
            "PLATFORM_BLOCKED": "平台风控拒绝请求，请稍后重试或更新兼容配置",
            "SERVER_ERROR": "DeepSeek 服务暂时异常",
            "UNKNOWN_ERROR": f"DeepSeek 请求失败（HTTP {response.status_code}）",
        }
        raise APIError(code, endpoint, messages[code], response.status_code)

    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and "json" not in content_type:
        raise APIError("INVALID_RESPONSE", endpoint, "DeepSeek 返回了非 JSON 数据")
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise APIError("INVALID_RESPONSE", endpoint, "DeepSeek 返回的数据无法解析") from exc
    try:
        data = payload["data"]
        return data["biz_data"]
    except (KeyError, TypeError) as exc:
        message = payload.get("message") if isinstance(payload, dict) else None
        raise APIError(
            "INVALID_RESPONSE", endpoint, str(message or "DeepSeek 返回结构已变化")
        ) from exc


def get_user_summary() -> dict[str, Any]:
    result = _get("/api/v0/users/get_user_summary")
    if not isinstance(result, dict):
        raise APIError("INVALID_RESPONSE", "get_user_summary", "账户摘要格式异常")
    return result


def get_usage_amount(month: int, year: int) -> dict[str, Any]:
    result = _get("/api/v0/usage/amount", params={"month": month, "year": year})
    if not isinstance(result, dict):
        raise APIError("INVALID_RESPONSE", "amount", "Token 用量格式异常")
    return result


def get_usage_cost(month: int, year: int) -> dict[str, Any]:
    result = _get("/api/v0/usage/cost", params={"month": month, "year": year})
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        raise APIError("INVALID_RESPONSE", "cost", "费用用量格式异常")
    return result
