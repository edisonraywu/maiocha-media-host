from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .core import (Blocked, digest, item_dir, item_files, now, read_json, save_json, text_hash)
from .journal import update_attempt
from .network import Transport


def schedule_batch(repo: Path, workspace: Path, content: Path, config: dict, selection: list[dict], journal, *, test_only=False, meta=None, transport=None, host_action=None):
    from .core import credentials
    from .journal import schedule_release
    from .release import stage_release, verify_hosted
    from .publisher import preflight
    import time
    if not selection:
        return []
    credentials(config)
    state, _ = journal.read()
    if state['paused']:
        raise Blocked('PUBLISHING_PAUSED')
    if not test_only and not state['production_ready']:
        raise Blocked('LIVE_TEST_NOT_VERIFIED', manual=True)
    if test_only and (len(selection) != 1 or selection[0].get('content_type') != 'SINGLE'):
        raise Blocked('FIRST_TEST_MUST_BE_EXACTLY_ONE_SINGLE')
    packages = [stage_release(repo, content, item, config) for item in selection]
    (host_action or (lambda: host(repo, workspace)))()
    net = transport or Transport()
    results = []
    for item, pack in zip(selection, packages):
        # Bounded wait for the existing Pages deployment; retry only public reads.
        for attempt in range(8):
            try:
                verify_hosted(pack, net)
                break
            except Blocked:
                if attempt == 7:
                    raise Blocked('PAGES_NOT_READY_RUN_SCHEDULE_AGAIN') from None
                time.sleep(5)
        report = preflight(repo, pack, config, journal, meta, net, test_only=test_only)
        save_json(item_dir(content, item['content_id']) / 'preflight.json', report)
        if report['result'] == 'PASS':
            # Test publication is explicit; a scheduled production runner can never start the first test.
            if not test_only:
                schedule_release(journal, pack)
            item['status'] = 'APPROVED' if test_only else 'SCHEDULED'
            item['release_hash'] = pack['release_hash']
            save_json(item_dir(content, item['content_id']) / 'item.json', item)
        results.append(report)
    return results


def host(repo: Path, workspace: Path):
    """Reuse the existing GitHub Pages checkout and DPAPI Git askpass helper."""
    allowed = ('media/baobao', 'releases/baobao', 'config/brands/baobao.yaml')
    def git(*args):
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, env=env, timeout=120)
        if result.returncode:
            raise Blocked('GIT_HOSTING_OPERATION_FAILED', manual=True)
        return result.stdout.decode('utf-8', errors='replace').strip()
    env = dict(os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'
    askpass = workspace / '買房喵查局內容系統/11_系統工具/媒體託管/GitHubTokenAskPass.cmd'
    if askpass.exists():
        env['GIT_ASKPASS'] = str(askpass)
    remote = git('remote', 'get-url', 'origin')
    if remote != 'https://github.com/edisonraywu/maiocha-media-host.git':
        raise Blocked('UNEXPECTED_HOSTING_REMOTE')
    if git('branch', '--show-current') != 'main':
        raise Blocked('HOSTING_REQUIRES_MAIN_BRANCH')
    staged = git('diff', '--cached', '--name-only')
    if any(not any(line == prefix or line.startswith(prefix + '/') for prefix in allowed) for line in staged.splitlines()):
        raise Blocked('UNRELATED_STAGED_FILES')
    git('fetch', 'origin', 'main')
    if git('rev-list', '--count', 'HEAD..origin/main') != '0':
        raise Blocked('HOSTING_CHECKOUT_BEHIND_REMOTE')
    paths = [p for p in allowed if (repo / p).exists()]
    git('add', '--', *paths)
    if git('diff', '--cached', '--name-only'):
        git('commit', '-m', 'Stage approved baobao publishing assets')
    git('push', 'origin', 'main')
    return {'status': 'HOSTED_PENDING_PUBLIC_VERIFICATION', 'note': 'Pages 建置完成後，schedule 會重新下載核對每張圖。'}


def sync_archive(content: Path, journal):
    state, _ = journal.read()
    save_json(content / 'history' / 'published-history.json', {'brand': state['brand'], 'checked_at': now(),
              'items': list(state['items'].values()), 'history': state['history']})
    for path in item_files(content):
        item = read_json(path)
        entry = state['items'].get(item['content_id'])
        if not entry:
            continue
        item['remote_publish_state'] = entry
        item['status'] = entry['status']
        if entry['status'] == 'PUBLISHED':
            item['instagram_media_id'] = entry['instagram_media_id']
            item['published_at'] = entry['published_at']
            archive = content / 'archive' / item['content_id']
            archive.mkdir(parents=True, exist_ok=True)
            # Keep input originals immutable, and retain the item as a durable local tombstone.
            for name in ('product_grounding.json', 'caption_basis.json', 'caption_candidates.json',
                         'caption_qa.json', 'vision_qa.json', 'selected_caption.txt'):
                src = path.parent / name
                if src.exists() and not (archive / name).exists():
                    shutil.copy2(src, archive / name)
            save_json(archive / 'published.json', entry)
            save_json(archive / 'item.json', item)
        save_json(path, item)
    return {'remote_items': len(state['items']), 'production_ready': state['production_ready'], 'paused': state['paused']}


def verify_test(repo: Path, config: dict, journal, meta, other_meta, *, visual_confirmed=False):
    state, _ = journal.read()
    tests = [e for e in state['items'].values() if e.get('is_test') and e['status'] == 'PUBLISHED']
    if len(tests) != 1:
        raise Blocked('EXACTLY_ONE_SUCCESSFUL_TEST_REQUIRED')
    entry = tests[0]
    meta.verify_account()
    if entry['target'] != config['target']:
        raise Blocked('TEST_TARGET_MISMATCH')
    live = next((x for x in meta.recent_media() if str(x.get('id')) == entry['instagram_media_id']), None)
    if not live:
        raise Blocked('TEST_MEDIA_NOT_ON_EXPECTED_ACCOUNT')
    caption = (repo / 'releases' / config['brand'] / entry['content_id'] / 'caption.txt').read_text(encoding='utf-8')
    if live.get('caption', '').replace('\r\n', '\n') != caption.replace('\r\n', '\n'):
        raise Blocked('LIVE_CHINESE_CAPTION_MISMATCH')
    if live.get('media_type') != 'IMAGE' or not live.get('media_url', '').startswith('https://'):
        raise Blocked('LIVE_TEST_IMAGE_MISSING')
    if other_meta is None:
        raise Blocked('OTHER_ACCOUNT_READ_CHECK_REQUIRED', manual=True)
    other_meta.verify_account()
    other = other_meta.recent_media()
    if any(str(x.get('id')) == entry['instagram_media_id'] or x.get('caption') == caption for x in other):
        raise Blocked('TEST_FOUND_ON_OTHER_BRAND')
    # This is a human/Codex visual inspection declaration after opening the real IG post.
    if not visual_confirmed:
        raise Blocked('OPEN_LIVE_POST_AND_VERIFY_IMAGE', manual=True)
    verification = {'content_id': entry['content_id'], 'media_id': entry['instagram_media_id'],
                    'target': config['target'], 'verified_at': now(), 'caption_matches': True,
                    'on_target_account': True, 'absent_on_other_account': True,
                    'image_visually_verified': True, 'permalink': live.get('permalink')}
    def change(state):
        state['test_verification'] = verification
        state['production_ready'] = True
        # Remain paused until the explicit resume operation.
        state['paused'] = True
    journal.mutate(change)
    return verification


def reconcile(repo: Path, config: dict, journal, meta, cid: str, media_id: str):
    state, _ = journal.read()
    entry = state['items'].get(cid)
    if not entry or entry['status'] not in ('PUBLISHING', 'MANUAL_ACTION_REQUIRED', 'FAILED'):
        raise Blocked('NO_UNRESOLVED_ATTEMPT')
    if not entry.get('publish_intent'):
        raise Blocked('NO_PUBLISH_INTENT_TO_RECONCILE')
    meta.verify_account()
    candidate = next((x for x in meta.recent_media() if str(x.get('id')) == media_id), None)
    if not candidate or text_hash(candidate.get('caption', '')) != entry['caption_hash']:
        raise Blocked('RECONCILIATION_MEDIA_NOT_MATCHED')
    return update_attempt(journal, cid, entry['owner'], status='PUBLISHED', stage='RECONCILED',
                          instagram_media_id=media_id, published_at=candidate.get('timestamp', now()))['items'][cid]
