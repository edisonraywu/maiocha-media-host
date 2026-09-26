"""One-time account binding using the existing Meta App. No token is printed."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlencode

import yaml

from .core import REPO, Blocked, atomic_bytes, brand_config, now, save_json
from .network import Transport, MetaClient


REQUIRED_PERMISSIONS = {'pages_show_list', 'pages_read_engagement', 'instagram_basic', 'instagram_content_publish'}


def authorized_pages(net, root, user_token, diagnostics):
    """Follow bounded cursors on our own Graph URL, never a token-bearing next URL."""
    params = {'fields': 'id,name,access_token,instagram_business_account', 'limit': 100}
    pages, seen_ids, seen_cursors = [], set(), set()
    for batch in range(10):
        response = net.json('GET', root + 'me/accounts?' + urlencode(params),
                            headers={'Authorization': 'Bearer ' + user_token})
        data = response.get('data')
        if not isinstance(data, list) or any(not isinstance(p, dict) for p in data):
            raise Blocked('INVALID_AUTHORIZED_PAGES_RESPONSE')
        for page in data:
            page_id = str(page.get('id', ''))
            if not page_id.isascii() or not page_id.isdigit():
                raise Blocked('INVALID_FACEBOOK_PAGE_ID')
            if page_id not in seen_ids:
                seen_ids.add(page_id)
                pages.append(page)
        paging = response.get('paging') or {}
        diagnostics.update(page_batches=batch + 1, authorized_page_count=len(pages), has_more_pages=bool(paging.get('next')))
        diagnostics['visible_pages'] = [
            {'facebook_page_id': str(p['id']), 'name': p.get('name'),
             'instagram_user_id': (p.get('instagram_business_account') or {}).get('id')}
            for p in pages]
        if not paging.get('next'):
            return pages
        cursor = (paging.get('cursors') or {}).get('after')
        if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
            raise Blocked('AUTHORIZED_PAGES_PAGINATION_INVALID')
        seen_cursors.add(cursor)
        params['after'] = cursor
    raise Blocked('AUTHORIZED_PAGES_PAGINATION_LIMIT')


def directly_granted_pages(net, root, user_token, diagnostics, excluded_page_id):
    """Use only Page IDs returned by this token's live grants when enumeration is empty."""
    grant_sets = {}
    for grant in diagnostics.get('granular_asset_grants', []):
        grant_sets.setdefault(grant['scope'], set()).update(grant['target_ids'])
    ids = (grant_sets.get('pages_show_list', set()) & grant_sets.get('pages_read_engagement', set())) - {excluded_page_id}
    if len(ids) > 10:
        raise Blocked('GRANTED_PAGE_LOOKUP_LIMIT', manual=True)
    diagnostics['stage'] = 'READ_EXPLICITLY_GRANTED_PAGES'
    diagnostics['direct_granted_page_lookups'] = []
    pages = []
    for page_id in sorted(ids):
        page = net.json('GET', root + page_id + '?' + urlencode({'fields': 'id,name,access_token,instagram_business_account'}),
                        headers={'Authorization': 'Bearer ' + user_token})
        if str(page.get('id')) != page_id:
            raise Blocked('GRANTED_PAGE_ID_MISMATCH')
        diagnostics['direct_granted_page_lookups'].append({
            'facebook_page_id': page_id, 'name': page.get('name'),
            'instagram_user_id': (page.get('instagram_business_account') or {}).get('id'),
            'page_token_available': bool(page.get('access_token'))})
        pages.append(page)
    return pages


def bind(expected_username: str, workspace: Path, repo=REPO, transport=None, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics['stage'] = 'CHECK_INPUT'
    config = brand_config('baobao', repo)
    user_token = os.environ.get('BAOBAO_SETUP_USER_TOKEN', '').strip()
    if not user_token:
        raise Blocked('USER_AUTHORIZATION_REQUIRED', manual=True)
    expected_username = expected_username.lstrip('@').strip()
    if not expected_username or expected_username.casefold() == 'maiocha.lab':
        raise Blocked('BAOBAO_USERNAME_REQUIRED')
    net = transport or Transport()
    root = 'https://graph.facebook.com/' + config['api_version'] + '/'
    # Exchange against the existing App to prove the new authorization belongs to that App.
    app_secret = os.environ.get('BAOBAO_SETUP_APP_SECRET')
    if not app_secret:
        raise Blocked('EXISTING_META_APP_SECRET_REQUIRED', manual=True)
    if app_secret:
        diagnostics['stage'] = 'SAME_APP_TOKEN_EXCHANGE'
        exchanged = net.json('GET', root + 'oauth/access_token?' + urlencode({
            'grant_type': 'fb_exchange_token', 'client_id': config['meta_app_id'],
            'client_secret': app_secret, 'fb_exchange_token': user_token}))
        user_token = exchanged.get('access_token', '')
        if not user_token:
            raise Blocked('LONG_LIVED_TOKEN_EXCHANGE_FAILED', manual=True)
    diagnostics['stage'] = 'VERIFY_TOKEN_APP_AND_ASSET_GRANTS'
    debug = net.json('GET', root + 'debug_token?' + urlencode({'input_token': user_token}),
                     headers={'Authorization': 'Bearer ' + config['meta_app_id'] + '|' + app_secret}).get('data', {})
    diagnostics['token_valid'] = debug.get('is_valid') is True
    diagnostics['token_app_id'] = debug.get('app_id')
    diagnostics['token_type'] = debug.get('type')
    for field in ('expires_at', 'data_access_expires_at'):
        if type(debug.get(field)) is int:
            diagnostics[field] = debug[field]
    if debug.get('is_valid') is not True:
        raise Blocked('META_USER_TOKEN_INVALID', manual=True)
    if str(debug.get('app_id')) != config['meta_app_id']:
        raise Blocked('META_APP_ID_MISMATCH', manual=True)
    if debug.get('type') != 'USER':
        raise Blocked('META_USER_TOKEN_REQUIRED', manual=True)
    diagnostics['granular_asset_grants'] = [
        {'scope': entry['scope'], 'target_ids': [str(v) for v in entry.get('target_ids', []) if str(v).isascii() and str(v).isdigit()]}
        for entry in debug.get('granular_scopes', [])
        if isinstance(entry, dict) and entry.get('scope') in REQUIRED_PERMISSIONS]
    diagnostics['stage'] = 'VERIFY_USER_PERMISSIONS'
    permission_response = net.json('GET', root + 'me/permissions', headers={'Authorization': 'Bearer ' + user_token})
    granted = {p.get('permission') for p in permission_response.get('data', []) if p.get('status') == 'granted'}
    required = REQUIRED_PERMISSIONS
    diagnostics['granted_required_permissions'] = sorted(required & granted)
    diagnostics['missing_permissions'] = sorted(required - granted)
    diagnostics['business_management_granted'] = 'business_management' in granted
    if not required <= granted:
        raise Blocked('META_REQUIRED_PERMISSIONS_NOT_GRANTED', manual=True)
    diagnostics['stage'] = 'LIST_AUTHORIZED_PAGES'
    pages = authorized_pages(net, root, user_token, diagnostics)
    diagnostics['stage'] = 'MATCH_TARGET_PAGE'
    expected_page = config.get('expected_facebook_page_name')
    if not expected_page:
        raise Blocked('EXPECTED_FACEBOOK_PAGE_NAME_REQUIRED', manual=True)
    candidates = [p for p in pages if p.get('name') == expected_page]
    if not candidates:
        other_page_id = brand_config('maiocha', repo)['target']['facebook_page_id']
        direct_pages = directly_granted_pages(net, root, user_token, diagnostics, other_page_id)
        candidates = [p for p in direct_pages if p.get('name') == expected_page]
        diagnostics['discovery_method'] = 'EXPLICIT_TOKEN_ASSET_GRANTS'
    else:
        diagnostics['discovery_method'] = 'ME_ACCOUNTS'
    diagnostics['stage'] = 'MATCH_TARGET_PAGE'
    if not candidates:
        raise Blocked('BAOBAO_PAGE_NOT_IN_AUTHORIZED_PAGES', manual=True)
    if len(candidates) != 1:
        raise Blocked('AMBIGUOUS_BAOBAO_FACEBOOK_PAGE', manual=True)
    page = candidates[0]
    page_token = page.get('access_token', '')
    if not page_token:
        raise Blocked('PAGE_TOKEN_NOT_GRANTED', manual=True)
    diagnostics['stage'] = 'READ_TARGET_PAGE_LINK'
    headers = {'Authorization': 'Bearer ' + page_token}
    live_page = net.json('GET', root + str(page['id']) + '?' + urlencode({'fields': 'id,name,instagram_business_account'}), headers=headers)
    if str(live_page.get('id')) != str(page['id']) or live_page.get('name') != expected_page:
        raise Blocked('BAOBAO_FACEBOOK_PAGE_NAME_MISMATCH', manual=True)
    ig_id = str((live_page.get('instagram_business_account') or {}).get('id', ''))
    if not ig_id:
        raise Blocked('BAOBAO_LINKED_PROFESSIONAL_IG_NOT_VISIBLE', manual=True)
    if not ig_id.isascii() or not ig_id.isdigit():
        raise Blocked('INVALID_INSTAGRAM_ACCOUNT_ID')
    diagnostics['stage'] = 'READ_TARGET_IG_USERNAME'
    ig = net.json('GET', root + ig_id + '?' + urlencode({'fields': 'id,username'}), headers=headers)
    diagnostics['candidate_account'] = {'facebook_page_id': str(page['id']), 'facebook_page_name': expected_page,
                                        'instagram_user_id': str(ig.get('id')), 'username': ig.get('username')}
    if str(ig.get('id')) != ig_id or str(ig.get('username', '')).casefold() != expected_username.casefold():
        raise Blocked('BAOBAO_IG_USERNAME_MISMATCH', manual=True)
    for scope, asset_id in [('pages_show_list', str(page['id'])), ('pages_read_engagement', str(page['id'])),
                            ('instagram_basic', ig_id), ('instagram_content_publish', ig_id)]:
        scoped_grants = [g for g in diagnostics['granular_asset_grants'] if g['scope'] == scope]
        if scoped_grants and asset_id not in {v for g in scoped_grants for v in g['target_ids']}:
            raise Blocked('BAOBAO_ASSET_PERMISSION_MISMATCH', manual=True)
    target = {'instagram_user_id': ig_id, 'facebook_page_id': str(page['id']), 'username': ig['username']}
    other = brand_config('maiocha', repo)['target']
    if any(target[k].casefold() == other[k].casefold() for k in target):
        raise Blocked('CROSS_BRAND_ACCOUNT')
    creds = dict(target, token=page_token)
    config['target'] = target
    diagnostics['stage'] = 'VERIFY_PAGE_IG_IDENTITY'
    verified = MetaClient(config, creds, net).verify_account()
    verified['granted_permissions'] = sorted(required)
    # Persist only after a live Page→IG and username check.
    diagnostics['stage'] = 'SAVE_VERIFIED_ACCOUNT'
    destination = workspace / 'content/baobao/.env'
    text = '\n'.join(config['env'][k] + '=' + str(v) for k, v in creds.items()) + '\n'
    atomic_bytes(destination, text.encode('utf-8'))
    atomic_bytes(repo / 'config/brands/baobao.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode('utf-8'))
    save_json(workspace / 'content/baobao/account-verification.json', verified)
    diagnostics['stage'] = 'COMPLETE'
    return verified


def connect_and_report(expected_username: str, workspace: Path, repo=REPO, transport=None):
    """Persist controlled diagnostics, never credentials, API messages or request URLs."""
    report = {'brand': 'baobao', 'expected_username': expected_username, 'checked_at': now()}
    try:
        verified = bind(expected_username, workspace, repo, transport, report)
        report.update(result='PASS', account=verified)
        return verified
    except Blocked as error:
        report.update(result='FAIL', error_code=error.code)
        for field in ('http_status', 'provider_code', 'provider_subcode'):
            value = getattr(error, field, None)
            if type(value) is int:
                report[field] = value
        raise
    except Exception:
        report.update(result='FAIL', error_code='ACCOUNT_BINDING_FAILED_NO_CREDENTIALS_EXPOSED')
        raise
    finally:
        save_json(workspace / '.local/baobao-connect-result.json', report)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--username', required=True)
    p.add_argument('--workspace', type=Path, required=True)
    args = p.parse_args()
    try:
        import json
        print(json.dumps(connect_and_report(args.username, args.workspace), ensure_ascii=False))
    except Blocked as error:
        print(error.code)
        raise SystemExit(2)
    except Exception:
        print('ACCOUNT_BINDING_FAILED_NO_CREDENTIALS_EXPOSED')
        raise SystemExit(3)
