"""Provision only the four verified baobao values, sealed with GitHub's repository public key."""
from base64 import b64encode
import os
from nacl import encoding, public

from .core import Blocked, credentials, now
from .network import MetaClient, Transport

NAMES = frozenset({'BAOBAO_IG_USER_ID', 'BAOBAO_PAGE_ID', 'BAOBAO_IG_USERNAME', 'BAOBAO_PAGE_ACCESS_TOKEN'})


def sync_secrets(config, transport=None, meta=None):
    if config['brand'] != 'baobao' or config['hosting']['repository'] != 'edisonraywu/maiocha-media-host' or set(config['env'].values()) != NAMES:
        raise Blocked('SECRET_DESTINATION_MISMATCH')
    creds = credentials(config)
    verified = (meta or MetaClient(config, creds)).verify_account()
    gh_token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not gh_token:
        raise Blocked('MISSING_GITHUB_STATE_CREDENTIAL', manual=True)
    net = transport or Transport()
    base = 'https://api.github.com/repos/' + config['hosting']['repository'] + '/actions/secrets'
    headers = {'Authorization': 'Bearer ' + gh_token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    key = net.json('GET', base + '/public-key', headers=headers)
    box = public.SealedBox(public.PublicKey(key['key'].encode('ascii'), encoding.Base64Encoder()))
    names = []
    for field, name in config['env'].items():
        encrypted = b64encode(box.encrypt(creds[field].encode('utf-8'))).decode('ascii')
        # GitHub returns no body on an update; never try to parse it as JSON.
        net.request('PUT', base + '/' + name, headers=headers, body={'encrypted_value': encrypted, 'key_id': key['key_id']})
        confirmation = net.json('GET', base + '/' + name, headers=headers)
        if confirmation.get('name') != name:
            raise Blocked('GITHUB_SECRET_WRITE_NOT_CONFIRMED', manual=True)
        names.append(name)
    return {'result': 'PASS', 'secret_names': sorted(names), 'account': verified, 'checked_at': now(), 'values_logged': False}
