"""Private batch intake; product facts come from the owner's text, never from vision.

The existing item/approval/release pipeline remains the single publishing path.
"""
from __future__ import annotations

import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .core import (Blocked, PRODUCT_FIELDS, atomic_bytes, digest, file_hash, inside, item_dir,
                   item_files, local_lock, now, read_json, save_json, secret_free, valid_id)
from .ingest import IMAGE_EXTENSIONS, ingest_one, metadata

DATE = re.compile(r'(?<!\d)(?:(20\d{2})[-/年])?(\d{1,2})[/月-](\d{1,2})日?(?!\d)')
REF = re.compile(r'(?<![\w-])([A-Za-z][A-Za-z_-]*\d[A-Za-z0-9_-]*)(?=\s|[:：,，]|$)')
LABELS = {'水晶名稱': 'crystal_name', '礦名': 'crystal_name', '水晶': 'crystal_name',
          '商品名稱': 'product_name', '品名': 'product_name', '價格': 'price', '售價': 'price',
          '珠徑': 'bead_size', '庫存': 'stock', '備註': 'notes', 'SKU': 'sku',
          **{k: k for k in PRODUCT_FIELDS}}
LABEL = re.compile(r'(' + '|'.join(sorted(LABELS, key=len, reverse=True)) + r')\s*[:：]\s*', re.I)


def default_time(config: dict) -> str:
    value = config['posting'].get('default_publish_time')
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise Blocked('DEFAULT_PUBLISH_TIME_REQUIRED', manual=True)
    return value


def parsed_date(match, year: int) -> date:
    try:
        return date(int(match[1] or year), int(match[2]), int(match[3]))
    except ValueError:
        raise Blocked('INVALID_PUBLISH_DATE') from None


def parse_intake(text: str, config: dict, *, year: int | None = None) -> dict:
    """Accept owner's short lists or multiline product blocks. Ambiguities stay local.

    Codex can normalize more conversational phrasing into this same explicit list;
    the saved source text is retained and no identities are supplied by this parser.
    """
    secret_free(text)
    zone = config['posting']['timezone']
    if zone != 'Asia/Taipei':
        raise Blocked('BATCH_TIMEZONE_MISMATCH')
    year = year or datetime.now(ZoneInfo(zone)).year
    clock = default_time(config)
    lines = text.replace('；', '\n').replace(';', '\n').splitlines()
    blocks, header, current = [], [], None
    for line in lines:
        if current is not None and LABEL.match(line.strip()):
            current['text'] += '\n' + line
            continue
        first_label = LABEL.search(line)
        matches = list(REF.finditer(line[:first_label.start()] if first_label else line))
        if len(matches) > 1:
            raise Blocked('PUT_EACH_PRODUCT_ON_ITS_OWN_LINE')
        if matches:
            current = {'product_ref': valid_id(matches[0][1]), 'text': line}
            blocks.append(current)
        elif current is not None:
            current['text'] += '\n' + line
        else:
            header.append(line)
    if not blocks:
        raise Blocked('NO_EXPLICIT_PRODUCT_REFERENCES')
    if len(blocks) > 30:
        raise Blocked('BATCH_MORE_THAN_30_PRODUCTS')
    header_dates = [parsed_date(m, year) for m in DATE.finditer('\n'.join(header))]
    if len(header_dates) not in (0, 2):
        raise Blocked('BATCH_DATE_RANGE_AMBIGUOUS')
    start, end = (header_dates if header_dates else (None, None))
    if start and end < start:
        raise Blocked('BATCH_DATE_RANGE_REVERSED_USE_EXPLICIT_YEAR')
    products = []
    for block in blocks:
        raw = block['text']
        issues, facts = [], {k: None for k in PRODUCT_FIELDS}
        # Labeled optional facts are removed before searching for the publish date.
        labels = list(LABEL.finditer(raw))
        spans = []
        for index, label in enumerate(labels):
            stop = labels[index + 1].start() if index + 1 < len(labels) else len(raw)
            fragment = raw[label.end():stop]
            value = re.split(r'[\n，]|,(?!\d{3}(?:\D|$))', fragment, maxsplit=1)[0].strip()
            key = next(v for k, v in LABELS.items() if k.casefold() == label[1].casefold())
            if facts[key] is not None:
                issues.append('AMBIGUOUS_' + key.upper())
            facts[key] = value or None
            spans.append((label.start(), label.end() + len(re.split(r'[\n，]|,(?!\d{3}(?:\D|$))', fragment, maxsplit=1)[0])))
        remainder = raw
        for a, b in reversed(spans):
            remainder = remainder[:a] + ' ' + remainder[b:]
        dates = list(DATE.finditer(remainder))
        publish_date = None
        if len(dates) == 1:
            try:
                publish_date = parsed_date(dates[0], start.year if start else year)
            except Blocked as error:
                issues.append(error.code)
        elif len(dates) > 1:
            issues.append('AMBIGUOUS_PUBLISH_DATE')
        else:
            issues.append('USER_PUBLISH_DATE_REQUIRED')
        times = re.findall(r'(?<!\d)(\d{1,2}:[0-5]\d)(?!\d)', remainder)
        publish_time = clock
        if len(times) > 1:
            issues.append('AMBIGUOUS_PUBLISH_TIME')
        elif times:
            publish_time = times[0].zfill(5)
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', publish_time):
                issues.append('INVALID_PUBLISH_TIME')
        if not facts['crystal_name']:
            name = DATE.sub(' ', remainder)
            name = REF.sub(' ', name)
            name = re.sub(r'(?:附|有|約)?(?:這條的|這組的)?[一二三四五六七八九十\d]+張(?:不同角度的)?(?:照片|實拍)', ' ', name)
            name = re.sub(r'\d{1,2}:[0-5]\d|[\[【（(].*?[\]】）)]|(?:發布|發佈|日期|照片|張|→)', ' ', name)
            name = re.sub(r'[，,。]', ' ', name)
            name = name.strip(' \n\t:：,，-')
            if name and len(name) <= 30 and not re.search(r'\s|[:：\d]', name):
                facts['crystal_name'] = name
            else:
                issues.append('USER_CRYSTAL_NAME_REQUIRED')
        for key in ('price', 'stock'):
            if facts[key] is not None:
                numeric = str(facts[key]).replace(',', '')
                numeric = re.sub(r'^(?:NT\$|NTD|\$)\s*', '', numeric, flags=re.I)
                numeric = re.sub(r'\s*(?:元|件|條)$', '', numeric)
                if re.fullmatch(r'\d+(?:\.\d+)?', numeric):
                    facts[key] = float(numeric) if '.' in numeric else int(numeric)
                else:
                    issues.append('INVALID_' + key.upper())
        if publish_date and start and not start <= publish_date <= end:
            issues.append('PUBLISH_DATE_OUTSIDE_BATCH')
        stamp = None
        if publish_date and 'INVALID_PUBLISH_TIME' not in issues and 'AMBIGUOUS_PUBLISH_TIME' not in issues:
            stamp = datetime.fromisoformat(publish_date.isoformat() + 'T' + publish_time).replace(tzinfo=ZoneInfo(zone)).isoformat()
        products.append(dict(product_ref=block['product_ref'], **facts,
                             publish_date=publish_date.isoformat() if publish_date else None,
                             publish_time=publish_time, publish_at=stamp, time_source='user' if times else 'brand_default',
                             user_declaration=raw, issues=issues))
    refs = Counter(p['product_ref'].casefold() for p in products)
    if any(count > 1 for count in refs.values()):
        raise Blocked('DUPLICATE_PRODUCT_REFERENCE')
    actual = sorted(p['publish_date'] for p in products if p['publish_date'])
    return {'timezone': zone, 'default_publish_time': clock, 'intake_year': year,
            'date_range': {'start': start.isoformat() if start else (actual[0] if actual else None),
                           'end': end.isoformat() if end else (actual[-1] if actual else None)}, 'products': products}


def batch_path(content: Path, batch_id: str) -> Path:
    return inside(content / 'batches', valid_id(batch_id))


def declared_schedule(product: dict) -> dict:
    return {k: product.get(k) for k in ('publish_date', 'publish_time', 'publish_at', 'time_source')}


def write_binding(folder: Path, manifest: dict, product: dict):
    provided = {k: product.get(k) for k in PRODUCT_FIELDS}
    atomic_bytes(folder / 'product.yaml', yaml.safe_dump(provided, allow_unicode=True, sort_keys=False).encode('utf-8'))
    save_json(folder / 'batch-binding.json', {'brand': manifest['brand'], 'batch_id': manifest['batch_id'],
              'content_id': product['content_id'], 'product_ref': product['product_ref'],
              'metadata_hash': digest(provided), 'declared_schedule': declared_schedule(product),
              'source_images': [{k: a[k] for k in ('file', 'sha256')} for a in product['source_images']]})


def intake_batch(content: Path, config: dict, text: str, source: Path, *, batch_id: str | None = None, year: int | None = None) -> dict:
    parsed = parse_intake(text, config, year=year)
    dates = parsed['date_range']
    batch_id = valid_id(batch_id or f'{dates["start"] or "undated"}_to_{dates["end"] or "undated"}')
    folder = batch_path(content, batch_id)
    source = source.resolve()
    if not source.is_dir() or source == folder.resolve() or source.is_relative_to(folder.resolve()):
        raise Blocked('BATCH_SOURCE_DIRECTORY_REQUIRED')
    old = read_json(folder / 'batch.json')
    if old:
        if old['intake_hash'] != digest({'text': text, 'source': str(source), 'parsed': parsed}):
            raise Blocked('BATCH_EXISTS_USE_TARGETED_UPDATE')
        return refresh_batch(content, batch_id)
    manifest = dict(parsed, schema_version=1, batch_id=batch_id, brand=config['brand'], created_at=now(),
                    intake_hash=digest({'text': text, 'source': str(source), 'parsed': parsed}),
                    source_directory=str(source), status='DRAFT', approval_granted=False)
    for product in manifest['products']:
        product['content_id'] = valid_id(f'{config["brand"]}-{batch_id}-{product["product_ref"]}')
        product['source_images'] = []
        product['status'] = 'DRAFT'
        incoming = inside(source, product['product_ref'])
        destination = inside(folder, product['product_ref'])
        destination.mkdir(parents=True, exist_ok=True)
        if not incoming.is_dir():
            product['issues'].append('PRODUCT_PHOTO_GROUP_MISSING')
        else:
            # Only explicitly named groups are read; no photo-based guessing of groups or identity.
            if (source / product['product_ref']).is_symlink():
                raise Blocked('SYMLINK_PRODUCT_FOLDER')
            photos = sorted(p for p in incoming.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
            if len(photos) > 50:
                raise Blocked('MORE_THAN_50_PHOTOS_IN_ONE_PRODUCT')
            for photo in photos:
                if photo.is_symlink() or not photo.is_file() or photo.stat().st_size > 60_000_000:
                    raise Blocked('INVALID_SOURCE_PHOTO')
                sha = file_hash(photo)
                target = inside(destination, photo.name)
                if target.exists() and file_hash(target) != sha:
                    raise Blocked('BATCH_ORIGINAL_COLLISION')
                if not target.exists():
                    shutil.copy2(photo, target)
                if file_hash(target) != sha:
                    raise Blocked('BATCH_COPY_HASH_MISMATCH')
                product['source_images'].append({'asset_id': product['content_id'] + '-' + sha[:24],
                    'content_id': product['content_id'], 'file': photo.name, 'sha256': sha,
                    'path': target.relative_to(content).as_posix()})
        if not product['source_images'] and 'PRODUCT_PHOTO_GROUP_MISSING' not in product['issues']:
            product['issues'].append('NO_USABLE_PHOTOS')
        write_binding(destination, manifest, product)
    known = {p['product_ref'] for p in manifest['products']}
    manifest['unmapped_groups'] = sorted(p.name for p in source.iterdir() if p.is_dir() and p.name not in known)
    manifest['unmapped_images'] = sorted(p.name for p in source.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    atomic_bytes(folder / 'intake.txt', text.encode('utf-8'))
    save_json(folder / 'batch.json', manifest)
    return refresh_batch(content, batch_id)


def batch_conflicts(content: Path) -> dict:
    hashes, days = defaultdict(set), defaultdict(set)
    for path in (content / 'batches').glob('*/batch.json'):
        for product in read_json(path)['products']:
            cid = product['content_id']
            item = read_json(item_dir(content, cid) / 'item.json', {})
            if item.get('status') == 'CANCELLED':
                continue
            if product.get('publish_date'):
                days[product['publish_date']].add(cid)
            for asset in product['source_images']:
                hashes[asset['sha256']].add(cid)
    for path in item_files(content):
        item = read_json(path)
        for photo in item['photos']:
            hashes[photo['source_sha256']].add(item['content_id'])
    return {'photo_hashes': {k: sorted(v) for k, v in hashes.items() if len(v) > 1},
            'dates': {k: sorted(v) for k, v in days.items() if len(v) > 1}}


def refresh_batch(content: Path, batch_id: str) -> dict:
    path = batch_path(content, batch_id) / 'batch.json'
    manifest = read_json(path)
    if not manifest:
        raise Blocked('BATCH_NOT_FOUND')
    conflicts = batch_conflicts(content)
    for product in manifest['products']:
        item = read_json(item_dir(content, product['content_id']) / 'item.json', {})
        product['binding_errors'] = ['CROSS_PRODUCT_PHOTO_HASH'] if any(product['content_id'] in v for v in conflicts['photo_hashes'].values()) else []
        product['schedule_warnings'] = ['SAME_DAY_MULTIPLE_PRODUCTS'] if product.get('publish_date') in conflicts['dates'] else []
        product['status'] = item.get('status', 'NEEDS_INFO' if product['issues'] or product['binding_errors'] else 'DRAFT')
        if product['binding_errors']:
            product['status'] = 'NEEDS_INFO'
    manifest['conflicts'] = conflicts
    manifest['counts'] = dict(Counter(p['status'] for p in manifest['products']))
    manifest['status'] = 'READY_FOR_REVIEW' if all(p['status'] == 'READY_FOR_REVIEW' for p in manifest['products']) else 'PARTIAL'
    save_json(path, manifest)
    return manifest


def assert_batch_binding(content: Path, item: dict):
    if not item.get('batch_id'):
        return
    manifest = refresh_batch(content, item['batch_id'])
    product = next((p for p in manifest['products'] if p['content_id'] == item['content_id']), None)
    if (not product or item['brand'] != manifest['brand'] or item['user_provided'] != {k: product[k] for k in PRODUCT_FIELDS}
            or item.get('declared_schedule') != declared_schedule(product) or item.get('publish_at') != product.get('publish_at')):
        raise Blocked('BATCH_PRODUCT_BINDING_MISMATCH')
    if product.get('binding_errors'):
        raise Blocked('CROSS_PRODUCT_PHOTO_HASH')
    if product.get('issues'):
        raise Blocked('BATCH_INTAKE_NEEDS_INFO')
    expected = {a['sha256'] for a in product['source_images']}
    if {p['source_sha256'] for p in item['photos']} != expected:
        raise Blocked('BATCH_PHOTO_BINDING_MISMATCH')


def prepare_batch(content: Path, config: dict, batch_id: str, generator_factory) -> list[dict]:
    from .pipeline import check_prepared, prepare_one
    with local_lock(content):
        manifest = refresh_batch(content, batch_id)
        generator, results, recent = None, [], []
        for product in manifest['products']:
            try:
                item = ingest_one(content, batch_path(content, batch_id) / product['product_ref'], config['brand'])
                if product.get('binding_errors'):
                    raise Blocked('CROSS_PRODUCT_PHOTO_HASH')
                if item['status'] in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'):
                    results.append(item)
                    continue
                current = False
                if item['status'] in ('READY_FOR_REVIEW', 'APPROVED', 'SCHEDULED'):
                    try:
                        check_prepared(content, item)
                        current = True
                    except Blocked:
                        if item.get('release_hash'):
                            raise Blocked('REVOKE_REMOTE_SCHEDULE_BEFORE_EDIT')
                if not current:
                    generator = generator or generator_factory()
                    item = prepare_one(content, item, config, generator, recent)
                if product['issues'] and item['status'] not in ('PUBLISHED', 'PUBLISHING', 'CANCELLED'):
                    item.update(status='NEEDS_INFO', approval=None, approval_state='PENDING',
                                prepare_errors=sorted(set(item.get('prepare_errors', []) + product['issues'])))
                folder = item_dir(content, item['content_id'])
                save_json(folder / 'user_declared_facts.json', dict(item['user_provided'], content_id=item['content_id'],
                          batch_id=batch_id, publish_date=product['publish_date'], publish_time=product['publish_time'],
                          source='owner_batch_declaration', declaration=product['user_declaration']))
                save_json(folder / 'item.json', item)
                results.append(item)
                recent.append({k: item.get(k) for k in ('hook', 'caption_structure', 'colour_families')})
            except Blocked as error:
                path = item_dir(content, product['content_id']) / 'item.json'
                item = read_json(path)
                if item and item['status'] not in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'):
                    item.update(status='NEEDS_INFO', approval=None, approval_state='PENDING', prepare_errors=[error.code])
                    save_json(path, item)
                results.append({'content_id': product['content_id'], 'status': 'NEEDS_INFO', 'prepare_errors': [error.code]})
        refresh_batch(content, batch_id)
        return results


def select_range(content: Path, batch_id: str, start: str, end: str) -> list[dict]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise Blocked('APPROVAL_RANGE_REQUIRES_ISO_DATES') from None
    if last < first:
        raise Blocked('APPROVAL_RANGE_REVERSED')
    manifest = refresh_batch(content, batch_id)
    selected = []
    for product in manifest['products']:
        day = product.get('publish_date')
        if day and first <= date.fromisoformat(day) <= last:
            item = read_json(item_dir(content, product['content_id']) / 'item.json')
            if not item or item['status'] != 'READY_FOR_REVIEW':
                raise Blocked('RANGE_CONTAINS_ITEM_NOT_READY')
            assert_batch_binding(content, item)
            selected.append(item)
    if not selected:
        raise Blocked('NO_PRODUCTS_IN_APPROVAL_RANGE')
    return selected


def approve_range(content: Path, config: dict, batch_id: str, start: str, end: str):
    from .pipeline import check_prepared
    from .release import approve
    selected = select_range(content, batch_id, start, end)
    # Validate every selected item before recording any approvals.
    for item in selected:
        check_prepared(content, item)
    result = [approve(content, item, config) for item in selected]
    refresh_batch(content, batch_id)
    return result


def resolve_item(content: Path, reference: str) -> dict:
    direct = read_json(item_dir(content, reference) / 'item.json')
    if direct:
        return direct
    matches = [read_json(p) for p in item_files(content) if read_json(p).get('product_ref') == reference]
    if len(matches) != 1:
        raise Blocked('PRODUCT_REFERENCE_AMBIGUOUS_USE_CONTENT_ID' if matches else 'ITEM_NOT_FOUND')
    return matches[0]


def update_product(content: Path, config: dict, batch_id: str, product_ref: str, changes: dict):
    """Explicit single-product facts/date edit. Caller must revoke any remote queue first."""
    if not changes or set(changes) - set(PRODUCT_FIELDS) - {'publish_date', 'publish_time'}:
        raise Blocked('INVALID_BATCH_UPDATE')
    secret_free(changes)
    folder = batch_path(content, batch_id)
    manifest = read_json(folder / 'batch.json')
    if not manifest:
        raise Blocked('BATCH_NOT_FOUND')
    product = next((p for p in manifest['products'] if p['product_ref'] == product_ref), None)
    if not product:
        raise Blocked('PRODUCT_REFERENCE_NOT_FOUND')
    item = read_json(item_dir(content, product['content_id']) / 'item.json', {})
    if item.get('status') in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'):
        raise Blocked('IMMUTABLE_OR_UNCERTAIN_PRODUCT')
    if item.get('release_hash'):
        raise Blocked('REVOKE_REMOTE_SCHEDULE_BEFORE_EDIT')
    updated = dict(product, **changes)
    # Validate through the same parser; every changed value remains explicitly owner supplied.
    lines = [product_ref, updated.get('publish_date') or '', updated.get('publish_time') or default_time(config)]
    lines += [f'{key}: {updated[key]}' for key in PRODUCT_FIELDS if updated.get(key) is not None]
    parsed = parse_intake('\n'.join(lines), config)['products'][0]
    product.update({k: parsed[k] for k in (*PRODUCT_FIELDS, 'publish_date', 'publish_time', 'publish_at', 'time_source', 'issues')})
    product['user_declaration'] += '\n明確修改：' + str(changes)
    write_binding(folder / product_ref, manifest, product)
    save_json(folder / 'batch.json', manifest)
    return ingest_one(content, folder / product_ref, config['brand'])


def add_photos(content: Path, config: dict, batch_id: str, product_ref: str, source: Path):
    """Owner explicitly maps this photo folder to one product; originals never overwritten."""
    folder = batch_path(content, batch_id)
    manifest = read_json(folder / 'batch.json')
    if not manifest:
        raise Blocked('BATCH_NOT_FOUND')
    product = next((p for p in manifest['products'] if p['product_ref'] == product_ref), None)
    if not product:
        raise Blocked('PRODUCT_REFERENCE_NOT_FOUND')
    prior = read_json(item_dir(content, product['content_id']) / 'item.json', {})
    if prior.get('status') in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'CANCELLED') or prior.get('release_hash'):
        raise Blocked('IMMUTABLE_OR_REVOKE_REMOTE_FIRST')
    source = source.resolve()
    if not source.is_dir():
        raise Blocked('PRODUCT_PHOTO_GROUP_MISSING')
    existing = {a['file']: a for a in product['source_images']}
    new = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if len(set(existing) | {p.name for p in new}) > 50:
        raise Blocked('MORE_THAN_50_PHOTOS_IN_ONE_PRODUCT')
    for photo in new:
        if photo.is_symlink() or not photo.is_file() or photo.stat().st_size > 60_000_000:
            raise Blocked('INVALID_SOURCE_PHOTO')
        sha = file_hash(photo)
        target = inside(folder / product_ref, photo.name)
        if target.exists() and file_hash(target) != sha:
            raise Blocked('BATCH_ORIGINAL_COLLISION_RENAME_NEW_PHOTO')
        if not target.exists():
            shutil.copy2(photo, target)
        if file_hash(target) != sha:
            raise Blocked('BATCH_COPY_HASH_MISMATCH')
        existing[photo.name] = {'file': photo.name, 'sha256': sha, 'content_id': product['content_id'],
                              'asset_id': product['content_id'] + '-' + sha[:24], 'path': target.relative_to(content).as_posix()}
    product['source_images'] = list(existing.values())
    if product['source_images']:
        product['issues'] = [x for x in product['issues'] if x not in ('PRODUCT_PHOTO_GROUP_MISSING', 'NO_USABLE_PHOTOS')]
    write_binding(folder / product_ref, manifest, product)
    save_json(folder / 'batch.json', manifest)
    return ingest_one(content, folder / product_ref, config['brand'])
