"""Invoice time presets. Calendar boundaries are inclusive dates, exclusive datetimes."""
from datetime import date, datetime, time, timedelta

from lunar_vn import LunarDate, lunar_to_solar, solar_to_lunar


PERIOD_GROUPS = (
    ('Theo ngày', (('today', 'Hôm nay'), ('yesterday', 'Hôm qua'))),
    ('Theo tuần', (('week', 'Tuần này'), ('last_week', 'Tuần trước'), ('7days', '7 ngày qua'))),
    ('Theo tháng', (('month', 'Tháng này'), ('last_month', 'Tháng trước'),
                    ('lunar_month', 'Tháng này (âm lịch)'), ('last_lunar_month', 'Tháng trước (âm lịch)'),
                    ('30days', '30 ngày qua'))),
    ('Theo quý', (('quarter', 'Quý này'), ('last_quarter', 'Quý trước'))),
    ('Theo năm', (('year', 'Năm nay'), ('last_year', 'Năm trước'),
                  ('lunar_year', 'Năm nay (âm lịch)'), ('last_lunar_year', 'Năm trước (âm lịch)'),
                  ('all', 'Toàn thời gian'))),
)
PERIOD_LABELS = dict(option for _, options in PERIOD_GROUPS for option in options)


def shift_month(value, offset):
    year, month = divmod(value.year * 12 + value.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def period_bounds(key, today, start_value='', end_value=''):
    """Return [start, end) using Vietnamese lunar dates and Monday-based weeks."""
    if key == 'all':
        return None, None
    if key == 'custom':
        try:
            start = datetime.fromisoformat(start_value)
            end = datetime.fromisoformat(end_value)
            if start.tzinfo is not None or end.tzinfo is not None or start > end:
                raise ValueError
            # A date includes the whole day; a datetime includes the entire selected minute.
            end += timedelta(days=1) if len(end_value) == 10 else timedelta(minutes=1)
            return start, end
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Vui lòng chọn thời gian bắt đầu và kết thúc hợp lệ, theo đúng thứ tự.') from None
    if key == 'today':
        start, end = today, today + timedelta(days=1)
    elif key == 'yesterday':
        start, end = today - timedelta(days=1), today
    elif key in ('7days', '30days'):
        start = today - timedelta(days=6 if key == '7days' else 29)
        end = today + timedelta(days=1)
    elif key in ('week', 'last_week'):
        start = today - timedelta(days=today.weekday() + (7 if key == 'last_week' else 0))
        end = start + timedelta(days=7)
    elif key in ('month', 'last_month'):
        start = shift_month(today, -1 if key == 'last_month' else 0)
        end = shift_month(start, 1)
    elif key in ('quarter', 'last_quarter'):
        start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        if key == 'last_quarter':
            start = shift_month(start, -3)
        end = shift_month(start, 3)
    elif key in ('year', 'last_year'):
        year = today.year - (key == 'last_year')
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
    elif key in ('lunar_month', 'last_lunar_month'):
        # Derive month starts from actual lunar days, including leap months.
        start = today - timedelta(days=solar_to_lunar(today).day - 1)
        if key == 'last_lunar_month':
            end = start
            previous_day = start - timedelta(days=1)
            start = previous_day - timedelta(days=solar_to_lunar(previous_day).day - 1)
        else:
            end = start + timedelta(days=29)
            if solar_to_lunar(end).day != 1:
                end += timedelta(days=1)
    elif key in ('lunar_year', 'last_lunar_year'):
        year = solar_to_lunar(today).year - (key == 'last_lunar_year')
        start = lunar_to_solar(LunarDate(1, 1, year))
        end = lunar_to_solar(LunarDate(1, 1, year + 1))
    else:
        raise ValueError('Khoảng thời gian không hợp lệ.')
    return datetime.combine(start, time.min), datetime.combine(end, time.min)


def datetime_input(value, end=False):
    """Keep links using date-only filters compatible with datetime-local inputs."""
    if not value:
        return ''
    try:
        stamp = datetime.fromisoformat(value)
        if len(value) == 10 and end:
            stamp = stamp.replace(hour=23, minute=59)
        return stamp.isoformat(timespec='minutes')
    except (ValueError, TypeError):
        return ''
