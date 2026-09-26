from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
BRANDS = frozenset({'baobao', 'maiocha'})
STATES = frozenset({'DRAFT', 'PREPARED', 'NEEDS_INFO', 'READY', 'READY_FOR_REVIEW', 'APPROVED', 'SCHEDULED', 'PUBLISHING',
                    'PUBLISHED', 'FAILED', 'MANUAL_ACTION_REQUIRED', 'CANCELLED'})
PRODUCT_FIELDS = ('product_name', 'crystal_name', 'price', 'bead_size', 'stock', 'sku', 'notes')
ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$')
SECRET_RE = re.compile(r'(EAA[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]+|sk-[A-Za-z0-9_-]{20,})')


class Blocked(Exception):
    """Only controlled, secret-free error codes cross the CLI/report boundary."""
    def __init__(self, code: str, manual: bool = False):
        self.code, self.manual = code, manual
        super().__init__(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8') + b'\n')


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError):
        raise Blocked('CORRUPT_JSON') from None


def read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, OSError, yaml.YAMLError):
        raise Blocked('INVALID_YAML') from None


def valid_id(value: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise Blocked('INVALID_CONTENT_ID')
    return value


def inside(root: Path, relative: str | Path) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise Blocked('PATH_OUTSIDE_NAMESPACE')
    # Resolving symbolic links must not permit a shortcut across product folders.
    return candidate


def brand_config(brand: str, repo: Path = REPO) -> dict:
    if brand not in BRANDS:
        raise Blocked('UNKNOWN_BRAND')
    data = read_yaml(repo / 'config' / 'brands' / f'{brand}.yaml')
    if data.get('brand') != brand or data.get('hosting', {}).get('namespace') != f'media/{brand}':
        raise Blocked('BRAND_CONFIG_MISMATCH')
    if brand == 'baobao' and (data.get('approval_mode') is not True or data.get('auto_publish_without_approval', False) is not False):
        raise Blocked('BAOBAO_REQUIRES_EXPLICIT_MANUAL_APPROVAL')
    other = read_yaml(repo / 'config' / 'brands' / f'{"maiocha" if brand == "baobao" else "baobao"}.yaml')
    for key in ('instagram_user_id', 'facebook_page_id', 'username'):
        value = data['target'].get(key)
        if value and str(value).lower() == str(other['target'].get(key)).lower():
            raise Blocked('CROSS_BRAND_ACCOUNT')
    return data


def load_env(path: Path) -> None:
    """Explicit per-brand .env only; existing process settings take precedence."""
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if sep and re.fullmatch(r'[A-Z][A-Z0-9_]*', key.strip()):
            os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def credentials(config: dict) -> dict:
    result = {}
    for key, name in config['env'].items():
        value = os.environ.get(name, '').strip()
        if not value:
            raise Blocked(f'MISSING_{name}', manual=True)
        result[key] = value
    for key in ('instagram_user_id', 'facebook_page_id', 'username'):
        pinned = config['target'].get(key)
        if not pinned:
            raise Blocked('TARGET_NOT_PINNED', manual=True)
        if result[key].casefold() != str(pinned).casefold():
            raise Blocked('ACCOUNT_CONFIG_MISMATCH')
    return result


def parse_time(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp
    except (AttributeError, ValueError):
        raise Blocked('SCHEDULE_REQUIRES_TIMEZONE') from None


def secret_free(value: Any) -> None:
    if SECRET_RE.search(json.dumps(value, ensure_ascii=False)):
        raise Blocked('SECRET_IN_CONTENT')


@contextlib.contextmanager
def local_lock(root: Path):
    """An OS-held lock releases on process exit; never delete another process's lock."""
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / '.pipeline.lock').open('a+b')
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stream.close()
            raise Blocked('ANOTHER_PREPARE_IS_RUNNING') from None
    else:
        import fcntl
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise Blocked('ANOTHER_PREPARE_IS_RUNNING') from None
    try:
        yield
    finally:
        stream.close()


def item_dir(content: Path, content_id: str) -> Path:
    return inside(content / 'items', valid_id(content_id))


def item_files(content: Path):
    return sorted((content / 'items').glob('*/item.json'))


def cancel_approval(item: dict) -> None:
    item.pop('approval', None)
    item.pop('release_hash', None)
    item['status'] = 'DRAFT'
    item['updated_at'] = now()
