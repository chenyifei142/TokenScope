import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.activity import activity_levels, calendar_position, compact_tokens, normalize_activity
from ui.qt_heatmap import ActivityTooltip, TokenActivityHeatmap

APP = QApplication.instance() or QApplication([])


def test_activity_calendar_covers_a_full_year_and_complete_weeks():
    period, days = normalize_activity([], date(2026, 7, 3))

    assert period.start == date(2025, 7, 4)
    assert period.end == date(2026, 7, 3)
    assert period.grid_start.weekday() == 0
    assert period.grid_end.weekday() == 6
    assert len(days) == period.week_count * 7
    assert period.week_count in (52, 53)


def test_calendar_position_uses_week_columns_and_weekday_rows():
    period, _days = normalize_activity([], date(2026, 7, 3))

    assert calendar_position(period.grid_start, period.grid_start) == (0, 0)
    assert calendar_position(period.grid_start + timedelta(days=6), period.grid_start) == (0, 6)
    assert calendar_position(period.grid_start + timedelta(days=7), period.grid_start) == (1, 0)


def test_missing_dates_are_zero_and_source_values_are_aggregated():
    period, days = normalize_activity(
        [
            {"date": "2026-07-03", "tokens": 10, "cost_cny": ".1"},
            {"date": "2026-07-03", "tokens": 15, "cost_cny": ".2"},
        ],
        date(2026, 7, 3),
    )
    by_date = {day.date: day for day in days}

    assert by_date[period.start].token_count == 0
    assert by_date[date(2026, 7, 3)].token_count == 25
    assert by_date[date(2026, 7, 3)].amount == 0.3


def test_levels_use_robust_dynamic_scale():
    _period, days = normalize_activity(
        [
            {"date": "2026-07-01", "tokens": 10},
            {"date": "2026-07-02", "tokens": 100},
            {"date": "2026-07-03", "tokens": 1_000_000},
        ],
        date(2026, 7, 3),
    )
    levels = activity_levels(days)

    assert 1 <= levels[date(2026, 7, 1)] <= 4
    assert levels[date(2026, 7, 1)] < levels[date(2026, 7, 2)]
    assert levels[date(2026, 7, 3)] == 4


def test_token_values_use_wan_units():
    assert compact_tokens(0) == "0万"
    assert compact_tokens(1_500) == "0.15万"
    assert compact_tokens(1_500_000) == "150万"

    parent = TokenActivityHeatmap()
    tooltip = ActivityTooltip(parent)
    day = normalize_activity(
        [{"date": "2026-07-03", "tokens": 1_500_000}],
        date(2026, 7, 3),
    )[1][-3]
    tooltip.show_day(day, parent.rect().center())

    assert "Token 使用量：150万" in tooltip._body.text()
    parent.close()


def test_heatmap_renders_complete_calendar_grid():
    heatmap = TokenActivityHeatmap()
    heatmap.set_activity([], date(2026, 7, 3))
    heatmap.resize(heatmap.minimumSize())
    heatmap.show()
    APP.processEvents()
    heatmap.grab()

    assert len(heatmap._hits) >= 365
    assert heatmap.minimumWidth() >= 560
    heatmap.close()


def test_future_padding_uses_the_same_color_as_unused_days():
    heatmap = TokenActivityHeatmap()
    heatmap.set_activity([], date(2026, 7, 3))
    heatmap.resize(heatmap.minimumSize())
    heatmap.show()
    APP.processEvents()
    image = heatmap.grab().toImage()
    horizontal_step = max(
        heatmap.CELL + heatmap.MIN_HORIZONTAL_GAP,
        (heatmap.width() - heatmap.LEFT - 12) // heatmap.period.week_count,
    )

    def cell_center(day):
        week, weekday = calendar_position(day, heatmap.period.grid_start)
        return (
            heatmap.LEFT + week * horizontal_step + heatmap.CELL // 2,
            heatmap.TOP + weekday * (heatmap.CELL + heatmap.GAP) + heatmap.CELL // 2,
        )

    unused_color = image.pixelColor(*cell_center(heatmap.period.start))
    future_color = image.pixelColor(*cell_center(heatmap.period.end + timedelta(days=1)))

    assert future_color == unused_color
    heatmap.close()
