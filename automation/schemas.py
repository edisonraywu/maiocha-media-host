"""Strict model contracts; all model output remains untrusted until validated."""
S = {'type': 'string'}
B = {'type': 'boolean'}


def arr(items=S):
    return {'type': 'array', 'items': items}


def enum(*values):
    return {'type': 'string', 'enum': list(values)}


def obj(**properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


COLOUR = enum('藍', '灰', '白', '粉', '紫', '綠', '黃', '金', '茶', '棕', '黑', '紅', '橙', '無色')
PHOTO_REVIEW = obj(photo_id=S, usable=B, issues=arr(), composition=S,
                   dominant_colors=arr(COLOUR), lighting=S, colour_reliable=B,
                   wearing=B, close_up=B, full_view=B, flat_lay=B, cover_score={'type': 'integer', 'minimum': 0, 'maximum': 100},
                   product_count={'type': 'integer', 'minimum': 0}, same_product=B)
PHOTO_REVIEW['properties'].update(
    photo_type=enum('hero', 'full_product', 'close_up', 'wearing', 'flat_lay', 'alternate_angle', 'different_lighting', 'other'),
    sharpness=S, exposure=S, white_balance=S, product_visibility=S, duplicate_similarity=S,
    similar_to_photo_id={'type': ['string', 'null']}, selection_reason=S)
PHOTO_REVIEW['required'] = list(PHOTO_REVIEW['properties'])
OBSERVATIONS = obj(dominant_colors=arr(COLOUR), secondary_colors=arr(COLOUR), color_description=S,
                   perceived_brightness=enum('明亮', '中等', '深暗', '不確定'),
                   visual_transparency_appearance=enum('不透明感', '半透明感', '透明感', '無法判斷'),
                   visible_surface_appearance=S, visible_patterns=arr(),
                   visual_contrast=enum('低', '中', '高', '不確定'), overall_visual_tone=S,
                   photo_lighting=S, wearing_scene=S, photo_type=arr(enum('上手', '平放', '近拍', '全貌', '其他')), visual_keywords=arr())
GROUNDING = obj(content_id=S, input_hash=S, grounding_status=enum('PASS', 'NEEDS_INFO'),
                visual_observations=OBSERVATIONS,
                facts=arr(obj(fact_id=S, description=S, evidence_photo_ids=arr())),
                photo_reviews=arr(PHOTO_REVIEW), selected_photo_ids=arr(),
                issues=arr(obj(photo_id=S, reason=S, action=S)))
BASIS = obj(content_id=S, input_hash=S, dominant_color=arr(COLOUR), secondary=arr(COLOUR),
            light=S, visual_mood=arr(), photo_characteristics=arr(), user_provided_crystal={'type': ['string', 'null']},
            candidate_imagery=arr(), rejected_imagery=arr(), reason=S, evidence_fact_ids=arr(),
            user_provided_facts=arr(obj(field=S, value=S)), unknown_facts=arr(),
            content_style=enum('商品主角', '顏色意境', '上手日常', '短句', '品牌生活', '新品', '貓咪品牌元素', '已查證小知識'))
CANDIDATE = obj(key=enum('A', 'B', 'C'), caption=S, hook=S, structure=S,
                claims=arr(obj(text=S, source=enum('user_provided', 'visual', 'imagery', 'subjective', 'cta'), references=arr())),
                product_fit_score={'type': 'integer', 'minimum': 0, 'maximum': 100}, reason=S)
CAPTIONS = obj(content_id=S, input_hash=S, candidates=arr(CANDIDATE), selected_key=enum('A', 'B', 'C'), selection_reason=S)
QA_KEYS = ('main_color_matches', 'light_matches', 'transparency_surface_supported', 'name_from_user',
           'price_from_user', 'bead_size_from_user', 'no_invented_features', 'no_guessed_mineral',
           'imagery_matches', 'same_product', 'content_id_matches', 'product_specific',
           'claims_fully_grounded', 'no_unsupported_treatment_origin_grade_health')
VISION_QA = obj(content_id=S, input_hash=S, caption_hash=S, selected_photo_ids=arr(),
                checks=obj(**{key: B for key in QA_KEYS}), issues=arr(), result=enum('PASS', 'FAIL'))
SCHEMAS = {'grounding': GROUNDING, 'basis': BASIS, 'captions': CAPTIONS, 'qa': VISION_QA}
