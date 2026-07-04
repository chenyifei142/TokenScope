"""Pure window geometry helpers plus Windows monitor work-area lookup."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from ctypes import wintypes


@dataclass(frozen=True)
class WorkArea:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    user32 = ctypes.WinDLL("user32.dll")
    try:
        # Per-monitor V2 keeps Tk coordinates aligned with Win32 work areas on mixed-DPI screens.
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def monitor_work_area(x: int, y: int, fallback_width: int, fallback_height: int) -> WorkArea:
    if os.name != "nt":
        return WorkArea(0, 0, fallback_width, fallback_height)
    user32 = ctypes.WinDLL("user32.dll")
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    point = wintypes.POINT(x, y)
    monitor = user32.MonitorFromPoint(point, 2)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return WorkArea(0, 0, fallback_width, fallback_height)
    work = info.rcWork
    return WorkArea(work.left, work.top, work.right, work.bottom)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum)) if maximum >= minimum else minimum


def expanded_geometry(
    compact: tuple[int, int, int, int],
    panel_size: tuple[int, int],
    work: WorkArea,
    margin: int = 8,
    gap: int = 16,
) -> tuple[int, int, int, int, str, str]:
    x, y, compact_width, compact_height = compact
    # 展开后悬浮球仍属于同一透明窗口，因此总宽度需要同时预留球和间距。
    panel_width = min(
        panel_size[0], max(1, work.width - compact_width - gap - margin * 2)
    )
    height = min(panel_size[1], max(1, work.height - margin * 2))
    width = compact_width + gap + panel_width

    if x + compact_width / 2 <= work.left + work.width / 2:
        window_x, horizontal = x, "right"
    else:
        window_x, horizontal = x + compact_width - width, "left"
    if work.bottom - y >= height + margin:
        window_y, vertical = y, "down"
    else:
        window_y, vertical = y + compact_height - height, "up"

    window_x = _clamp(window_x, work.left + margin, work.right - width - margin)
    window_y = _clamp(window_y, work.top + margin, work.bottom - height - margin)
    return window_x, window_y, width, height, horizontal, vertical


def expanded_panel_geometry(
    compact: tuple[int, int, int, int],
    panel_size: tuple[int, int],
    work: WorkArea,
    margin: int = 8,
) -> tuple[int, int, int, int, str, str]:
    """Expand from the ball anchor while replacing, rather than retaining, the ball."""
    x, y, compact_width, compact_height = compact
    width = min(panel_size[0], max(1, work.width - margin * 2))
    height = min(panel_size[1], max(1, work.height - margin * 2))

    if x + compact_width / 2 <= work.left + work.width / 2:
        window_x, horizontal = x, "right"
    else:
        window_x, horizontal = x + compact_width - width, "left"
    if work.bottom - y >= height + margin:
        window_y, vertical = y, "down"
    else:
        window_y, vertical = y + compact_height - height, "up"

    window_x = _clamp(window_x, work.left + margin, work.right - width - margin)
    window_y = _clamp(window_y, work.top + margin, work.bottom - height - margin)
    return window_x, window_y, width, height, horizontal, vertical


def compact_geometry(
    panel: tuple[int, int, int, int],
    compact_size: int,
    horizontal: str,
    vertical: str,
    work: WorkArea,
    margin: int = 8,
) -> tuple[int, int]:
    x, y, width, height = panel
    compact_x = x if horizontal == "right" else x + width - compact_size
    compact_y = y if vertical == "down" else y + height - compact_size
    # 收起时保留原锚点，不再把悬浮球强制吸附到左右边缘。
    return clamp_window(
        compact_x, compact_y, compact_size, compact_size, work, margin
    )


def snap_compact(
    x: int, y: int, size: int, work: WorkArea, margin: int = 8
) -> tuple[int, int]:
    """吸附到当前显示器最近的水平边缘，并避开任务栏工作区。"""
    left = work.left + margin
    right = work.right - size - margin
    target_x = left if abs(x - left) <= abs(x - right) else right
    return target_x, _clamp(y, work.top + margin, work.bottom - size - margin)


def clamp_window(
    x: int, y: int, width: int, height: int, work: WorkArea, margin: int = 8
) -> tuple[int, int]:
    return (
        _clamp(x, work.left + margin, work.right - width - margin),
        _clamp(y, work.top + margin, work.bottom - height - margin),
    )
