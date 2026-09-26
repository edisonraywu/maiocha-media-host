"""Persist explicit owner feedback. Ambiguous clauses remain questions, never preferences."""
from __future__ import annotations

import copy
import re

from .core import Blocked, digest, now, secret_free
from .style import STYLE_NAMES, empty_profile


def parse_feedback(text: str, examples: list[dict]) -> dict:
    secret_free(text)
    if not text.strip():
        raise Blocked('FEEDBACK_REQUIRED')
    result = {'preferred_styles': [], 'secondary_styles': [], 'rejected_styles': [], 'values': {},
              'style_adjustments': {}, 'favorite_phrases': [], 'forbidden_phrases': [],
              'favorite_examples': [], 'rejected_examples': [], 'tone': [], 'pending_clarification': []}

    def add_example(style, kind, scope='all', role='example'):
        matches = [e for e in examples if e['style_id'] == style]
        if not matches:
            result['pending_clarification'].append(f'找不到 Style {style} 的校準文字。')
        for example in matches:
            lines = [p for p in example['text'].split('\n\n') if p.strip()]
            if len(lines) == 1:
                lines = [p for p in example['text'].splitlines() if p.strip()]
            selected = lines[0] if scope == 'first_paragraph' else lines[-1] if scope == 'ending' else example['text']
            row = dict(example, text=selected, scope=scope, role=role)
            if row not in result[kind]:
                result[kind].append(row)

    # Keep quoted favorite phrases intact when splitting clauses.
    normalized = text.replace('寶寶，你的礦到了', '寶寶你的礦到了').replace('寶寶,你的礦到了', '寶寶你的礦到了')
    normalized = re.sub(r'(?i)([A-F]\s*(?:喜歡|不喜歡|不要))\s*(?=[A-F])', r'\1，', normalized)
    normalized = re.sub(r'(?=但(?:是)?\s*[A-F](?![A-Za-z]))', '，', normalized)
    parts = re.split(r'[\n。；;，,](?![^「」]*」)', normalized.strip())
    clauses = []
    for part in parts:
        if clauses and re.match(r'\s*但(?:是)?(?:不用|不要)每篇', part) and ('寶寶' in clauses[-1] or '品牌句' in clauses[-1]):
            clauses[-1] += ' ' + part
        else:
            clauses.append(part)
    for raw in clauses:
        clause = raw.strip(' 「」"“”')
        if not clause:
            continue
        known = False
        styles = re.findall(r'(?<![A-Za-z])([A-F])(?![A-Za-z])', clause, re.I)
        styles = list(dict.fromkeys(s.upper() for s in styles))
        negative = bool(re.search(r'不喜歡|不要|不愛|排除|拒絕', clause))
        positive = bool(re.search(r'喜歡|偏好|最愛|保留|可以|想要', clause)) and not negative
        if styles:
            if '第一段' in clause or '結尾' in clause or '語氣' in clause:
                for style in styles:
                    # A 的第一段 + E 的語氣 keeps the two references distinct.
                    segment = re.search(r'(?i)' + style + r'([^A-F]*)', clause)
                    portion = segment[1] if segment else clause
                    role = 'tone_preference' if '語氣' in portion else 'example'
                    scope = 'first_paragraph' if '第一段' in portion else 'ending' if '結尾' in portion else 'all'
                    kind = 'rejected_examples' if re.search(r'不喜歡|不要', portion) else 'favorite_examples'
                    add_example(style, kind, scope, role)
                known = True
            elif negative or positive:
                key = 'rejected_styles' if negative else 'secondary_styles' if '其次' in clause or '偶爾' in clause else 'preferred_styles'
                result[key] += styles
                for style in styles:
                    add_example(style, 'rejected_examples' if negative else 'favorite_examples')
                known = True
            for style in styles:
                adjustment = {}
                if re.search(r'太文青|太詩意|太夢幻', clause):
                    adjustment['poetic_level'] = 'low'
                if '太短' in clause:
                    adjustment['length'] = 'longer'
                if '太長' in clause:
                    adjustment['length'] = 'shorter'
                if '太像廣告' in clause or '太銷售' in clause:
                    adjustment['sales_level'] = 'low'
                if adjustment:
                    result['style_adjustments'].setdefault(style, {}).update(adjustment)
                    known = True
        if re.search(r'emoji|表情符號', clause, re.I):
            if re.search(r'不要|不用|禁止', clause):
                result['values']['emoji_usage'] = 'none'
            elif re.search(r'少量|少一點|一點|偶爾', clause):
                result['values']['emoji_usage'] = 'sparse'
            else:
                result['pending_clarification'].append(raw.strip())
            known = True
        if re.search(r'CTA|私訊|硬廣告|像廣告|銷售', clause, re.I):
            if re.search(r'不要.*(?:CTA|私訊)|(?:CTA|私訊).*(?:不要|不用)', clause, re.I) and '每篇' not in clause:
                result['values']['cta_usage'] = 'none'
            else:
                result['values']['cta_usage'] = 'occasional'
            result['values']['sales_level'] = 'low'
            known = True
        if '寶寶' in clause or re.search(r'signature|品牌句', clause, re.I):
            if re.search(r'不用每篇|不要每篇|偶爾|少量', clause):
                result['values']['brand_signature_usage'] = 'occasional'
            elif re.search(r'不要|不用', clause):
                result['values']['brand_signature_usage'] = 'none'
            elif '每篇' in clause and re.search(r'一定|都要', clause):
                result['values']['brand_signature_usage'] = 'always'
            elif re.search(r'可以留|保留', clause):
                result['values']['brand_signature_usage'] = 'occasional'
            else:
                result['pending_clarification'].append(raw.strip())
            known = True
        if not styles:
            if re.search(r'太詩意|太文青|太夢幻|少一點詩意|不要.*詩意', clause):
                result['values']['poetic_level'] = 'low'
                known = True
            if re.search(r'風景.*(?:多|強)|多.*風景|意境.*多', clause):
                result['values']['imagery_strength'] = 'high'
                known = True
            if re.search(r'短一點|喜歡短文|太長', clause):
                result['values']['preferred_length'] = 'short'
                known = True
            if re.search(r'喜歡長文|長一點', clause):
                result['values']['preferred_length'] = 'long'
                known = True
        for phrase, tone in (('自然', '自然'), ('生活感', '有生活感'), ('溫柔', '溫柔'), ('太做作', '避免做作'),
                             ('太官腔', '不官腔'), ('太可愛', '避免過度可愛'), ('罐頭', '避免罐頭文案')):
            if phrase in clause:
                result['tone'].append(tone)
                if phrase == '生活感':
                    result['values']['daily_life_level'] = 'high'
                known = True
        if re.search(r'最近.*很像|太重複|不要重複|罐頭', clause):
            result['values']['strengthen_repetition'] = True
            known = True
        quoted = re.findall(r'[「“"]([^」”"]+)[」”"]', raw)
        if quoted and (positive or negative):
            result['forbidden_phrases' if negative else 'favorite_phrases'] += quoted
            known = True
        if not styles and re.search(r'第一段|結尾', clause):
            # A single product and explicit style context must accompany this reference.
            if len(examples) == 1:
                add_example(examples[0]['style_id'], 'rejected_examples' if negative else 'favorite_examples',
                            'ending' if '結尾' in clause else 'first_paragraph')
            else:
                result['pending_clarification'].append('請指定哪條商品的哪個 Style：' + raw.strip())
            known = True
        if not known:
            result['pending_clarification'].append(raw.strip())
    for key in ('preferred_styles', 'secondary_styles', 'rejected_styles', 'tone', 'favorite_phrases', 'forbidden_phrases'):
        result[key] = list(dict.fromkeys(result[key]))
    return result


def merge_feedback(profile: dict | None, parsed: dict, text: str, *, session_id: str, evidence_hash: str,
                   resolve_pending=False) -> dict:
    result = copy.deepcopy(profile or empty_profile())
    result['revision'] += 1
    result['status'] = 'CALIBRATION_FEEDBACK_RECEIVED'
    result['CAPTION_STYLE_CALIBRATED'] = 'NO'
    result['confirmation'] = None
    if resolve_pending and not parsed['pending_clarification']:
        result['pending_clarification'] = []
    for key in ('preferred_styles', 'secondary_styles', 'rejected_styles', 'tone', 'favorite_phrases', 'forbidden_phrases',
                'favorite_examples', 'rejected_examples', 'pending_clarification'):
        for value in parsed[key]:
            if value not in result[key]:
                result[key].append(value)
    for style in parsed['rejected_styles']:
        for key in ('preferred_styles', 'secondary_styles'):
            result[key] = [s for s in result[key] if s != style]
    for style in parsed['preferred_styles'] + parsed['secondary_styles']:
        result['rejected_styles'] = [s for s in result['rejected_styles'] if s != style]
        result['rejected_examples'] = [e for e in result['rejected_examples'] if e.get('style_id') != style or e.get('scope') != 'all']
    for style, values in parsed['style_adjustments'].items():
        result['style_adjustments'].setdefault(style, {}).update(values)
    for key, value in parsed['values'].items():
        if key == 'strengthen_repetition':
            result['recent_repetition_rules'].update(max_same_imagery=2, max_same_cta=1, max_same_signature=1, max_common_phrase=2, max_similarity=.7)
        else:
            result[key] = value
    result['feedback'].append({'text': text, 'parsed': parsed, 'received_at': now(), 'session_id': session_id,
                               'evidence_hash': evidence_hash, 'source': 'explicit_owner_style_feedback'})
    return result
