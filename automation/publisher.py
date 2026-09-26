from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .core import Blocked, credentials, now, parse_time, save_json
from .journal import claim, update_attempt
from .network import ApiFailure, MetaClient, Transport
from .release import validate_release, verify_hosted


def preflight(repo: Path, release: dict, config: dict, journal, meta=None, transport=None, *, test_only=False, force=False, due=False) -> dict:
    checks, failures = {}, []
    manual = False
    def check(name, action):
        nonlocal manual
        try:
            value = action()
            checks[name] = True
            return value
        except Blocked as error:
            checks[name] = False
            failures.append({'check': name, 'code': error.code})
            manual |= error.manual
            return None
        except (OSError, KeyError, TypeError, ValueError):
            checks[name] = False
            failures.append({'check': name, 'code': 'INVALID_OR_MISSING_INPUT'})
            return None
    check('brand_manifest_assets_caption_qa', lambda: validate_release(repo, release, config))
    creds = check('credentials_match_pinned_target', lambda: credentials(config))
    def history():
        state, _ = journal.read()
        if state['brand'] != config['brand']:
            raise Blocked('JOURNAL_BRAND_MISMATCH')
        if state['paused'] or os.environ.get('PAUSE_ALL_' + config['brand'].upper() + '_PUBLISHING', '').lower() in ('true', '1', 'yes'):
            raise Blocked('PUBLISHING_PAUSED')
        if not test_only and (not state['production_ready'] or not state.get('test_verification') or state['test_verification'].get('target') != config['target']):
            raise Blocked('LIVE_TEST_NOT_VERIFIED', manual=True)
        old = state['items'].get(release['content_id'])
        if old and not (force and old['status'] == 'PUBLISHED'):
            raise Blocked('ALREADY_PUBLISHED' if old['status'] == 'PUBLISHED' else 'UNRESOLVED_PUBLISH_ATTEMPT', manual=True)
        queued = state.get('queue', {}).get(release['content_id'])
        if due and (not queued or queued.get('release_hash') != release['release_hash'] or queued.get('status') != 'SCHEDULED'):
            raise Blocked('RELEASE_NOT_IN_ACTIVE_SCHEDULE')
        if queued and queued.get('release_hash') != release['release_hash']:
            raise Blocked('STALE_RELEASE_REVOKED')
        if test_only and any(x.get('is_test') for x in state['items'].values()):
            raise Blocked('TEST_ALREADY_ATTEMPTED_USE_RECONCILE', manual=True)
        if not force:
            for entry in list(state['items'].values()) + state['history']:
                if entry.get('status') in ('RETRIED', 'CANCELLED'):
                    continue
                if entry.get('content_id') == release['content_id'] or set(entry.get('source_asset_hashes', [])) & set(release['source_asset_hashes']):
                    raise Blocked('DUPLICATE_PRODUCT_OR_ASSET')
        return state
    check('durable_history_pause_production', history)
    def schedule():
        stamp = parse_time(release['publish_at'])
        if due:
            elapsed = (datetime.now(timezone.utc) - stamp).total_seconds()
            if elapsed < 0:
                raise Blocked('NOT_DUE')
            if elapsed > config['posting'].get('max_lateness_hours', 24) * 3600:
                raise Blocked('SCHEDULE_TOO_OLD_REVIEW_REQUIRED', manual=True)
        if release['status'] not in ('APPROVED', 'SCHEDULED'):
            raise Blocked('ITEM_NOT_SCHEDULED_OR_APPROVED')
    check('schedule', schedule)
    if checks.get('brand_manifest_assets_caption_qa'):
        check('public_hosting', lambda: verify_hosted(release, transport or Transport()))
    else:
        checks['public_hosting'] = False
    if creds:
        check('live_page_ig_username_permissions', lambda: (meta or MetaClient(config, creds)).verify_account())
    else:
        checks['live_page_ig_username_permissions'] = False
    return {'brand': config['brand'], 'content_id': release.get('content_id'), 'checked_at': now(),
            'result': ('MANUAL_ACTION_REQUIRED' if manual else 'FAIL') if failures else 'PASS',
            'checks': checks, 'failures': failures, 'api_post_requests_sent': 0, 'is_test': test_only}


class Publisher:
    def __init__(self, repo, config, journal, meta=None, transport=None):
        self.repo, self.config, self.journal = repo, config, journal
        self.meta = meta
        self.transport = transport or Transport()

    def publish_feed(self, release, **kwargs):
        if release['content_type'] != 'SINGLE':
            raise Blocked('SINGLE_REQUIRED')
        return self.publish(release, **kwargs)

    def publish_carousel(self, release, **kwargs):
        if release['content_type'] != 'CAROUSEL':
            raise Blocked('CAROUSEL_REQUIRED')
        return self.publish(release, **kwargs)

    def publish_reel(self, release, **kwargs):
        # Stable legacy maiocha Reel implementation remains available via its original entry.
        raise Blocked('REEL_NOT_ENABLED_FOR_THIS_BRAND', manual=True)

    def publish_story(self, release, **kwargs):
        raise Blocked('STORY_REQUIRES_ACCOUNT_CAPABILITY_VALIDATION', manual=True)

    def publish(self, release, *, dry_run=False, test_only=False, force=False, due=False):
        if test_only and release['content_type'] != 'SINGLE':
            raise Blocked('FIRST_TEST_MUST_BE_ONE_FEED_IMAGE')
        report = preflight(self.repo, release, self.config, self.journal, self.meta, self.transport,
                           test_only=test_only, force=force, due=due)
        if dry_run:
            return report
        if report['result'] != 'PASS':
            raise Blocked('PREFLIGHT_' + report['result'], manual=report['result'] == 'MANUAL_ACTION_REQUIRED')
        meta = self.meta or MetaClient(self.config, credentials(self.config))
        caption = validate_release(self.repo, release, self.config)
        owner = claim(self.journal, release, test_only, force, due)
        cid, containers, publish_intent = release['content_id'], [], False
        def before_post(stage):
            # The journal write must be confirmed before the irreversible side effect.
            state, _ = self.journal.read()
            if state['paused'] or os.environ.get('PAUSE_ALL_' + self.config['brand'].upper() + '_PUBLISHING', '').lower() in ('true', '1', 'yes'):
                raise Blocked('PUBLISHING_PAUSED')
            update_attempt(self.journal, cid, owner, stage=stage, containers=list(containers))
        def create(fields):
            before_post('CREATE_CONTAINER_INTENT')
            result = meta.post('media', fields)
            creation_id = str(result.get('id', ''))
            if not creation_id.isdigit():
                raise Blocked('CONTAINER_RESPONSE_UNCERTAIN', manual=True)
            containers.append(creation_id)
            update_attempt(self.journal, cid, owner, stage='CONTAINER_CREATED', containers=list(containers))
            meta.wait_container(creation_id)
            return creation_id
        try:
            if release['content_type'] == 'SINGLE':
                parent = create({'image_url': release['assets'][0]['url'], 'caption': caption})
            elif release['content_type'] == 'CAROUSEL':
                children = [create({'image_url': a['url'], 'is_carousel_item': 'true'}) for a in release['assets']]
                parent = create({'media_type': 'CAROUSEL', 'children': ','.join(children), 'caption': caption})
            else:
                raise Blocked('UNSUPPORTED_MEDIA_TYPE')
            # A second live identity check immediately before publication prevents stale gates.
            meta.verify_account()
            validate_release(self.repo, release, self.config)
            before_post('PUBLISH_INTENT')
            update_attempt(self.journal, cid, owner, publish_intent=True, creation_id=parent, publish_attempted_at=now())
            publish_intent = True
            result = meta.post('media_publish', {'creation_id': parent})
            media_id = str(result.get('id', ''))
            if not media_id.isdigit():
                raise Blocked('PUBLISH_RESPONSE_UNCERTAIN', manual=True)
            final = update_attempt(self.journal, cid, owner, status='PUBLISHED', stage='PUBLISHED',
                                   instagram_media_id=media_id, published_at=now())
            return final['items'][cid]
        except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
            code = error.code if isinstance(error, Blocked) else 'PUBLISH_PROCESS_INTERRUPTED'
            # Never retry a publish POST, even after an HTTP timeout/temporary provider failure.
            state, _ = self.journal.read()
            current = state['items'].get(cid, {})
            uncertain = publish_intent or current.get('stage') in ('CREATE_CONTAINER_INTENT', 'PUBLISH_INTENT') or current.get('publish_intent')
            status = 'MANUAL_ACTION_REQUIRED' if uncertain else 'FAILED'
            if current.get('status') != 'PUBLISHED':
                update_attempt(self.journal, cid, owner, status=status, error_code=code)
            raise Blocked(code, manual=uncertain) from None
