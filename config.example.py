"""TokenSpider 配置模板 — 复制为 config.py 后填入实际凭证。"""

# DeepSeek API credentials
DEEPSEEK_API_KEY = ""  # 可选：官方 API Key，用于稳定的余额接口
DEEPSEEK_AUTH = ""  # 填入你的 Bearer token
DEEPSEEK_COOKIE = ""  # 填入你的 Cookie 字符串

# API base URL
DEEPSEEK_BASE = "https://platform.deepseek.com"

# Refresh interval in milliseconds
REFRESH_INTERVAL = 60_000  # 60 seconds

# Widget appearance
WIDGET_COMPACT_SIZE = 96
WIDGET_EXPANDED_SIZE = (820, 564)
BG_COLOR = "#071427"
ACCENT_COLOR = "#2f6fe4"
TEXT_COLOR = "#edf4ff"
