from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .core import Blocked, atomic_bytes, item_files, now, parse_time, read_json, save_json


def calendar_rows(content: Path) -> list[dict]:
    rows = []
    for path in item_files(content):
        item = read_json(path)
        photos = {p['photo_id']: p for p in item.get('photos', [])}
        rows.append({'content_id': item['content_id'], 'brand': item['brand'], 'publish_at': item.get('publish_at'),
                     'content_type': item.get('content_type'),
                     'asset_paths': [f'items/{item["content_id"]}/' + photos[k]['processed_path'] for k in item.get('selected_photo_ids', [])],
                     'caption_path': f'items/{item["content_id"]}/selected_caption.txt', 'status': item['status'],
                     'schedule_state': 'SCHEDULED' if item['status'] == 'SCHEDULED' else 'PROPOSED_SCHEDULE'})
    return sorted(rows, key=lambda x: (x['publish_at'] or '9999', x['content_id']))


def save_calendar(content: Path, config: dict):
    data = {'brand': config['brand'], 'timezone': config['posting']['timezone'],
            'posting_defaults_need_review': config['posting'].get('defaults_need_review', False),
            'posting_note': config['posting'].get('note'), 'items': calendar_rows(content)}
    atomic_bytes(content / 'calendar' / 'calendar.yaml', yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode('utf-8'))
    save_json(content / 'calendar' / 'calendar.json', data)
    return data


def plan_calendar(content: Path, config: dict, start: datetime | None = None):
    settings = config['posting']
    zone = ZoneInfo(settings['timezone'])
    start = (start or datetime.now(timezone.utc)).astimezone(zone)
    days, times, maximum = settings['posting_days'], settings['posting_times'], settings['posts_per_week']
    if not days or not times or not isinstance(maximum, int) or maximum < 1 or any(d not in range(7) for d in days):
        raise Blocked('INVALID_POSTING_CONFIGURATION')
    try:
        parsed_times = [datetime.strptime(t, '%H:%M').time() for t in times]
    except (ValueError, TypeError):
        raise Blocked('INVALID_POSTING_TIME') from None
    items = [read_json(p) for p in item_files(content)]
    scheduled = [x for x in items if x.get('publish_at') and x['status'] != 'CANCELLED']
    occupied = {parse_time(x['publish_at']).astimezone(zone) for x in scheduled}
    counts = Counter((t.isocalendar().year, t.isocalendar().week) for t in occupied)
    pending = [x for x in items if not x.get('publish_at') and x['status'] == 'READY_FOR_REVIEW']
    history = sorted(scheduled, key=lambda x: x['publish_at'])[-5:]
    def penalty(item):
        score = 0
        for index, previous in enumerate(reversed(history[-3:])):
            weight = 3 - index
            score += weight * 4 * bool(set(item.get('colour_families', [])) & set(previous.get('colour_families', [])))
            score += weight * 3 * (item.get('caption_structure') == previous.get('caption_structure'))
            score += weight * 6 * (item.get('hook') == previous.get('hook'))
            score += weight * (item.get('content_style') == previous.get('content_style'))
            score += weight * (item.get('cover_composition') == previous.get('cover_composition'))
        return score, item['content_id']
    for day_index in range(730):
        day = start.date() + timedelta(days=day_index)
        if day.weekday() not in days:
            continue
        for clock in sorted(parsed_times):
            slot = datetime.combine(day, clock, zone)
            week = (slot.isocalendar().year, slot.isocalendar().week)
            if slot <= start or slot in occupied or counts[week] >= maximum:
                continue
            eligible = []
            for item in pending:
                sku = item['user_provided'].get('sku')
                repeats = [parse_time(p['publish_at']) for p in scheduled if sku and p.get('user_provided', {}).get('sku') == sku]
                if any(abs((slot - p).total_seconds()) < settings.get('product_repeat_days', 30) * 86400 for p in repeats):
                    continue
                eligible.append(item)
            if not eligible:
                continue
            chosen = min(eligible, key=penalty)
            pending.remove(chosen)
            chosen['publish_at'] = slot.isoformat()
            chosen['approval'] = None
            save_json(content / 'items' / chosen['content_id'] / 'item.json', chosen)
            occupied.add(slot)
            counts[week] += 1
            scheduled.append(chosen)
            history.append(chosen)
        if not pending:
            break
    if pending:
        raise Blocked('CALENDAR_CAPACITY_EXCEEDED')
    return save_calendar(content, config)
