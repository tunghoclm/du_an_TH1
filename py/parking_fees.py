"""Calculate a stay's fee across every applicable daily pricing window."""
from datetime import datetime, timedelta
import math


def _minutes(hhmm):
    hour, minute = map(int, hhmm.split(':'))
    return hour * 60 + minute


def _contains(minute, start, end):
    return start <= minute <= end if start <= end else minute >= start or minute <= end


def _money(amount):
    return f'{amount:,}'.replace(',', '.') + 'đ'


def calculate_turn_fee(prices, entry_time: datetime, exit_time: datetime, hourly_fallback: int):
    """Return (total, explanation), charging each window occurrence once.

    Rates repeat daily; an overnight window is one occurrence across midnight.
    The oldest configured window wins overlaps, matching entry-price selection.
    HH:MM end values include the whole final minute. The window active at exit
    is included, so 13:00:00 already incurs the window starting at 13:00.
    Unpriced time uses the existing hourly fallback, rounded up in aggregate.
    """
    prices = sorted(prices, key=lambda row: row['period_id'])
    parsed = [(row, _minutes(row['start']), _minutes(row['end'])) for row in prices]
    boundaries = {0, 1440}
    for _, start, end in parsed:
        boundaries.update((start, end + 1))
    boundaries = sorted(boundaries)
    schedule = []
    for start, end in zip(boundaries, boundaries[1:]):
        winner = next((item for item in parsed if _contains(start, item[1], item[2])), None)
        schedule.append((start, end, winner))

    # A zero-length stay still incurs the active window/minimum hourly fee.
    exit_time = max(entry_time, exit_time)
    day = entry_time.replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = exit_time.replace(hour=0, minute=0, second=0, microsecond=0)
    seen = set()
    charges = {}
    missing_seconds = 0
    has_missing_price = False
    while day <= last_day:
        for start, end, winner in schedule:
            window_start = day + timedelta(minutes=start)
            window_end = day + timedelta(minutes=end)
            overlap = (min(exit_time, window_end) - max(entry_time, window_start)).total_seconds()
            at_exit = window_start <= exit_time < window_end
            if overlap <= 0 and not at_exit:
                continue
            if winner is None:
                has_missing_price = True
                missing_seconds += max(0, overlap)
                continue
            row, rate_start, rate_end = winner
            anchor = day.date()
            if rate_start > rate_end and start <= rate_end:
                anchor -= timedelta(days=1)
            occurrence = (row['period_id'], anchor)
            if occurrence in seen:
                continue
            seen.add(occurrence)
            if row['period_id'] not in charges:
                charges[row['period_id']] = dict(row=row, count=0)
            charges[row['period_id']]['count'] += 1
        day += timedelta(days=1)

    total, descriptions = 0, []
    for charge in charges.values():
        row, count = charge['row'], charge['count']
        subtotal = row['amount'] * count
        total += subtotal
        multiplier = f' × {count}' if count > 1 else ''
        descriptions.append(f"{row['period_name']} ({row['start']}–{row['end']}){multiplier}: {_money(subtotal)}")
    if has_missing_price:
        hours = max(1, math.ceil(missing_seconds / 3600))
        subtotal = hours * hourly_fallback
        total += subtotal
        descriptions.append(f'đơn giá dự phòng {_money(hourly_fallback)}/giờ × {hours} giờ')
    explanation = ' + '.join(descriptions)
    if len(descriptions) > 1:
        explanation += f' = {_money(total)}'
    return total, explanation
