from __future__ import annotations

import io
import shutil
import warnings
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, ImageStat

from .core import (Blocked, PRODUCT_FIELDS, cancel_approval, digest, file_hash, inside,
                   item_dir, now, read_json, read_yaml, save_json, secret_free, valid_id)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.tif', '.tiff'}
Image.MAX_IMAGE_PIXELS = 60_000_000


def metadata(folder: Path) -> dict:
    path = folder / 'product.yaml'
    data = read_yaml(path) if path.exists() and path.stat().st_size else {}
    if set(data) - set(PRODUCT_FIELDS):
        raise Blocked('UNRECOGNIZED_PRODUCT_FIELD')
    result = {key: data.get(key) for key in PRODUCT_FIELDS}
    for key, value in result.items():
        if value is None or value == '':
            result[key] = None
        elif isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise Blocked('PRODUCT_VALUE_MUST_BE_SCALAR')
        elif len(str(value)) > 3000:
            raise Blocked('PRODUCT_VALUE_TOO_LONG')
    secret_free(result)
    return result


def source_snapshot(folder: Path) -> tuple[list[Path], dict, str]:
    if folder.is_symlink():
        raise Blocked('SYMLINK_PRODUCT_FOLDER')
    photos = sorted([p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS], key=lambda p: p.name)
    if any(p.is_symlink() or not p.is_file() for p in photos):
        raise Blocked('INVALID_SOURCE_PHOTO')
    if len(photos) > 50:
        raise Blocked('MORE_THAN_50_PHOTOS_IN_ONE_PRODUCT')
    for p in photos:
        inside(folder, p.name)
        if p.stat().st_size > 60_000_000:
            raise Blocked('SOURCE_PHOTO_TOO_LARGE')
    data = metadata(folder)
    fingerprint = digest({'metadata': data, 'photos': [{'name': p.name, 'sha256': file_hash(p)} for p in photos]})
    return photos, data, fingerprint


def convert_photo(source: Path, destination: Path, thumbnail: Path) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(source) as opened:
            opened.verify()
        with Image.open(source) as opened:
            im = ImageOps.exif_transpose(opened)
            icc = im.info.get('icc_profile')
            if icc:
                source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                im = ImageCms.profileToProfile(im, source_profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
            else:
                if im.mode in ('RGBA', 'LA'):
                    bg = Image.new('RGBA', im.size, 'white')
                    im = Image.alpha_composite(bg, im.convert('RGBA'))
                im = im.convert('RGB')
            w, h = im.size
            # Diagnostics are advisory; never infer mineral, item colour, or quality from global pixels.
            sample = im.copy()
            sample.thumbnail((160, 160))
            brightness = sum(ImageStat.Stat(sample).mean) / 3
            canvas = Image.new('RGB', (1080, 1350), 'white')
            fit = ImageOps.contain(im, canvas.size, Image.Resampling.LANCZOS)
            canvas.paste(fit, ((1080 - fit.width) // 2, (1350 - fit.height) // 2))
            destination.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(destination, format='JPEG', quality=95, subsampling=0)
            thumb = canvas.copy()
            thumb.thumbnail((324, 405))
            thumb.save(thumbnail, format='JPEG', quality=88)
    return {'original_width': w, 'original_height': h, 'width': 1080, 'height': 1350,
            'format': 'JPEG', 'average_brightness_diagnostic_only': round(brightness, 1),
            'technical_warning': 'LOW_RESOLUTION' if min(w, h) < 600 else None,
            'operations': ['exif_orientation', 'icc_to_srgb_if_present', 'resize_contain', 'white_padding', 'jpeg_export'],
            'colour_enhancement': False, 'ai_redraw': False}


def ingest_one(content: Path, folder: Path, brand: str) -> dict:
    folder_id = valid_id(folder.name)
    content_id = valid_id(f'{brand}-{folder_id}')
    dest = item_dir(content, content_id)
    prior = read_json(dest / 'item.json')
    photos, provided, source_hash = source_snapshot(folder)
    if prior and prior['input_hash'] == source_hash:
        return prior
    if prior and prior['status'] in ('PUBLISHING', 'PUBLISHED', 'MANUAL_ACTION_REQUIRED'):
        raise Blocked('IMMUTABLE_OR_UNCERTAIN_PRODUCT')
    dest.mkdir(parents=True, exist_ok=True)
    if prior:
        revision = dest / 'revisions' / prior['input_hash']
        revision.mkdir(parents=True, exist_ok=True)
        for old in dest.iterdir():
            if old.is_file() and not (revision / old.name).exists():
                shutil.copy2(old, revision / old.name)
    records, duplicates, issues, seen = [], [], [], {}
    for photo in photos:
        sha = file_hash(photo)
        if sha in seen:
            duplicates.append({'file': photo.name, 'same_as': seen[sha]})
            continue
        seen[sha] = photo.name
        photo_id = 'p-' + sha[:24]
        original = dest / 'originals' / sha / photo.name
        original.parent.mkdir(parents=True, exist_ok=True)
        if not original.exists():
            shutil.copy2(photo, original)
        if file_hash(original) != sha:
            raise Blocked('ORIGINAL_HASH_MISMATCH')
        processed = dest / 'processed' / f'{photo_id}.jpg'
        thumb = dest / 'processed' / f'{photo_id}-thumb.jpg'
        try:
            if processed.exists() and thumb.exists():
                # Source is immutable but output format policy may change; validate again on new input.
                facts = convert_photo(original, processed, thumb)
            else:
                facts = convert_photo(original, processed, thumb)
            records.append({'photo_id': photo_id, 'source_name': photo.name, 'source_sha256': sha,
                            'original_path': original.relative_to(dest).as_posix(),
                            'processed_path': processed.relative_to(dest).as_posix(),
                            'thumbnail_path': thumb.relative_to(dest).as_posix(),
                            'processed_sha256': file_hash(processed), **facts})
        except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            issues.append({'file': photo.name, 'code': 'UNREADABLE_IMAGE', 'action': '請補一張清楚的 JPEG/PNG；HEIC 請先匯出 JPEG。'})
    if not records:
        issues.append({'file': folder.name, 'code': 'NO_USABLE_PHOTOS', 'action': '每條商品資料夾至少放一張實際商品照片。'})
    item = {'schema_version': 1, 'brand': brand, 'content_id': content_id,
            'source_folder': f'inbox/{folder_id}', 'input_hash': source_hash,
            'user_provided': provided, 'photos': records, 'duplicates_removed': duplicates,
            'issues': issues, 'created_at': (prior or {}).get('created_at', now()), 'updated_at': now(),
            'status': 'NEEDS_INFO' if issues else 'DRAFT', 'publish_at': (prior or {}).get('publish_at')}
    save_json(dest / 'item.json', item)
    return item


def ingest(content: Path, brand: str) -> list[dict]:
    inbox = content / 'inbox'
    inbox.mkdir(parents=True, exist_ok=True)
    results = []
    for folder in sorted(inbox.iterdir()):
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        try:
            results.append(ingest_one(content, folder, brand))
        except Blocked as error:
            results.append({'brand': brand, 'source_folder': folder.name, 'status': 'NEEDS_INFO', 'error': error.code})
    save_json(content / 'ingest-report.json', {'checked_at': now(), 'items': results})
    return results

