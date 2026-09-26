from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.parse import quote, urlparse

from PIL import Image

from .core import (Blocked, atomic_bytes, digest, file_hash, inside, item_dir, now,
                   parse_time, read_json, save_json, secret_free, text_hash, valid_id)
from .pipeline import check_prepared
from .schemas import QA_KEYS


def approval_fingerprint(item: dict, config: dict):
    return digest({key: item.get(key) for key in ('brand', 'content_id', 'input_hash', 'qa_hash',
                   'selected_photo_ids', 'content_type', 'publish_at')} | {'target': config['target']})


def approve(content: Path, item: dict, config: dict):
    if item['status'] not in ('READY_FOR_REVIEW', 'APPROVED', 'SCHEDULED'):
        raise Blocked('ITEM_NOT_READY')
    check_prepared(content, item)
    if not item.get('publish_at'):
        raise Blocked('SET_CALENDAR_FIRST')
    if not all(config['target'].values()):
        raise Blocked('TARGET_NOT_PINNED', manual=True)
    if (item.get('approval') or {}).get('mode') == 'manual' and item.get('approval_state') == 'APPROVED' and item['approval'].get('state') == 'APPROVED' and item['approval'].get('source') == 'explicit_approval_command' and item['approval'].get('fingerprint') == approval_fingerprint(item, config):
        return item
    item['approval'] = {'mode': 'manual', 'state': 'APPROVED', 'source': 'explicit_approval_command',
                        'approved_at': now(), 'fingerprint': approval_fingerprint(item, config)}
    item['approval_state'] = 'APPROVED'
    item['status'] = 'APPROVED'
    save_json(item_dir(content, item['content_id']) / 'item.json', item)
    return item


def build_release(content: Path, item: dict, config: dict) -> dict:
    if item.get('status') not in ('APPROVED', 'SCHEDULED') or item.get('approval_state') != 'APPROVED':
        raise Blocked('EXPLICIT_APPROVAL_REQUIRED')
    report = check_prepared(content, item)
    if item['brand'] != config['brand']:
        raise Blocked('BRAND_MISMATCH')
    if not all(config['target'].values()):
        raise Blocked('TARGET_NOT_PINNED', manual=True)
    parse_time(item.get('publish_at'))
    approval = item.get('approval') or {}
    if (approval.get('mode') != 'manual' or approval.get('state') != 'APPROVED' or
            approval.get('fingerprint') != approval_fingerprint(item, config)):
        raise Blocked('APPROVAL_MISSING_OR_STALE')
    folder = item_dir(content, item['content_id'])
    photos = {p['photo_id']: p for p in item['photos']}
    assets = []
    prefix = config['hosting']['namespace'] + '/' + valid_id(item['content_id'])
    for index, key in enumerate(item['selected_photo_ids']):
        p = photos[key]
        name = f'{index + 1:02d}-{p["processed_sha256"][:16]}.jpg'
        public_path = prefix + '/' + name
        assets.append({'photo_id': key, 'path': public_path, 'sha256': p['processed_sha256'],
                       'mime': 'image/jpeg', 'width': 1080, 'height': 1350,
                       'url': config['hosting']['base_url'].rstrip('/') + '/' + public_path})
    caption = (folder / 'selected_caption.txt').read_text(encoding='utf-8')
    release = {'schema_version': 3, 'brand': item['brand'], 'content_id': item['content_id'],
               'input_hash': item['input_hash'], 'target': config['target'], 'api_version': config['api_version'],
               'content_type': item['content_type'], 'publish_at': item['publish_at'],
               'namespace': config['hosting']['namespace'], 'assets': assets,
               'caption_path': f'releases/{item["brand"]}/{item["content_id"]}/caption.txt',
               'caption_sha256': text_hash(caption), 'source_asset_hashes': [photos[k]['source_sha256'] for k in item['selected_photo_ids']],
               'qa': {'result': 'PASS', 'brand': item['brand'], 'content_id': item['content_id'],
                      'input_hash': item['input_hash'], 'caption_hash': report['caption_hash'],
                      'checks': report['checks'], 'local_report_hash': digest(report),
                      'selected_photo_ids': item['selected_photo_ids']},
               'approval': approval, 'approval_state': 'APPROVED', 'status': 'APPROVED'}
    release['release_hash'] = digest(release)
    secret_free(release)
    return release


def stage_release(repo: Path, content: Path, item: dict, config: dict):
    release = build_release(content, item, config)
    folder = item_dir(content, item['content_id'])
    photos = {p['photo_id']: p for p in item['photos']}
    for asset in release['assets']:
        destination = inside(repo, asset['path'])
        source = inside(folder, photos[asset['photo_id']]['processed_path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and file_hash(destination) != asset['sha256']:
            raise Blocked('PUBLIC_IMMUTABLE_ASSET_COLLISION')
        if not destination.exists():
            shutil.copyfile(source, destination)
    caption_path = inside(repo, release['caption_path'])
    atomic_bytes(caption_path, (folder / 'selected_caption.txt').read_bytes())
    save_json(caption_path.parent / 'release.json', release)
    item['approval'] = release['approval']
    save_json(folder / 'item.json', item)
    return release


def require_approved_release(release: dict):
    """Fail before any network call, including explicit test publication."""
    approval = release.get('approval') or {}
    if (release.get('status') not in ('APPROVED', 'SCHEDULED') or release.get('approval_state') != 'APPROVED' or
            approval.get('mode') != 'manual' or approval.get('state') != 'APPROVED' or
            approval.get('source') != 'explicit_approval_command' or not approval.get('approved_at')):
        raise Blocked('EXPLICIT_APPROVAL_REQUIRED')
    parse_time(approval['approved_at'])
    fingerprint_item = {k: release.get(k) for k in ('brand', 'content_id', 'input_hash', 'content_type', 'publish_at')}
    fingerprint_item.update(qa_hash=release.get('qa', {}).get('local_report_hash'),
                            selected_photo_ids=[a.get('photo_id') for a in release.get('assets', [])])
    if approval.get('fingerprint') != approval_fingerprint(fingerprint_item, {'target': release.get('target')}):
        raise Blocked('APPROVAL_MISSING_OR_STALE')


def validate_release(repo: Path, release: dict, config: dict):
    require_approved_release(release)
    brand, cid = config['brand'], valid_id(release.get('content_id'))
    if release.get('schema_version') != 3 or release.get('brand') != brand or not cid.startswith(brand + '-'):
        raise Blocked('RELEASE_BRAND_MISMATCH')
    if release.get('target') != config['target'] or not all(config['target'].values()):
        raise Blocked('RELEASE_TARGET_MISMATCH')
    if release.get('api_version') != config['api_version'] or release.get('namespace') != f'media/{brand}':
        raise Blocked('RELEASE_CONFIG_MISMATCH')
    expected_hash = digest({k: v for k, v in release.items() if k != 'release_hash'})
    if release.get('release_hash') != expected_hash:
        raise Blocked('RELEASE_TAMPERED')
    if release.get('content_type') not in config['publishing']['enabled_types']:
        raise Blocked('MEDIA_TYPE_NOT_ENABLED')
    count = len(release.get('assets', []))
    if (release['content_type'] == 'SINGLE' and count != 1) or (release['content_type'] == 'CAROUSEL' and not 2 <= count <= 10):
        raise Blocked('INVALID_MEDIA_COUNT')
    if len(release.get('source_asset_hashes', [])) != count or len(set(a.get('photo_id') for a in release['assets'])) != count:
        raise Blocked('INVALID_SOURCE_ASSET_BINDING')
    qa = release.get('qa', {})
    if (qa.get('result') != 'PASS' or qa.get('brand') != brand or qa.get('content_id') != cid or
        qa.get('input_hash') != release.get('input_hash') or qa.get('caption_hash') != release.get('caption_sha256') or
        set(qa.get('checks', {})) != set(QA_KEYS) or any(v is not True for v in qa['checks'].values()) or
        qa.get('selected_photo_ids') != [a['photo_id'] for a in release['assets']]):
        raise Blocked('CAPTION_QA_NOT_VALID')
    expected_caption_path = f'releases/{brand}/{cid}/caption.txt'
    if release.get('caption_path') != expected_caption_path:
        raise Blocked('CAPTION_NAMESPACE_MISMATCH')
    caption_file = inside(repo, expected_caption_path)
    if not caption_file.is_file() or file_hash(caption_file) != release['caption_sha256']:
        raise Blocked('CAPTION_HASH_MISMATCH')
    caption = caption_file.read_text(encoding='utf-8')
    if not caption.strip() or len(caption) > 2200:
        raise Blocked('CAPTION_INVALID')
    parse_time(release.get('publish_at'))
    for asset in release['assets']:
        path = asset.get('path', '')
        if not path.startswith(f'media/{brand}/{cid}/') or Path(path).name != path.split('/')[-1] or '..' in path or '\\' in path:
            raise Blocked('ASSET_NAMESPACE_MISMATCH')
        expected_url = config['hosting']['base_url'].rstrip('/') + '/' + path
        if asset.get('url') != expected_url or not expected_url.startswith('https://'):
            raise Blocked('ASSET_URL_MISMATCH')
        local = inside(repo, path)
        if not local.is_file() or file_hash(local) != asset['sha256']:
            raise Blocked('ASSET_HASH_MISMATCH')
        with Image.open(local) as im:
            if im.format != 'JPEG' or im.size != (1080, 1350) or asset.get('mime') != 'image/jpeg':
                raise Blocked('MEDIA_FORMAT_INVALID')
            im.verify()
        if local.stat().st_size > 8_000_000:
            raise Blocked('IMAGE_TOO_LARGE')
    secret_free(release)
    secret_free(caption)
    return caption


def verify_hosted(release: dict, transport):
    for asset in release['assets']:
        raw, mime = transport.request('GET', asset['url'])
        if mime != 'image/jpeg' or hashlib.sha256(raw).hexdigest() != asset['sha256']:
            raise Blocked('HOSTING_BYTES_OR_MIME_MISMATCH')
    return True
