"""One-time account binding using the existing Meta App. No token is printed."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlencode

import yaml

from .core import REPO, Blocked, atomic_bytes, brand_config, save_json
from .network import Transport, MetaClient


def bind(expected_username: str, workspace: Path, repo=REPO, transport=None):
    config = brand_config('baobao', repo)
    user_token = os.environ.get('BAOBAO_SETUP_USER_TOKEN', '')
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
        exchanged = net.json('GET', root + 'oauth/access_token?' + urlencode({
            'grant_type': 'fb_exchange_token', 'client_id': config['meta_app_id'],
            'client_secret': app_secret, 'fb_exchange_token': user_token}))
        user_token = exchanged.get('access_token', '')
        if not user_token:
            raise Blocked('LONG_LIVED_TOKEN_EXCHANGE_FAILED', manual=True)
    permission_response = net.json('GET', root + 'me/permissions', headers={'Authorization': 'Bearer ' + user_token})
    granted = {p.get('permission') for p in permission_response.get('data', []) if p.get('status') == 'granted'}
    required = {'pages_show_list', 'pages_read_engagement', 'instagram_basic', 'instagram_content_publish'}
    if not required <= granted:
        raise Blocked('META_REQUIRED_PERMISSIONS_NOT_GRANTED', manual=True)
    pages = net.json('GET', root + 'me/accounts?' + urlencode({'fields': 'id,name,access_token,instagram_business_account{id,username}', 'limit': 100}),
                     headers={'Authorization': 'Bearer ' + user_token})
    candidates = [p for p in pages.get('data', []) if p.get('instagram_business_account', {}).get('username', '').casefold() == expected_username.casefold()]
    if len(candidates) != 1:
        raise Blocked('BAOBAO_NOT_IN_AUTHORIZED_PAGES', manual=True)
    page = candidates[0]
    target = {'instagram_user_id': str(page['instagram_business_account']['id']),
              'facebook_page_id': str(page['id']), 'username': page['instagram_business_account']['username']}
    other = brand_config('maiocha', repo)['target']
    if any(target[k].casefold() == other[k].casefold() for k in target):
        raise Blocked('CROSS_BRAND_ACCOUNT')
    creds = dict(target, token=page.get('access_token', ''))
    if not creds['token']:
        raise Blocked('PAGE_TOKEN_NOT_GRANTED', manual=True)
    config['target'] = target
    verified = MetaClient(config, creds, net).verify_account()
    verified['granted_permissions'] = sorted(required)
    # Persist only after a live Page→IG and username check.
    destination = workspace / 'content/baobao/.env'
    text = '\n'.join(config['env'][k] + '=' + str(v) for k, v in creds.items()) + '\n'
    atomic_bytes(destination, text.encode('utf-8'))
    atomic_bytes(repo / 'config/brands/baobao.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode('utf-8'))
    save_json(workspace / 'content/baobao/account-verification.json', verified)
    return verified


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--username', required=True)
    p.add_argument('--workspace', type=Path, required=True)
    args = p.parse_args()
    try:
        import json
        print(json.dumps(bind(args.username, args.workspace), ensure_ascii=False))
    except Blocked as error:
        print(error.code)
        raise SystemExit(2)
    except Exception:
        print('ACCOUNT_BINDING_FAILED_NO_CREDENTIALS_EXPOSED')
        raise SystemExit(3)
