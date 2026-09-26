from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

from .calendar import save_calendar
from .core import atomic_bytes, item_files, read_json, save_json


def photo_plan(item: dict, grounding: dict) -> list[dict]:
    reviews = {p['photo_id']: p for p in grounding.get('photo_reviews', [])}
    selected = item.get('selected_photo_ids', grounding.get('selected_photo_ids', []))
    rows = []
    for photo in item.get('photos', []):
        review = reviews.get(photo['photo_id'], {})
        position = selected.index(photo['photo_id']) + 1 if photo['photo_id'] in selected else None
        rows.append({**photo, 'position': position, 'cover': position == 1, 'review': review,
                     'recommendation': 'INCLUDE' if position else ('RECOMMEND_EXCLUDE' if review else 'PENDING_REVIEW'),
                     'reason': review.get('selection_reason') or '等待逐張照片分析。'})
    rows.sort(key=lambda p: (p['position'] or 999, p['source_name']))
    for duplicate in item.get('duplicates_removed', []):
        rows.append(dict(duplicate, source_name=duplicate['file'], position=None, cover=False,
                         duplicate_of=duplicate['same_as'], review={}, processed_path=None))
    return rows


def render_preview(content: Path, config: dict) -> Path:
    preview = content / 'preview'
    preview.mkdir(parents=True, exist_ok=True)
    rows, cards = [], []
    esc = lambda x: html.escape(str(x if x is not None else '未提供'))
    from .batch import refresh_batch
    batches = [refresh_batch(content, p.parent.name) for p in sorted((content / 'batches').glob('*/batch.json'))]
    products = {p['content_id']: p for b in batches for p in b['products']}
    for path in sorted(item_files(content), key=lambda p: (read_json(p).get('publish_at') or '9999', p.parent.name)):
        item = read_json(path)
        folder = path.parent
        grounding = read_json(folder / 'product_grounding.json', {})
        basis = read_json(folder / 'caption_basis.json', {})
        qa = read_json(folder / 'caption_qa.json', {})
        candidates = read_json(folder / 'caption_candidates.json', {})
        review_checks = read_json(folder / 'preview_preflight.json', {})
        caption_path = folder / 'selected_caption.txt'
        caption = caption_path.read_text(encoding='utf-8') if caption_path.exists() else '等待實際商品讀圖與文案生成。'
        photos = {p['photo_id']: p for p in item.get('photos', [])}
        selection = item.get('selected_photo_ids') or grounding.get('selected_photo_ids', [])
        plan = photo_plan(item, grounding)
        photo_html = []
        for p in plan:
            source = folder / (p.get('processed_path') or p['original_path'])
            rel = quote(os.path.relpath(source, preview).replace('\\', '/'), safe='/')
            position = '封面 · 01' if p['cover'] else (f'{p["position"]:02d}' if p['position'] else p['recommendation'])
            review = p.get('review', {})
            quality = ' · '.join(str(review[k]) for k in ('photo_type', 'sharpness', 'exposure', 'white_balance', 'product_visibility', 'duplicate_similarity') if review.get(k))
            photo_html.append(f'<figure data-recommendation="{esc(p["recommendation"])}"><img loading="lazy" src="{rel}" alt="{esc(p["source_name"])}"><figcaption><b>{esc(position)}</b> · {esc(p["source_name"])}<br>{esc(p["reason"])}<br>{esc(quality)}</figcaption></figure>')
        problems = item.get('issues', []) + item.get('photo_issues', []) + item.get('prepare_errors', [])
        product = products.get(item['content_id'], {})
        problems += product.get('binding_errors', []) + product.get('schedule_warnings', [])
        title = item['user_provided'].get('product_name') or item['user_provided'].get('crystal_name') or '這條素串（待提供水晶名稱）'
        obs = grounding.get('visual_observations', {})
        rows.append({'content_id': item['content_id'], 'product_name': title, 'publish_at': item.get('publish_at'),
                     'status': item['status'], 'photos': [photos[k]['source_name'] for k in selection],
                     'grounding': obs, 'caption_basis': basis, 'selected_caption': caption,
                     'user_provided': item['user_provided'], 'unknown_fields': grounding.get('unknown_fields', []),
                     'source_folder': item['source_folder'], 'target': config['target'], 'content_type': item.get('content_type'),
                     'selected_photo_ids': selection, 'caption_candidates': candidates.get('candidates', []),
                     'batch_id': item.get('batch_id'), 'product_ref': item.get('product_ref'), 'photo_plan': plan,
                     'declared_schedule': item.get('declared_schedule'), 'schedule_warnings': product.get('schedule_warnings', []),
                     'crystal_name': item['user_provided'].get('crystal_name'), 'selected_key': candidates.get('selected_key'),
                     'selection_reason': candidates.get('selection_reason'),
                     'preview_preflight': review_checks, 'schedule_state': 'SCHEDULED' if item['status'] == 'SCHEDULED' else 'PROPOSED_SCHEDULE',
                     'approval_state': item.get('approval_state', 'PENDING'), 'issues': problems, 'qa_result': qa.get('result')})
        metadata = ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in item['user_provided'].items())
        tags = ' · '.join(obs.get('dominant_colors', []))
        candidate_html = ''.join(f'<section><h3>文案 {esc(c["key"])}</h3><pre>{esc(c["caption"])}</pre><p>{esc(c.get("reason"))}</p></section>' for c in candidates.get('candidates', []))
        cards.append(f'''<article data-status="{esc(item['status'])}">
<div class="top"><span class="id">{esc(item['content_id'])}</span><b class="badge">{esc(item['status'])}</b></div>
<h2>{esc(title)}</h2><p class="date">{'正式排程' if item['status'] == 'SCHEDULED' else ('你指定的日期（待批准）' if item.get('batch_id') else '建議日期（尚非正式排程）')}：{esc(item.get('publish_at'))} · {esc(item.get('content_type'))}</p>
<p class="date">Batch：{esc(item.get('batch_id'))} · 商品：{esc(item.get('product_ref', item['content_id']))}</p>
<p class="date">商品資料夾：{esc(item['source_folder'])}<br>預計帳號：{esc(config['target'].get('username'))} · IG ID：{esc(config['target'].get('instagram_user_id'))}</p>
<div class="photos">{''.join(photo_html)}</div><div class="details"><section><h3>這一串的觀察</h3>
<p>{esc(obs.get('color_description', '尚未分析'))} {esc(tags)}</p><p>{esc(obs.get('photo_lighting', ''))}</p>
<p>{esc(obs.get('visual_transparency_appearance', ''))}（僅為照片視覺描述）</p>
<h3>為什麼用這個意境</h3><p>{esc(basis.get('reason', '尚未選擇'))}</p>
<p>候選：{esc('／'.join(basis.get('candidate_imagery', [])))}</p>
<p>排除：{esc('／'.join(basis.get('rejected_imagery', [])))}</p></section>
<section><h3>選定文案 {esc(candidates.get('selected_key'))}</h3><pre>{esc(caption)}</pre><p>選擇原因：{esc(candidates.get('selection_reason'))}</p><p>圖片 QA：{esc(qa.get('result'))}</p></section></div>
<div class="details">{candidate_html}</div>
<p>審核前檢查：{esc(review_checks.get('result', '尚未檢查'))} · Hosting：{esc(review_checks.get('checks', {}).get('hosting', '等待明確批准後公開'))}</p>
<details><summary>商品資料、未知欄位與需要補充的事項</summary><dl>{metadata}</dl><p>未知：{esc('、'.join(grounding.get('unknown_fields', [])))}</p><pre>{esc(problems or '沒有待補事項')}</pre></details></article>''')
    warning = config['posting'].get('note', '') if config['posting'].get('defaults_need_review') else ''
    ingest_report = read_json(content / 'ingest-report.json', {})
    intake_errors = [x for x in ingest_report.get('items', []) if x.get('error')]
    if intake_errors:
        cards.insert(0, '<article><h2>照片資料夾需要修正</h2><pre>' + esc(intake_errors) + '</pre></article>')
    batch_summary = ''.join('<article><h2>Batch ' + esc(b['batch_id']) + '</h2><p>' +
        esc(b['counts']) + '</p><p>日期／照片提醒：' + esc(b['conflicts']) + '</p><p>未對應群組：' +
        esc(b['unmapped_groups']) + '；未分組照片：' + esc(b['unmapped_images']) + '</p></article>' for b in batches)
    seen = {r['content_id'] for r in rows}
    for b in batches:
        for p in b['products']:
            if p['content_id'] not in seen:
                cards.append('<article data-status="NEEDS_INFO"><h2>' + esc(p['product_ref']) + ' · ' + esc(p['crystal_name']) +
                             '</h2><p>' + esc(p['publish_at']) + '</p><p>' + esc(p['status']) + '</p><pre>' +
                             esc(p['issues'] + p.get('binding_errors', [])) + '</pre></article>')
    page = f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>寶寶礦到了 · 批次內容預覽</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f2eb;color:#273a39;font:16px/1.65 system-ui,"Microsoft JhengHei",sans-serif}}
header,main{{max-width:1180px;margin:auto;padding:28px}}header{{padding-top:52px}}h1{{font-size:36px;margin:0}}.lead{{color:#596a63}}
.notice{{padding:16px;border-left:4px solid #a87839;background:#fff5df}}article{{background:#fff;border:1px solid #deded4;border-radius:16px;padding:24px;margin:24px 0}}
.top{{display:flex;justify-content:space-between;gap:16px}}.id,.date{{font-size:14px;color:#66736e}}.badge{{background:#eef2ea;border-radius:20px;padding:3px 12px;font-size:13px}}
h2{{font-size:24px;margin:12px 0 2px}}h3{{font-size:17px}}.photos{{display:flex;gap:12px;overflow:auto;margin:20px 0}}figure{{margin:0;flex:0 0 230px}}img{{display:block;width:100%;border-radius:8px}}figcaption{{font-size:12px;color:#78857d}}
.details{{display:grid;grid-template-columns:1fr 1fr;gap:32px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}dl{{display:grid;grid-template-columns:130px 1fr}}dt{{color:#6d756e}}dd{{margin:0}}
button{{padding:9px 16px;background:#e6ece3;border:0;border-radius:6px;cursor:pointer;margin-right:8px}}footer{{color:#68786d;font-size:13px}}@media(max-width:650px){{header,main{{padding:18px}}.details{{grid-template-columns:1fr}}article{{padding:16px}}h1{{font-size:29px}}}}
</style><header><p>寶寶，你的礦到了。</p><h1>每一串，都從它自己開始。</h1><p class="lead">商品照片 → 觀察 → 文案依據 → 三候選 → 圖片 QA → 日曆</p>
<p class="notice">{esc(warning or '目前排程使用已設定的日期與時間。')}<br>每篇皆須你明確批准。READY_FOR_REVIEW 只表示等待審核；查看此頁、提供照片、建議日期都不等於批准，這個頁面不會發布。</p>
<button onclick="filter('all')">全部</button><button onclick="filter('READY_FOR_REVIEW')">待審核</button><button onclick="filter('NEEDS_INFO')">需要補充</button><button onclick="filter('FAILED')">失敗</button></header>
<main>{batch_summary}{''.join(cards) if cards else '<article><h2>還沒有商品照片</h2><p>每週或每兩週提供商品照片、水晶名稱與每天要發哪一條，Codex 會整理這裡的批次 Preview。</p><p>沒有照片不會生成示範商品文案，也不會標記 READY_FOR_REVIEW。</p></article>'}
<footer>此頁是本機私人預覽。Original、商品資料與內部分析不會直接上傳 Hosting。</footer></main>
<script>function filter(s){{document.querySelectorAll('article[data-status]').forEach(a=>a.hidden=s!=='all'&&a.dataset.status!==s)}}</script></html>'''
    atomic_bytes(preview / 'preview.html', page.encode('utf-8'))
    save_json(preview / 'preview.json', {'brand': config['brand'], 'posting': config['posting'], 'batches': batches, 'items': rows})
    save_calendar(content, config)
    return preview / 'preview.html'
