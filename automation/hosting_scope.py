"""Canonical public path checks used before staging and before publishing."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from .core import Blocked, BRANDS, valid_id


def canonical_key(value: str) -> str:
    if not isinstance(value, str) or not value or re.search(r'[\x00-\x1f\x7f?#:]', value):
        raise Blocked('HOSTING_INVALID_OBJECT_KEY')
    decoded = value
    for _ in range(5):
        if '%' not in decoded:
            break
        if re.search(r'%(?![0-9a-fA-F]{2})', decoded):
            raise Blocked('HOSTING_INVALID_ENCODING')
        fresh = unquote(decoded, errors='strict')
        if fresh == decoded:
            raise Blocked('HOSTING_INVALID_ENCODING')
        decoded = fresh
    if re.search(r'[%\x00-\x1f\x7f?#:]', decoded):
        raise Blocked('HOSTING_INVALID_OBJECT_KEY')
    parts = []
    for part in decoded.replace('\\', '/').split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise Blocked('HOSTING_PATH_TRAVERSAL')
            parts.pop()
            continue
        if re.search(r'[<>"|*]', part) or part.rstrip(' .') != part or re.match(r'(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part):
            raise Blocked('HOSTING_INVALID_PATH_SEGMENT')
        parts.append(part)
    if not parts:
        raise Blocked('HOSTING_EMPTY_OBJECT_KEY')
    return '/'.join(parts)


def scoped_key(key: str, namespace: str, *, allow_root=False) -> str:
    result = canonical_key(key)
    parts, allowed = result.split('/'), canonical_key(namespace).split('/')
    if parts[:len(allowed)] != allowed or len(parts) < len(allowed) or (not allow_root and len(parts) == len(allowed)):
        raise Blocked('HOSTING_NAMESPACE_MISMATCH')
    return result


def public_asset_key(config: dict, cid: str, key: str, url: str | None = None) -> str:
    brand = config.get('brand')
    if brand not in BRANDS or not valid_id(cid).startswith(brand + '-') or config['hosting']['namespace'] != f'media/{brand}':
        raise Blocked('HOSTING_BRAND_CONTEXT_MISMATCH')
    result = scoped_key(key, f'media/{brand}/{cid}')
    # Releases are produced with canonical paths; ambiguous alternate spellings are not release identities.
    if result != key:
        raise Blocked('HOSTING_NONCANONICAL_RELEASE_PATH')
    if url is not None:
        expected = config['hosting']['base_url'].rstrip('/') + '/' + result
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.query or parts.fragment or parts.username or url != expected:
            raise Blocked('HOSTING_URL_OBJECT_IDENTITY_MISMATCH')
    return result
