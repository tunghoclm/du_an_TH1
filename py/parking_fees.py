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


def calculate_turn_fee(prices, entry_time: datetime, exit_time: datetime, hourly_fallback: int,
                       grace_minutes: int = 0, daily_cap: int = 0, *, free_minutes: int = 0,
                       first_block_hours: int = 0, first_block_amount: int = 0,
                       next_hour_amount: int = 0):
    """Return (total, explanation), charging each window occurrence once.

    Rates repeat daily; an overnight window is one occurrence across midnight.
    The oldest configured window wins overlaps, matching entry-price selection.
    HH:MM end values include the whole final minute. The window active at exit
    is included, so 13:00:00 already incurs the window starting at 13:00.
    Unpriced time uses the existing hourly fallback, rounded up in aggregate.
    """
    seconds = max(0, (exit_time - entry_time).total_seconds())
    if free_minutes > 0 and seconds <= free_minutes * 60:
        return 0, f'Miễn phí {free_minutes} phút đầu'
    if first_block_hours > 0:
        extra_hours = max(0, math.ceil((seconds - first_block_hours * 3600) / 3600))
        buckets = {0: first_block_amount}
        # Each started extra hour is charged in its 24h cycle from entry.
        for hour in range(extra_hours):
            bucket = (first_block_hours + hour) // 24
            buckets[bucket] = buckets.get(bucket, 0) + next_hour_amount
        total = sum(min(amount, daily_cap) if daily_cap > 0 else amount
                    for amount in buckets.values())
        note = (f'Block đầu {first_block_hours} giờ: {_money(first_block_amount)}'
                f' + {extra_hours} giờ tiếp theo × {_money(next_hour_amount)}/giờ')
        if daily_cap > 0:
            note += f' · Trần {_money(daily_cap)}/24h từ lúc vào'
        return total, note + f' = {_money(total)}'
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
    buckets = {}
    missing_buckets = {}
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
                cursor = max(entry_time, window_start)
                stop = min(exit_time, window_end)
                while cursor < stop or (at_exit and cursor == stop):
                    bucket = int((cursor - entry_time).total_seconds() // 86400)
                    edge = min(stop, entry_time + timedelta(days=bucket + 1))
                    missing_buckets[bucket] = missing_buckets.get(bucket, 0) + max(0, (edge - cursor).total_seconds())
                    if edge >= stop:
                        break
                    cursor = edge
                continue
            row, rate_start, rate_end = winner
            anchor = day.date()
            if rate_start > rate_end and start <= rate_end:
                anchor -= timedelta(days=1)
            occurrence = (row['period_id'], anchor)
            if occurrence in seen:
                continue
            seen.add(occurrence)
            occurrence_start = datetime.combine(anchor, entry_time.time().replace(hour=0, minute=0, second=0, microsecond=0)) + timedelta(minutes=rate_start)
            if entry_time < occurrence_start and grace_minutes > 0 and exit_time < occurrence_start + timedelta(minutes=grace_minutes):
                continue
            charged_at = max(entry_time, window_start)
            bucket = int((charged_at - entry_time).total_seconds() // 86400)
            buckets[bucket] = buckets.get(bucket, 0) + row['amount']
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
    if daily_cap > 0:
        for bucket, seconds in missing_buckets.items():
            buckets[bucket] = buckets.get(bucket, 0) + max(1, math.ceil(seconds / 3600)) * hourly_fallback
        total = min(total, sum(min(value, daily_cap) for value in buckets.values()))
    explanation = ' + '.join(descriptions)
    if len(descriptions) > 1:
        explanation += f' = {_money(total)}'
    if grace_minutes:
        explanation += f' · Ân hạn giao thời: {grace_minutes} phút'
    if daily_cap > 0:
        explanation += f' · Giá trần {_money(daily_cap)}/24h từ lúc vào: {_money(total)}'
    return total, explanation
