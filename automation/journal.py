from __future__ import annotations

import base64
import copy
import json
import os
import uuid
from pathlib import Path
from urllib.parse import quote

from .core import Blocked, digest, now, read_json, save_json


def assert_release_journal_brand(state, release):
    if state.get('brand') != release.get('brand') or not str(release.get('content_id', '')).startswith(state['brand'] + '-'):
        raise Blocked('JOURNAL_RELEASE_BRAND_MISMATCH')


def assert_journal_records(state):
    brand = state['brand']
    for cid, entry in state['items'].items():
        if entry.get('brand') != brand or entry.get('content_id') != cid or not cid.startswith(brand + '-'):
            raise Blocked('JOURNAL_CROSS_BRAND_RECORD')
    for entry in state['history']:
        if entry.get('brand') != brand or not str(entry.get('content_id', '')).startswith(brand + '-'):
            raise Blocked('JOURNAL_CROSS_BRAND_RECORD')
    if any(not cid.startswith(brand + '-') for cid in state.get('queue', {})):
        raise Blocked('JOURNAL_CROSS_BRAND_RECORD')
from .network import ApiFailure, Transport


def initial_state(brand: str):
    return {'schema_version': 1, 'brand': brand, 'paused': True, 'production_ready': False,
            'test_verification': None, 'items': {}, 'history': [], 'queue': {}, 'operation_id': None}


class GitHubJournal:
    """The same remote CAS journal is mandatory for local and Actions publishing."""
    def __init__(self, config: dict, token=None, transport=None):
        self.brand = config['brand']
        self.repo = config['hosting']['repository']
        self.branch = config['publishing']['journal_branch']
        self.token = token or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not self.token:
            raise Blocked('MISSING_GITHUB_STATE_CREDENTIAL', manual=True)
        self.transport = transport or Transport()
        self.base = 'https://api.github.com/repos/' + self.repo
        self.path = f'state/{self.brand}.json'
        self.headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}

    def initialize(self):
        try:
            self.transport.json('GET', self.base + '/git/ref/heads/' + quote(self.branch), headers=self.headers)
        except ApiFailure as error:
            if error.http_status != 404:
                raise
            main = self.transport.json('GET', self.base + '/git/ref/heads/main', headers=self.headers)
            try:
                self.transport.json('POST', self.base + '/git/refs', headers=self.headers,
                                    body={'ref': 'refs/heads/' + self.branch, 'sha': main['object']['sha']})
            except ApiFailure:
                # Read-only reconciliation: do not retry a possibly successful POST.
                self.transport.json('GET', self.base + '/git/ref/heads/' + quote(self.branch), headers=self.headers)
        try:
            self.read()
        except ApiFailure as error:
            if error.http_status != 404:
                raise
            self.write(initial_state(self.brand), None)

    def read(self):
        response = self.transport.json('GET', self.base + '/contents/' + self.path + '?ref=' + quote(self.branch), headers=self.headers)
        try:
            state = json.loads(base64.b64decode(response['content']))
        except (KeyError, ValueError):
            raise Blocked('CORRUPT_PUBLISH_HISTORY') from None
        if state.get('brand') != self.brand or state.get('schema_version') != 1 or not isinstance(state.get('items'), dict) or not isinstance(state.get('history'), list):
            raise Blocked('JOURNAL_BRAND_OR_SCHEMA_MISMATCH')
        assert_journal_records(state)
        return state, response['sha']

    def write(self, state: dict, sha: str | None):
        if state.get('brand') != self.brand:
            raise Blocked('JOURNAL_BRAND_OR_SCHEMA_MISMATCH')
        assert_journal_records(state)
        state['operation_id'] = uuid.uuid4().hex
        body = {'message': 'Update ' + self.brand + ' publication journal [skip ci]', 'branch': self.branch,
                'content': base64.b64encode(json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8')).decode('ascii')}
        if sha:
            body['sha'] = sha
        try:
            self.transport.json('PUT', self.base + '/contents/' + self.path, headers=self.headers, body=body)
        except ApiFailure as error:
            if error.http_status in (409, 422):
                raise Blocked('JOURNAL_CONCURRENT_CHANGE') from None
            # A lost successful PUT is safely recognizable by our unique operation ID.
            latest, _ = self.read()
            if latest.get('operation_id') != state['operation_id']:
                raise Blocked('JOURNAL_WRITE_UNCONFIRMED', manual=True) from None

    def mutate(self, change):
        state, sha = self.read()
        change(state)
        self.write(state, sha)
        return state


class LocalTestJournal:
    """Test double only. Production CLI cannot select this implementation."""
    def __init__(self, brand='baobao'):
        self.state = initial_state(brand)

    def read(self):
        return copy.deepcopy(self.state), digest(self.state)

    def write(self, state, sha):
        if sha != digest(self.state):
            raise Blocked('JOURNAL_CONCURRENT_CHANGE')
        self.state = copy.deepcopy(state)

    def mutate(self, change):
        state, sha = self.read()
        change(state)
        self.write(state, sha)
        return state


def claim(journal, release: dict, test_only=False, force=False, due=False) -> str:
    from .release import require_approved_release
    require_approved_release(release)
    owner = uuid.uuid4().hex
    cid = release['content_id']
    def change(state):
        assert_release_journal_brand(state, release)
        if state['paused']:
            raise Blocked('PUBLISHING_PAUSED')
        if not test_only and not state['production_ready']:
            raise Blocked('LIVE_TEST_NOT_VERIFIED', manual=True)
        if due and state.get('queue', {}).get(cid, {}).get('release_hash') != release['release_hash']:
            raise Blocked('SCHEDULE_REVOKED_BEFORE_CLAIM')
        existing = state['items'].get(cid)
        if existing:
            if existing['status'] == 'PUBLISHED' and force:
                state['history'].append(copy.deepcopy(existing))
            else:
                raise Blocked('ALREADY_PUBLISHED' if existing['status'] == 'PUBLISHED' else 'UNRESOLVED_PUBLISH_ATTEMPT', manual=True)
        if not force and any(x.get('content_id') == cid and x.get('status') == 'PUBLISHED' for x in state['history']):
            raise Blocked('ALREADY_PUBLISHED')
        # A renamed folder may not republish the same exact source asset automatically.
        sources = set(release['source_asset_hashes'])
        if not force and any(x.get('status') not in ('RETRIED', 'CANCELLED') and sources & set(x.get('source_asset_hashes', [])) for x in list(state['items'].values()) + state['history']):
            raise Blocked('SOURCE_ASSET_ALREADY_USED')
        state['items'][cid] = {'content_id': cid, 'brand': release['brand'], 'status': 'PUBLISHING',
                               'owner': owner, 'started_at': now(), 'target': release['target'],
                               'release_hash': release['release_hash'], 'caption_hash': release['caption_sha256'],
                               'asset_hashes': [a['sha256'] for a in release['assets']],
                               'source_asset_hashes': release['source_asset_hashes'],
                               'is_test': test_only, 'stage': 'CLAIMED', 'containers': [], 'publish_intent': False}
    journal.mutate(change)
    return owner


def update_attempt(journal, cid, owner, **values):
    def change(state):
        entry = state['items'].get(cid, {})
        if entry.get('owner') != owner or entry.get('status') == 'PUBLISHED':
            raise Blocked('PUBLISH_LEASE_MISMATCH')
        entry.update(values)
        entry['updated_at'] = now()
    return journal.mutate(change)


def revoke_scheduled(journal, cid):
    def change(state):
        active = state['items'].get(cid)
        if active and active['status'] not in ('CANCELLED',):
            raise Blocked('ACTIVE_OR_PUBLISHED_ITEM_CANNOT_BE_REVISED', manual=True)
        state.setdefault('queue', {}).pop(cid, None)
    return journal.mutate(change)


def schedule_release(journal, release):
    from .release import require_approved_release
    require_approved_release(release)
    def change(state):
        assert_release_journal_brand(state, release)
        cid = release['content_id']
        if cid in state['items']:
            raise Blocked('EXISTING_PUBLICATION_ATTEMPT')
        state.setdefault('queue', {})[cid] = {'status': 'SCHEDULED', 'release_hash': release['release_hash'],
                                              'publish_at': release['publish_at'], 'scheduled_at': now()}
    return journal.mutate(change)
