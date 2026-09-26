from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .calendar import plan_calendar, save_calendar
from .core import (REPO, Blocked, atomic_bytes, brand_config, credentials, digest, item_dir,
                   item_files, load_env, now, parse_time, read_json, save_json, valid_id)
from .generator import CodexBatchGenerator
from .ingest import ingest
from .journal import GitHubJournal, revoke_scheduled, schedule_release
from .network import MetaClient
from .operations import host, reconcile, schedule_batch, sync_archive, verify_test
from .pipeline import check_prepared, prepare
from .preview import render_preview
from .publisher import Publisher, preflight, preview_preflight
from .release import approve, stage_release


def parser():
    p = argparse.ArgumentParser(description='寶寶礦到了：商品照片 → 批次文案 → 審核 → 排程發布')
    p.add_argument('--brand', choices=['baobao', 'maiocha'], default='baobao')
    p.add_argument('--workspace', type=Path, default=REPO.parent)
    p.add_argument('--repo', type=Path, default=REPO)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('ingest', 'prepare', 'preview', 'calendar', 'status', 'host', 'init-journal', 'pause', 'resume', 'sync', 'doctor', 'due', 'secrets-sync', 'validate'):
        sub.add_parser(name)
    for name in ('approve', 'stage', 'preflight', 'preview-preflight', 'schedule', 'cancel'):
        s = sub.add_parser(name)
        s.add_argument('content_id', nargs='?')
        s.add_argument('--all', action='store_true')
    for name in ('preflight', 'schedule'):
        sub.choices[name].add_argument('--test', action='store_true')
    pub = sub.add_parser('publish')
    pub.add_argument('content_id')
    pub.add_argument('--dry-run', action='store_true')
    pub.add_argument('--test', action='store_true')
    pub.add_argument('--now', action='store_true', help='Explicitly publish before its scheduled time')
    pub.add_argument('--force-republish', action='store_true', help='Explicitly republish an already published item')
    sub.choices['due'].add_argument('--dry-run', action='store_true')
    reschedule = sub.add_parser('reschedule')
    reschedule.add_argument('content_id')
    reschedule.add_argument('publish_at', help='2026-10-01T20:00:00+08:00')
    edit = sub.add_parser('review-caption')
    edit.add_argument('content_id')
    revise = sub.add_parser('revise')
    revise.add_argument('content_id')
    revise.add_argument('--instructions', required=True)
    reorder = sub.add_parser('reorder')
    reorder.add_argument('content_id')
    reorder.add_argument('photo_ids', nargs='+', help='依 Preview 所列 photo_id 排列，只處理這件商品')
    mode = sub.add_parser('mode')
    mode.add_argument('value', choices=['approval', 'auto'])
    verify = sub.add_parser('verify-test')
    verify.add_argument('--confirm-visual', action='store_true')
    verify.add_argument('--other-env', type=Path, required=True)
    rec = sub.add_parser('reconcile')
    rec.add_argument('content_id')
    rec.add_argument('--media-id', required=True)
    retry = sub.add_parser('retry')
    retry.add_argument('content_id')
    return p


def run(args):
    repo, workspace = args.repo.resolve(), args.workspace.resolve()
    config = brand_config(args.brand, repo)
    content = workspace / 'content' / args.brand
    load_env(content / '.env')
    content.mkdir(parents=True, exist_ok=True)
    command = args.command
    if config.get('legacy', {}).get('enabled'):
        if command not in ('doctor', 'status'):
            raise Blocked('MAIOCHA_USE_PRESERVED_LEGACY_ENTRY')
    def journal():
        return GitHubJournal(config)
    def item(cid):
        result = read_json(item_dir(content, cid) / 'item.json')
        if not result or result.get('brand') != args.brand:
            raise Blocked('ITEM_NOT_FOUND_OR_WRONG_BRAND')
        return result
    def release(cid):
        data = read_json(repo / 'releases' / args.brand / valid_id(cid) / 'release.json')
        if not data:
            raise Blocked('STAGE_AND_HOST_FIRST')
        return data
    def targets():
        if getattr(args, 'all', False):
            return [read_json(p) for p in item_files(content) if read_json(p)['status'] in ('READY_FOR_REVIEW', 'APPROVED', 'SCHEDULED')]
        if not getattr(args, 'content_id', None):
            raise Blocked('CONTENT_ID_OR_ALL_REQUIRED')
        return [item(args.content_id)]
    if command == 'doctor':
        missing = [name for name in config['env'].values() if not os.environ.get(name)]
        return {'brand': args.brand, 'target': config['target'], 'missing_env_names': missing,
                'inbox_products': len([p for p in (content / 'inbox').glob('*') if p.is_dir()]),
                'approval_mode': config['approval_mode'], 'posting': config['posting'],
                'production_ready': False if missing else 'RUN_LIVE_PREFLIGHT', 'paid_api_enabled': False}
    if command == 'validate':
        state, _ = journal().read()
        return {'result': 'VALIDATION_PASS', 'brand': config['brand'], 'approval_mode': config['approval_mode'],
                'auto_publish_without_approval': False, 'journal_access': 'PASS', 'paused': state['paused'],
                'production_ready': state['production_ready'],
                'secret_presence': {name: bool(os.environ.get(name)) for name in config['env'].values()},
                'api_post_requests_sent': 0, 'note': '驗證設定與持久紀錄可讀；不代表 Meta 帳號已授權或已完成實物驗收。'}
    if command == 'secrets-sync':
        from .secret_setup import sync_secrets
        result = sync_secrets(config)
        save_json(content / 'github-secret-verification.json', result)
        return result
    if command == 'ingest':
        result = ingest(content, args.brand)
        render_preview(content, config)
        return [{'content_id': x.get('content_id'), 'status': x['status'], 'error': x.get('error')} for x in result]
    if command == 'prepare':
        # Withdraw a previously scheduled immutable package before accepting local edits.
        for path in item_files(content):
            old = read_json(path)
            if old.get('release_hash'):
                try:
                    check_prepared(content, old)
                except Blocked:
                    revoke_scheduled(journal(), old['content_id'])
        results = prepare(content, config, lambda: CodexBatchGenerator(config['generator']['timeout_seconds']))
        plan_calendar(content, config)
        results = [read_json(p) for p in item_files(content)]
        reports = [preview_preflight(repo, content, x, config) for x in results if x['status'] == 'READY_FOR_REVIEW']
        path = render_preview(content, config)
        return {'items': [{'content_id': x['content_id'], 'status': x['status'], 'errors': x.get('prepare_errors', [])} for x in results],
                'preview': str(path), 'count': len(results), 'scheduling': None, 'approval_granted': False,
                'preview_preflight': reports, 'message': '內容準備後停在 READY_FOR_REVIEW；等你明確批准。'}
    if command == 'preview':
        return {'preview': str(render_preview(content, config))}
    if command == 'calendar':
        result = plan_calendar(content, config)
        render_preview(content, config)
        return result
    if command == 'status':
        return {'brand': args.brand, 'items': [{k: read_json(p).get(k) for k in ('content_id', 'status', 'publish_at', 'instagram_media_id')} for p in item_files(content)]}
    if command == 'mode':
        if args.value != 'approval':
            raise Blocked('AUTO_PUBLISH_DISABLED_REQUIRES_EXPLICIT_APPROVAL')
        config['approval_mode'] = True
        config['auto_publish_without_approval'] = False
        atomic_bytes(repo / 'config/brands' / (args.brand + '.yaml'), yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode('utf-8'))
        return {'approval_mode': True, 'auto_publish_without_approval': False}
    if command in ('pause', 'resume'):
        def change(state):
            state['paused'] = command == 'pause'
        state = journal().mutate(change)
        return {'paused': state['paused'], 'production_ready': state['production_ready']}
    if command == 'init-journal':
        journal().initialize()
        return {'journal_initialized': True, 'note': '既有紀錄不會重設。'}
    if command == 'host':
        return host(repo, workspace)
    if command == 'sync':
        result = sync_archive(content, journal())
        render_preview(content, config)
        return result
    if command == 'approve':
        results = [approve(content, x, config) for x in targets()]
        render_preview(content, config)
        return [{'content_id': x['content_id'], 'status': x['status']} for x in results]
    if command == 'reschedule':
        data = item(args.content_id)
        if data['status'] in ('PUBLISHED', 'PUBLISHING', 'MANUAL_ACTION_REQUIRED'):
            raise Blocked('CANNOT_RESCHEDULE_PUBLISHED_OR_UNCERTAIN')
        parse_time(args.publish_at)
        # Cancel any already deployed old schedule before changing local state.
        if (repo / 'releases' / args.brand / data['content_id'] / 'release.json').exists():
            revoke_scheduled(journal(), data['content_id'])
        data.update({'publish_at': args.publish_at, 'approval': None, 'approval_state': 'PENDING', 'status': 'READY_FOR_REVIEW'})
        save_json(item_dir(content, data['content_id']) / 'item.json', data)
        render_preview(content, config)
        return {'content_id': data['content_id'], 'status': 'READY_FOR_REVIEW', 'schedule_state': 'PROPOSED_SCHEDULE', 'note': '僅修改建議日期；需重新明確核准。'}
    if command == 'cancel':
        results = []
        for data in targets():
            if (repo / 'releases' / args.brand / data['content_id'] / 'release.json').exists():
                revoke_scheduled(journal(), data['content_id'])
            data['status'] = 'CANCELLED'
            data['approval'] = None
            data['approval_state'] = 'PENDING'
            save_json(item_dir(content, data['content_id']) / 'item.json', data)
            results.append({'content_id': data['content_id'], 'status': 'CANCELLED'})
        render_preview(content, config)
        return results
    if command == 'stage':
        return [{'content_id': x['content_id'], 'release_hash': stage_release(repo, content, x, config)['release_hash']} for x in targets()]
    if command == 'review-caption':
        from .pipeline import review_caption
        data = item(args.content_id)
        if data.get('release_hash'):
            revoke_scheduled(journal(), data['content_id'])
        result = review_caption(content, data, config, CodexBatchGenerator(config['generator']['timeout_seconds']))
        render_preview(content, config)
        return {'content_id': data['content_id'], 'status': result['status'], 'errors': result.get('prepare_errors')}
    if command in ('revise', 'reorder'):
        from .pipeline import revise_one
        data = item(args.content_id)
        if data.get('release_hash'):
            revoke_scheduled(journal(), data['content_id'])
        result = revise_one(content, data, config, CodexBatchGenerator(config['generator']['timeout_seconds']),
                            instructions=args.instructions if command == 'revise' else '',
                            photo_ids=args.photo_ids if command == 'reorder' else None)
        if result['status'] == 'READY_FOR_REVIEW':
            preview_preflight(repo, content, result, config)
        render_preview(content, config)
        return {'content_id': result['content_id'], 'status': result['status'], 'errors': result.get('prepare_errors'), 'approval_granted': False}
    if command == 'preview-preflight':
        result = [preview_preflight(repo, content, x, config) for x in targets()]
        render_preview(content, config)
        return result
    if command == 'schedule':
        results = schedule_batch(repo, workspace, content, config, targets(), journal(), test_only=args.test)
        render_preview(content, config)
        return results
    if command == 'preflight':
        results = []
        state_store = journal()
        for data in targets():
            check_prepared(content, data)
            pack = release(data['content_id'])
            if pack['input_hash'] != data['input_hash'] or pack['publish_at'] != data['publish_at'] or pack['caption_sha256'] != read_json(item_dir(content, data['content_id']) / 'caption_qa.json')['caption_hash']:
                raise Blocked('LOCAL_RELEASE_STALE')
            report = preflight(repo, pack, config, state_store, test_only=args.test)
            save_json(item_dir(content, data['content_id']) / 'preflight.json', report)
            results.append(report)
        render_preview(content, config)
        return results
    if command == 'publish':
        pack = release(args.content_id)
        local = item(args.content_id)
        check_prepared(content, local)
        if pack['input_hash'] != local['input_hash'] or pack['qa']['local_report_hash'] != local['qa_hash'] or pack['publish_at'] != local['publish_at']:
            raise Blocked('LOCAL_RELEASE_STALE')
        result = Publisher(repo, config, journal()).publish(pack, dry_run=args.dry_run, test_only=args.test,
                   force=args.force_republish, due=not args.now)
        if not args.dry_run:
            sync_archive(content, journal())
            render_preview(content, config)
        return result
    if command == 'due':
        packs = [read_json(p) for p in (repo / 'releases' / args.brand).glob('*/release.json')]
        due = sorted([p for p in packs if p.get('status') in ('APPROVED', 'SCHEDULED') and parse_time(p['publish_at']) <= datetime.now(timezone.utc)], key=lambda p: p['publish_at'])
        if not due:
            return {'status': 'NO_DUE_CONTENT', 'api_post_requests_sent': 0}
        store = journal()
        state, _ = store.read()
        if state['paused']:
            return {'status': 'PAUSED', 'api_post_requests_sent': 0}
        results = []
        for pack in due:
            if pack['content_id'] in state['items']:
                continue
            queued = state.get('queue', {}).get(pack['content_id'])
            if not queued or queued.get('release_hash') != pack['release_hash']:
                continue
            result = Publisher(repo, config, store).publish(pack, dry_run=args.dry_run, due=True)
            results.append(result)
            if len(results) >= config['publishing'].get('max_posts_per_run', 1):
                break
        return results
    if command == 'verify-test':
        load_env(args.other_env)
        other_config = brand_config('maiocha' if args.brand == 'baobao' else 'baobao', repo)
        return verify_test(repo, config, journal(), MetaClient(config, credentials(config)),
                           MetaClient(other_config, credentials(other_config)), visual_confirmed=args.confirm_visual)
    if command == 'reconcile':
        return reconcile(repo, config, journal(), MetaClient(config, credentials(config)), args.content_id, args.media_id)
    if command == 'retry':
        # Only failures known to precede publication can be explicitly reset, at most twice.
        def change(state):
            old = state['items'].get(args.content_id, {})
            if old.get('status') != 'FAILED' or old.get('publish_intent') or old.get('stage') == 'CREATE_CONTAINER_INTENT':
                raise Blocked('UNSAFE_RETRY_REQUIRES_RECONCILIATION')
            past = sum(x.get('content_id') == args.content_id and x.get('status') == 'RETRIED' for x in state['history'])
            if past >= 2:
                raise Blocked('RETRY_LIMIT_REACHED', manual=True)
            old['status'] = 'RETRIED'
            state['history'].append(old)
            del state['items'][args.content_id]
        journal().mutate(change)
        return {'retry_enabled': True, 'note': '再次 preflight 後才可 publish；不確定是否已發布的內容不可重送。'}
    raise Blocked('UNKNOWN_COMMAND')


def main():
    args = parser().parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        reports = result if isinstance(result, list) else [result]
        return 2 if any(isinstance(x, dict) and x.get('result') in ('FAIL', 'MANUAL_ACTION_REQUIRED') for x in reports) else 0
    except Blocked as error:
        print(json.dumps({'status': 'MANUAL_ACTION_REQUIRED' if error.manual else 'FAIL', 'code': error.code,
                          'publication_outcome': 'NOT_CONFIRMED', 'do_not_retry_automatically': True}, ensure_ascii=False))
        return 2
    except Exception:
        # No unfiltered traceback can leak credentials or provider response bodies.
        print(json.dumps({'status': 'FAIL', 'code': 'UNEXPECTED_LOCAL_ERROR', 'publication_outcome': 'NOT_CONFIRMED', 'do_not_retry_automatically': True}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
