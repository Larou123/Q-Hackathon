import http.server
import sqlite3
import json
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'db.sqlite')
EVIDENCE_STORE_PATH = os.path.join(BASE_DIR, 'evidence_store.json')
PORT = 3000
ELEVENLABS_AGENT_ID = os.getenv('ELEVENLABS_AGENT_ID', '').strip()
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY', '').strip()
ELEVENLABS_API_ORIGIN = os.getenv('ELEVENLABS_API_ORIGIN', 'https://api.elevenlabs.io').rstrip('/')
ELEVENLABS_TTS_VOICE_ID = os.getenv('ELEVENLABS_TTS_VOICE_ID', '').strip()
ELEVENLABS_TTS_MODEL_ID = os.getenv('ELEVENLABS_TTS_MODEL_ID', 'eleven_multilingual_v2').strip() or 'eleven_multilingual_v2'
ELEVENLABS_TTS_OUTPUT_FORMAT = os.getenv('ELEVENLABS_TTS_OUTPUT_FORMAT', 'mp3_44100_128').strip() or 'mp3_44100_128'
FOCUS_MATERIAL = os.getenv('FOCUS_MATERIAL', 'vitamin-d3').strip().lower() or 'vitamin-d3'
DATA_CACHE = None
AGENT_TTS_CACHE = None
_CACHE_LOCK = threading.Lock()


def humanize_product_name(sku, product_type):
    parts = sku.split('-')
    if product_type == 'raw-material':
        if len(parts) > 3:
            return ' '.join(part.capitalize() for part in parts[2:-1])
    if product_type == 'finished-good':
        if len(parts) > 2:
            brand = ' '.join(part.capitalize() for part in parts[1:-1]) or parts[1].capitalize()
            code = parts[-1].upper()
            return f'{brand} {code}'
    return sku


def strict_material_key(name):
    normalized = name.lower().replace('&', ' and ').replace('/', ' ')
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    normalized = ' '.join(normalized.split())
    return normalized.replace(' ', '')


def material_alias_definition(strict_key):
    aliases = {
        'naturalflavors': ('naturalflavor', 'Natural Flavor'),
        'naturalflavour': ('naturalflavor', 'Natural Flavor'),
        'naturalflavours': ('naturalflavor', 'Natural Flavor'),
        'silica': ('silica', 'Silica / Silicon Dioxide'),
        'silicondioxide': ('silica', 'Silica / Silicon Dioxide'),
        'ascorbicacid': ('vitaminc', 'Vitamin C / Ascorbic Acid'),
        'vitaminc': ('vitaminc', 'Vitamin C / Ascorbic Acid'),
        'vitamind3': ('vitamind3cholecalciferol', 'Vitamin D3 / Cholecalciferol'),
        'vitamind3cholecalciferol': ('vitamind3cholecalciferol', 'Vitamin D3 / Cholecalciferol'),
    }
    return aliases.get(strict_key, (strict_key, None))


def infer_material_risk_flags(name):
    strict_name = strict_material_key(name)
    flags = []

    if re.search(r'(bovine|porcine|gelatin|collagen|shellac|lanolin|tallow|fishoil|fishgelatin)', strict_name):
        flags.append({
            'code': 'animal_derived',
            'label': 'Animal-derived or claim-sensitive input',
            'severity': 'high',
            'detail': 'Name suggests an animal-derived source. Verify vegan, vegetarian, halal, kosher, and brand-claim fit before consolidation.',
        })

    if re.search(r'(softgel|capsule|beadlet|coating|encapsulat|filmcoat|filmcoated)', strict_name):
        flags.append({
            'code': 'dosage_form_specific',
            'label': 'Dosage-form specific component',
            'severity': 'medium',
            'detail': 'Name suggests a capsule, beadlet, or coating component. Treat it as function-specific and review formulation fit before merging it with generic ingredients.',
        })

    if re.search(r'(flavor|flavour|color|colour|sweetener|preservative|extract|aroma)', strict_name):
        flags.append({
            'code': 'label_sensitive',
            'label': 'Label-sensitive declaration risk',
            'severity': 'medium',
            'detail': 'Name suggests an ingredient that can affect label text, flavor claims, or declaration wording. Verify finished-product label impact before standardizing.',
        })

    if re.search(r'(label|bottle|closure|carton|pouch|foil|blister|jar|tube|liner)', strict_name):
        flags.append({
            'code': 'packaging_component',
            'label': 'Packaging component semantics',
            'severity': 'medium',
            'detail': 'Name suggests a packaging component. Verify dimensions, line compatibility, and functional fit before substitution.',
        })

    return flags


def default_evidence_store():
    return {
        'version': 1,
        'updated_at': None,
        'pipeline_blueprint': {
            'stages': ['retrieval', 'extraction', 'audit', 'commercial', 'decision'],
            'source_types': [
                'supplier_website',
                'product_page',
                'spec_pdf',
                'certificate_pdf',
                'regulatory_reference',
                'manual_upload',
                'api_response',
            ],
            'status_legend': {
                'queued': 'Ready for ingestion',
                'blocked': 'Waiting on an upstream stage',
                'in_progress': 'Currently being processed',
                'review': 'Needs human or auditor review',
                'verified': 'Verified and usable in decisions',
                'missing': 'No evidence loaded yet',
            },
        },
        'materials': {},
    }


def load_evidence_store():
    if not os.path.exists(EVIDENCE_STORE_PATH):
        return default_evidence_store()

    try:
        with open(EVIDENCE_STORE_PATH) as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default_evidence_store()

    default_payload = default_evidence_store()
    default_payload.update({
        'version': payload.get('version', default_payload['version']),
        'updated_at': payload.get('updated_at'),
        'pipeline_blueprint': {
            **default_payload['pipeline_blueprint'],
            **payload.get('pipeline_blueprint', {}),
        },
        'materials': payload.get('materials', {}),
    })
    return default_payload


def default_supplier_evidence_track(material_name, supplier_name, priority):
    return {
        'priority': priority,
        'notes': (
            f'Prepare a cached evidence package for {supplier_name} on {material_name}. '
            'This scaffold is the handoff boundary for future scraper, extractor, auditor, and pricing agents.'
        ),
        'stage_status': {
            'retrieval': 'queued',
            'extraction': 'blocked',
            'audit': 'blocked',
            'commercial': 'missing',
            'decision': 'blocked',
        },
        'source_queue': [
            {
                'type': 'supplier_website',
                'status': 'queued',
                'label': f'{supplier_name} website or catalog page',
                'url': None,
            },
            {
                'type': 'spec_pdf',
                'status': 'queued',
                'label': f'{material_name} specification / COA PDF',
                'url': None,
            },
            {
                'type': 'certificate_pdf',
                'status': 'queued',
                'label': 'Certification or claim-supporting PDF',
                'url': None,
            },
            {
                'type': 'manual_upload',
                'status': 'queued',
                'label': 'Commercial quote, MOQ, lead time, or service-level attachment',
                'url': None,
            },
        ],
        'claims_to_verify': [
            'ingredient identity',
            'claim fit for affected finished goods',
            'quality / certification fit',
        ],
        'commercial_fields': ['price', 'lead_time_days', 'moq', 'country_of_origin'],
        'evidence_items': [],
    }


def build_external_evidence_scaffold(evidence_store, focus_cluster):
    blueprint = evidence_store.get('pipeline_blueprint', default_evidence_store()['pipeline_blueprint'])
    material_entries = evidence_store.get('materials', {})
    material_entry = material_entries.get(focus_cluster['cluster_id'], {})

    supplier_tracks = []
    for candidate in focus_cluster['supplier_candidates'][:5]:
        priority = 'primary' if candidate['role'] == 'preferred' else ('secondary' if candidate['role'] == 'backup' else 'candidate')
        base_track = default_supplier_evidence_track(focus_cluster['canonical_name'], candidate['name'], priority)
        entry = material_entry.get('suppliers', {}).get(candidate['name'], {})

        stage_status = {**base_track['stage_status'], **entry.get('stage_status', {})}
        source_queue = entry.get('source_queue', base_track['source_queue'])
        evidence_items = entry.get('evidence_items', [])

        supplier_tracks.append({
            'name': candidate['name'],
            'role': candidate['role'],
            'priority': entry.get('priority', base_track['priority']),
            'notes': entry.get('notes', base_track['notes']),
            'stage_status': stage_status,
            'source_queue': source_queue,
            'claims_to_verify': entry.get('claims_to_verify', base_track['claims_to_verify']),
            'commercial_fields': entry.get('commercial_fields', base_track['commercial_fields']),
            'evidence_items': evidence_items,
        })

    queued_sources = sum(
        1
        for track in supplier_tracks
        for source in track['source_queue']
        if source.get('status') in {'queued', 'in_progress', 'review'}
    )
    verified_items = sum(
        1
        for track in supplier_tracks
        for item in track['evidence_items']
        if item.get('status') == 'verified'
    )
    ready_for_retrieval = sum(
        1
        for track in supplier_tracks
        if track['stage_status'].get('retrieval') in {'queued', 'in_progress', 'verified'}
    )

    return {
        'store_version': evidence_store.get('version', 1),
        'updated_at': evidence_store.get('updated_at'),
        'status': material_entry.get('status', 'scaffold_only'),
        'notes': material_entry.get(
            'notes',
            'Local scaffold only. Future scraper, OCR, extractor, auditor, and pricing agents can persist evidence here without changing the UI contract.',
        ),
        'review_questions': material_entry.get(
            'review_questions',
            [
                'Can the supplier prove the same ingredient identity or component specification?',
                'Are the required claims and certifications valid for the affected finished goods?',
                'Do price, lead time, MOQ, and service levels support consolidation?',
            ],
        ),
        'pipeline_blueprint': blueprint,
        'supplier_tracks': supplier_tracks,
        'summary': {
            'supplier_tracks': len(supplier_tracks),
            'queued_sources': queued_sources,
            'verified_items': verified_items,
            'retrieval_ready_suppliers': ready_for_retrieval,
        },
    }


def fetch_elevenlabs_conversation_token():
    if not ELEVENLABS_AGENT_ID or not ELEVENLABS_API_KEY:
        raise RuntimeError('ElevenLabs private voice mode is not configured.')

    url = (
        f'{ELEVENLABS_API_ORIGIN}/v1/convai/conversation/token'
        f'?agent_id={urllib.parse.quote(ELEVENLABS_AGENT_ID)}'
    )
    request = urllib.request.Request(
        url,
        headers={
            'xi-api-key': ELEVENLABS_API_KEY,
            'Accept': 'application/json',
        },
        method='GET',
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        raise RuntimeError(f'ElevenLabs returned HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Could not reach ElevenLabs: {exc.reason}') from exc

    token = payload.get('token')
    if not token:
        raise RuntimeError('ElevenLabs did not return a conversation token.')
    return token


def fetch_elevenlabs_agent_details():
    if not ELEVENLABS_AGENT_ID or not ELEVENLABS_API_KEY:
        raise RuntimeError('ElevenLabs agent details are not configured.')

    url = f'{ELEVENLABS_API_ORIGIN}/v1/convai/agents/{urllib.parse.quote(ELEVENLABS_AGENT_ID)}'
    request = urllib.request.Request(
        url,
        headers={
            'xi-api-key': ELEVENLABS_API_KEY,
            'Accept': 'application/json',
        },
        method='GET',
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        raise RuntimeError(f'Unable to fetch ElevenLabs agent details ({exc.code}): {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Could not reach ElevenLabs agent details: {exc.reason}') from exc


def resolve_elevenlabs_tts_config():
    global AGENT_TTS_CACHE

    if ELEVENLABS_TTS_VOICE_ID:
        return {
            'voice_id': ELEVENLABS_TTS_VOICE_ID,
            'model_id': ELEVENLABS_TTS_MODEL_ID,
            'source': 'env',
        }

    with _CACHE_LOCK:
        if AGENT_TTS_CACHE:
            return AGENT_TTS_CACHE

        agent_details = fetch_elevenlabs_agent_details()
        tts_config = ((agent_details.get('conversation_config') or {}).get('tts') or {})
        voice_id = (tts_config.get('voice_id') or '').strip()
        model_id = (tts_config.get('model_id') or ELEVENLABS_TTS_MODEL_ID).strip() or ELEVENLABS_TTS_MODEL_ID

        if not voice_id:
            raise RuntimeError('The ElevenLabs agent does not expose a usable TTS voice_id.')

        AGENT_TTS_CACHE = {
            'voice_id': voice_id,
            'model_id': model_id,
            'source': 'agent',
        }
        return AGENT_TTS_CACHE


def synthesize_elevenlabs_speech(text, language_code=None):
    if not ELEVENLABS_API_KEY:
        raise RuntimeError('ElevenLabs TTS requires ELEVENLABS_API_KEY.')

    tts_config = resolve_elevenlabs_tts_config()
    query = urllib.parse.urlencode({'output_format': ELEVENLABS_TTS_OUTPUT_FORMAT})
    url = f'{ELEVENLABS_API_ORIGIN}/v1/text-to-speech/{urllib.parse.quote(tts_config["voice_id"])}?{query}'
    payload = {
        'text': text,
        'model_id': tts_config['model_id'],
    }
    if language_code:
        payload['language_code'] = language_code

    request = urllib.request.Request(
        url,
        headers={
            'xi-api-key': ELEVENLABS_API_KEY,
            'Accept': 'audio/mpeg',
            'Content-Type': 'application/json',
        },
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), response.headers.get('Content-Type', 'audio/mpeg')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        raise RuntimeError(f'ElevenLabs TTS failed ({exc.code}): {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Could not reach ElevenLabs TTS: {exc.reason}') from exc


def get_cached_data(force_refresh=False):
    global DATA_CACHE
    with _CACHE_LOCK:
        if DATA_CACHE is None or force_refresh:
            DATA_CACHE = query_sourcing_data()
        return DATA_CACHE


def normalize_search_text(value):
    normalized = unicodedata.normalize('NFD', str(value or '').lower())
    normalized = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'\bgelatine\b', 'gelatin', normalized)
    normalized = re.sub(r'\bsoft gel\b', 'softgel', normalized)
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    return normalized.strip()


def get_meaningful_search_tokens(query):
    stopwords = {
        'a', 'an', 'and', 'are', 'der', 'die', 'das', 'oder', 'or', 'the', 'what', 'which',
        'welche', 'welcher', 'welches', 'wer', 'verkaufen', 'sell', 'sells', 'supplier',
        'suppliers', 'lieferant', 'lieferanten', 'material', 'materials', 'rohstoff',
        'rohstoffe', 'similar', 'derartiges', 'like', 'mit', 'von', 'for', 'zu', 'on',
    }
    return [
        token for token in normalize_search_text(query).split()
        if token and token not in stopwords
    ]


def score_search_text(text, tokens, full_query):
    normalized = normalize_search_text(text)
    if not normalized:
        return 0

    score = 0
    if full_query and full_query in normalized:
        score += 8

    for token in tokens:
        if normalized == token:
            score += 6
        elif token in normalized:
            score += 4 if len(token) >= 5 else 2

    return score


def find_matching_material_clusters(data, query, limit=5):
    full_query = normalize_search_text(query)
    tokens = get_meaningful_search_tokens(query)
    if not full_query and not tokens:
        return []

    ranked = []
    for cluster in data.get('material_clusters', []):
        searchable_texts = [
            cluster.get('canonical_name', ''),
            *cluster.get('name_variants', []),
            *(item.get('name', '') for item in cluster.get('raw_materials', [])),
        ]
        score = max(
            (score_search_text(text, tokens, full_query) for text in searchable_texts),
            default=0,
        )
        if score > 0:
            ranked.append((cluster, score))

    ranked.sort(
        key=lambda item: (
            -item[1],
            -item[0].get('finished_good_count', 0),
            item[0].get('canonical_name', ''),
        )
    )
    return [cluster for cluster, _score in ranked[:limit]]


def find_supplier_by_query(data, query):
    normalized = normalize_search_text(query)
    if not normalized:
        return None

    ranked = []
    for supplier in data.get('all_suppliers', []):
        score = score_search_text(supplier.get('name', ''), [normalized], normalized)
        if score > 0:
            ranked.append((supplier, score))

    ranked.sort(key=lambda item: (-item[1], item[0].get('name', '')))
    return ranked[0][0] if ranked else None


def build_material_supplier_lookup_payload(data, query, limit=5):
    matches = find_matching_material_clusters(data, query, limit=limit)
    return {
        'success': True,
        'query': query,
        'matches': [
            {
                'canonical_name': cluster.get('canonical_name'),
                'supplier_names': cluster.get('suppliers', []),
                'supplier_count': cluster.get('supplier_count', 0),
                'finished_good_count': cluster.get('finished_good_count', 0),
                'bom_count': cluster.get('bom_count', 0),
                'match_reason': cluster.get('match_reason'),
                'risk_flags': [
                    flag.get('label')
                    for flag in cluster.get('decision_readiness', {}).get('inferred_risk_flags', [])
                ],
            }
            for cluster in matches
        ],
    }


def build_supplier_catalog_payload(data, supplier_query):
    supplier = find_supplier_by_query(data, supplier_query)
    if not supplier:
        return {
            'success': True,
            'query': supplier_query,
            'supplier_found': False,
            'error': 'No supplier found in the internal snapshot.',
        }

    return {
        'success': True,
        'query': supplier_query,
        'supplier_found': True,
        'supplier_name': supplier.get('name'),
        'raw_material_count': sum(
            1 for product in supplier.get('products', [])
            if product.get('type') == 'raw-material'
        ),
        'linked_product_count': supplier.get('linked_products', 0),
        'sells_focus_material': supplier.get('selected_material_supplier', False),
        'sample_products': [
            {
                'name': product.get('name'),
                'sku': product.get('sku'),
                'type': product.get('type'),
            }
            for product in supplier.get('products', [])[:12]
        ],
    }


def extract_tool_value(payload, query_params, *names):
    sources = []
    if isinstance(payload, dict):
        sources.append(payload)
        for key in ('parameters', 'parameter', 'args', 'arguments', 'tool_input', 'input'):
            nested = payload.get(key)
            if isinstance(nested, dict):
                sources.append(nested)

    if query_params:
        sources.append({
            key: values[0]
            for key, values in query_params.items()
            if values
        })

    for name in names:
        for source in sources:
            value = source.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ''


def build_cluster_decision_readiness(cluster, cluster_confidence, preferred_supplier, backup_supplier):
    inferred_risk_flags = infer_material_risk_flags(cluster['canonical_name'])
    missing_evidence = [
        {
            'code': 'quality',
            'label': 'Quality evidence missing',
            'detail': 'No verified specification, COA, or certification data is present in the current internal snapshot.',
        },
        {
            'code': 'compliance',
            'label': 'Compliance evidence missing',
            'detail': 'No finished-good-specific compliance or claim-fit verification is available yet for this cluster.',
        },
        {
            'code': 'commercial',
            'label': 'Commercial evidence missing',
            'detail': 'Price, lead time, MOQ, and service-level terms are not part of the current recommendation score.',
        },
    ]

    if preferred_supplier:
        if (
            preferred_supplier['cluster_raw_material_coverage'] >= 1
            and preferred_supplier['cluster_finished_good_coverage'] >= 1
        ):
            internal_signal_strength = 'strong'
            internal_signal_summary = (
                'Preferred supplier covers every raw-material record and every affected finished good inside the current cluster.'
            )
        elif (
            preferred_supplier['cluster_raw_material_coverage'] >= 0.67
            or preferred_supplier['cluster_finished_good_coverage'] >= 0.67
        ):
            internal_signal_strength = 'moderate'
            internal_signal_summary = (
                'Preferred supplier covers most of the cluster, but some finished goods or raw-material records still sit outside the lead lane.'
            )
        else:
            internal_signal_strength = 'partial'
            internal_signal_summary = (
                'Preferred supplier only covers part of the cluster, so the recommendation should be treated as an early triage signal.'
            )
    else:
        internal_signal_strength = 'weak'
        internal_signal_summary = (
            'Agnes cannot form a meaningful internal shortlist because the current cluster lacks enough supplier-support data.'
        )

    required_checks = []
    if cluster_confidence == 'review':
        required_checks.append(
            'Confirm that the clustered records are functionally interchangeable before using the supplier shortlist.'
        )
    else:
        required_checks.append(
            'Confirm that the shortlisted suppliers can satisfy the same material specification across the affected finished goods.'
        )

    if inferred_risk_flags:
        required_checks.append(
            'Resolve the inferred material-name risk signals against claims, dosage-form requirements, or packaging fit before approval.'
        )

    required_checks.extend([
        'Verify quality evidence such as specifications, COAs, certifications, and customer-specific requirements.',
        'Add commercial evidence including price, lead time, MOQ, and service levels before final approval.',
    ])

    if backup_supplier:
        required_checks.append(
            f'Confirm that {backup_supplier["name"]} can cover the critical BOMs as an approved backup path.'
        )

    if cluster_confidence == 'review':
        status = 'needs_procurement_review'
        label = 'Needs procurement review'
        summary = (
            'Naming variants or alias collisions still need a buyer or formulation review before this cluster should drive a sourcing change.'
        )
        decision_boundary = (
            'Do not approve consolidation yet. First validate that these records really represent the same functional material.'
        )
    elif not preferred_supplier:
        status = 'insufficient_internal_signal'
        label = 'Insufficient internal signal'
        summary = (
            'The cluster is visible, but Agnes cannot yet form a stable lead-supplier recommendation from the internal data alone.'
        )
        decision_boundary = (
            'Use this as a watchlist item only until stronger supplier-coverage evidence is available.'
        )
    elif not backup_supplier:
        status = 'single_supplier_exposure'
        label = 'Single-supplier exposure'
        summary = (
            'Agnes can see a likely lead supplier, but there is no internal backup lane yet for resilience.'
        )
        decision_boundary = (
            'Treat this as a lead-supplier hypothesis, not an approval-ready sourcing decision.'
        )
    elif inferred_risk_flags:
        status = 'needs_external_review'
        label = 'Needs external review'
        summary = (
            'Internal demand and supplier-coverage signals are strong enough for a shortlist, but the material name suggests claim, formulation, or packaging-sensitive checks before approval.'
        )
        decision_boundary = (
            'Use this shortlist for triage only. External quality, compliance, or line-fit evidence is still mandatory.'
        )
    else:
        status = 'internal_shortlist_ready'
        label = 'Internal shortlist ready'
        summary = (
            'Internal demand, supplier coverage, and finished-good reach are strong enough to create a shortlist.'
        )
        decision_boundary = (
            'This is shortlist-ready, not approval-ready. Quality, compliance, and commercial checks are still required.'
        )

    return {
        'status': status,
        'label': label,
        'summary': summary,
        'decision_boundary': decision_boundary,
        'internal_signal_strength': internal_signal_strength,
        'internal_signal_summary': internal_signal_summary,
        'required_checks': required_checks,
        'missing_evidence': missing_evidence,
        'inferred_risk_flags': inferred_risk_flags,
    }


def build_sourcing_decision_payload(material_name, material_sku, suppliers, companies, material_clusters, evidence_store):
    if not material_clusters:
        return None

    focus_cluster = next(
        (cluster for cluster in material_clusters if cluster['contains_focus_material']),
        material_clusters[0],
    )
    preferred_supplier = focus_cluster['recommendation']['preferred_supplier']
    backup_supplier = focus_cluster['recommendation']['backup_supplier']
    readiness = focus_cluster['decision_readiness']
    external_evidence = build_external_evidence_scaffold(evidence_store, focus_cluster)

    status_copy = {
        'internal_shortlist_ready': 'Internal shortlist ready',
        'needs_external_review': 'Needs external review',
        'needs_procurement_review': 'Needs procurement review',
        'single_supplier_exposure': 'Single-supplier exposure',
        'insufficient_internal_signal': 'Insufficient internal signal',
    }.get(readiness['status'], readiness['label'])

    supplier_names = suppliers or focus_cluster['suppliers']
    supplier_preview = ', '.join(supplier_names[:3])
    if len(supplier_names) > 3:
        supplier_preview += f' +{len(supplier_names) - 3} more'

    context_items = [
        {'label': 'Raw material', 'value': material_name},
        {'label': 'Canonical cluster', 'value': focus_cluster['canonical_name']},
        {
            'label': 'Affected scope',
            'value': f'{focus_cluster["finished_good_count"]} finished goods · {focus_cluster["bom_count"]} BOMs',
        },
        {
            'label': 'Current suppliers',
            'value': supplier_preview or 'No linked suppliers',
        },
        {
            'label': 'Decision stage',
            'value': status_copy,
        },
        {
            'label': 'Naming pattern',
            'value': focus_cluster['match_reason'],
        },
        {
            'label': 'Companies impacted',
            'value': ', '.join(companies[:3]) + (f' +{len(companies) - 3} more' if len(companies) > 3 else ''),
        },
        {
            'label': 'Bundled opportunity',
            'value': 'Yes — lead lane can be shortlisted' if preferred_supplier else 'Needs more internal signal',
        },
    ]

    comparison_options = []
    for candidate in focus_cluster['supplier_candidates'][:5]:
        if candidate['role'] == 'preferred':
            triage_label = readiness['label']
            triage_status = readiness['status']
            decision_copy = readiness['decision_boundary']
        elif candidate['role'] == 'backup':
            triage_label = 'Backup shortlist'
            triage_status = 'backup_shortlist'
            decision_copy = 'Hold this supplier as the resilience path while the lead lane is externally verified.'
        else:
            triage_label = 'Further review'
            triage_status = 'candidate_review'
            decision_copy = 'Candidate is visible internally, but trails the lead and backup lanes on current coverage and network strength.'

        comparison_options.append({
            'name': candidate['name'],
            'role': candidate['role'],
            'triage_label': triage_label,
            'triage_status': triage_status,
            'score': candidate['score'],
            'cluster_coverage_percent': round(candidate['cluster_raw_material_coverage'] * 100),
            'finished_good_coverage_percent': round(candidate['cluster_finished_good_coverage'] * 100),
            'bom_coverage_percent': round(candidate['cluster_bom_coverage'] * 100),
            'raw_material_links': candidate['raw_material_links'],
            'focus_continuity': candidate['focus_continuity'],
            'decision_copy': decision_copy,
            'rationale': candidate['rationale'][:3],
        })

    evidence_items = [
        {
            'source': 'Internal · BOM graph',
            'status': 'verified',
            'title': 'Impact scope confirmed from internal BOMs',
            'detail': (
                f'{focus_cluster["canonical_name"]} touches {focus_cluster["bom_count"]} BOMs and '
                f'{focus_cluster["finished_good_count"]} finished goods across {focus_cluster["company_count"]} companies.'
            ),
            'tags': ['Internal', 'Verified'],
        },
    ]

    if preferred_supplier:
        evidence_items.append({
            'source': 'Internal · Supplier coverage',
            'status': 'verified',
            'title': f'{preferred_supplier["name"]} is the strongest internal lead lane',
            'detail': (
                f'Covers {preferred_supplier["raw_material_records_supported"]} of {focus_cluster["raw_material_count"]} '
                f'raw-material records and {preferred_supplier["finished_goods_supported"]} of '
                f'{focus_cluster["finished_good_count"]} finished goods in the cluster.'
            ),
            'tags': ['Internal', 'Coverage'],
        })
        evidence_items.append({
            'source': 'Internal · Supplier network',
            'status': 'verified',
            'title': 'Supplier network breadth confirmed',
            'detail': (
                f'{preferred_supplier["name"]} is already linked to {preferred_supplier["raw_material_links"]} raw materials '
                'across the wider internal network.'
            ),
            'tags': ['Internal', 'Network'],
        })

    evidence_items.append({
        'source': 'Internal · Master data',
        'status': 'inferred' if focus_cluster['match_reason'] != 'Same canonical name repeated' else 'verified',
        'title': 'Clustering logic defines the substitute lane',
        'detail': (
            f'{focus_cluster["canonical_name"]} currently groups {focus_cluster["raw_material_count"]} raw-material records '
            f'with {focus_cluster["name_variant_count"]} naming variants. Match reason: {focus_cluster["match_reason"]}.'
        ),
        'tags': ['Clustering', 'Inference' if focus_cluster['match_reason'] != 'Same canonical name repeated' else 'Verified'],
    })

    for missing in readiness['missing_evidence']:
        evidence_items.append({
            'source': 'Open evidence gap',
            'status': 'missing',
            'title': missing['label'],
            'detail': missing['detail'],
            'tags': ['Missing evidence'],
        })

    for flag in readiness['inferred_risk_flags']:
        evidence_items.append({
            'source': 'Name-based risk signal',
            'status': 'review',
            'title': flag['label'],
            'detail': flag['detail'],
            'tags': ['Needs review', flag['severity']],
        })

    next_actions = list(readiness['required_checks'][:4])
    if preferred_supplier:
        next_actions.insert(
            0,
            f'Keep {preferred_supplier["name"]} as the provisional lead supplier for {focus_cluster["canonical_name"]}.'
        )
    if backup_supplier:
        next_actions.insert(
            1,
            f'Keep {backup_supplier["name"]} approved as the resilience path while evidence is still being gathered.'
        )

    return {
        'title': f'{material_name} — Sourcing Decision Workspace',
        'subtitle': 'Live internal decision workspace from db.sqlite. Agnes shows what is shortlist-ready and what still blocks approval.',
        'question': (
            f'If we consolidate demand for {material_name} across the affected finished goods, '
            'which supplier lane should lead first, what still blocks approval, and what evidence is still missing?'
        ),
        'focus_cluster_id': focus_cluster['cluster_id'],
        'focus_cluster_name': focus_cluster['canonical_name'],
        'focus_cluster_confidence': focus_cluster['confidence'],
        'focus_match_reason': focus_cluster['match_reason'],
        'status': readiness['status'],
        'status_label': status_copy,
        'status_summary': readiness['summary'],
        'decision_boundary': readiness['decision_boundary'],
        'preferred_supplier': preferred_supplier,
        'backup_supplier': backup_supplier,
        'impact': {
            'raw_material_records': focus_cluster['raw_material_count'],
            'suppliers': focus_cluster['supplier_count'],
            'finished_goods': focus_cluster['finished_good_count'],
            'boms': focus_cluster['bom_count'],
            'companies': focus_cluster['company_count'],
        },
        'context_items': context_items,
        'comparison_options': comparison_options,
        'evidence_items': evidence_items[:8],
        'required_checks': readiness['required_checks'],
        'missing_evidence': readiness['missing_evidence'],
        'risk_flags': readiness['inferred_risk_flags'],
        'next_actions': next_actions[:5],
        'affected_finished_goods': focus_cluster['finished_goods'][:6],
        'external_evidence': external_evidence,
    }


def find_material_cluster_by_name(material_name, material_clusters):
    target_key = strict_material_key(material_name or '')
    if not target_key:
        return None

    for cluster in material_clusters:
        candidate_names = [cluster.get('canonical_name', ''), *(cluster.get('name_variants') or [])]
        if any(strict_material_key(name) == target_key for name in candidate_names if name):
            return cluster
    return None


def build_action_queue_payload(sourcing_decision, material_clusters, top_raw_materials):
    if not sourcing_decision:
        return []

    focus_cluster = next(
        (cluster for cluster in material_clusters if cluster['cluster_id'] == sourcing_decision['focus_cluster_id']),
        None,
    )
    if focus_cluster is None and material_clusters:
        focus_cluster = material_clusters[0]

    preferred_supplier = sourcing_decision.get('preferred_supplier')
    backup_supplier = sourcing_decision.get('backup_supplier')
    actions = []

    if focus_cluster and preferred_supplier:
        actions.append({
            'id': f'action-{focus_cluster["cluster_id"]}-lead',
            'type': 'supplier_consolidation',
            'title': f'Shift the main {focus_cluster["canonical_name"]} lane to {preferred_supplier["name"]}.',
            'summary': (
                f'{preferred_supplier["name"]} already covers {preferred_supplier["raw_material_records_supported"]} '
                f'of {focus_cluster["raw_material_count"]} raw-material records in this cluster and touches '
                f'{focus_cluster["bom_count"]} BOMs.'
            ),
            'reason': sourcing_decision.get('status_summary'),
            'status': sourcing_decision.get('status'),
            'status_label': sourcing_decision.get('status_label'),
            'priority_score': focus_cluster['priority_score'] + 45,
            'chips': [
                f'{focus_cluster["bom_count"]} BOMs',
                f'{focus_cluster["finished_good_count"]} finished goods',
                'Lead lane',
            ],
            'target': {
                'page': 'inventory',
                'cluster_id': focus_cluster['cluster_id'],
            },
            'cta': 'Open sourcing decision',
        })

    if focus_cluster and backup_supplier:
        actions.append({
            'id': f'action-{focus_cluster["cluster_id"]}-backup',
            'type': 'backup_coverage',
            'title': f'Keep {backup_supplier["name"]} approved as backup coverage.',
            'summary': (
                f'{backup_supplier["name"]} is the cleanest resilience path while Agnes still waits on '
                f'quality, compliance, and commercial checks for {focus_cluster["canonical_name"]}.'
            ),
            'reason': 'Backup coverage protects the lead-supplier move from creating a single-point sourcing failure.',
            'status': 'backup_shortlist',
            'status_label': 'Backup shortlist',
            'priority_score': focus_cluster['priority_score'] + 28,
            'chips': [
                backup_supplier['name'],
                f'{focus_cluster["supplier_count"]} suppliers',
                'Resilience',
            ],
            'target': {
                'page': 'suppliers',
                'supplier_name': backup_supplier['name'],
            },
            'cta': 'Open supplier',
        })

    standardization_material = None
    standardization_cluster = None
    focus_cluster_key = strict_material_key(focus_cluster['canonical_name']) if focus_cluster else ''
    for item in top_raw_materials:
        if strict_material_key(item['name']) == focus_cluster_key:
            continue
        standardization_material = item
        standardization_cluster = find_material_cluster_by_name(item['name'], material_clusters)
        break

    if standardization_material:
        standardization_chips = [
            f'{standardization_material["bom_count"]} BOMs',
            'Standardization',
        ]
        if standardization_cluster:
            standardization_chips.insert(1, f'{standardization_cluster["supplier_count"]} suppliers')

        actions.append({
            'id': f'action-standardize-{strict_material_key(standardization_material["name"])}',
            'type': 'standardization',
            'title': f'Standardize {standardization_material["name"]} specifications across the shared BOMs.',
            'summary': (
                f'{standardization_material["name"]} has one of the widest shared footprints in the current dataset. '
                'Harmonizing the specification first creates cleaner downstream supplier and reformulation decisions.'
            ),
            'reason': (
                f'{standardization_material["name"]} appears in {standardization_material["bom_count"]} BOMs, '
                'so this is one of the highest-reach master-data cleanup moves.'
            ),
            'status': standardization_cluster['decision_readiness']['status'] if standardization_cluster else 'internal_signal',
            'status_label': standardization_cluster['decision_readiness']['label'] if standardization_cluster else 'Internal signal',
            'priority_score': (standardization_cluster['priority_score'] if standardization_cluster else 0) + standardization_material['bom_count'] * 6,
            'chips': standardization_chips,
            'target': {
                'page': 'standardization' if standardization_cluster else 'products',
                **({'cluster_id': standardization_cluster['cluster_id']} if standardization_cluster else {}),
            },
            'cta': 'Open standardization' if standardization_cluster else 'Open products',
        })

    review_cluster = next(
        (
            cluster
            for cluster in material_clusters
            if focus_cluster and cluster['cluster_id'] != focus_cluster['cluster_id']
            and cluster['decision_readiness']['status'] in {'needs_external_review', 'needs_procurement_review'}
        ),
        None,
    )
    if review_cluster and len(actions) < 4:
        actions.append({
            'id': f'action-review-{review_cluster["cluster_id"]}',
            'type': 'evidence_review',
            'title': f'Review {review_cluster["canonical_name"]} before any larger sourcing shift.',
            'summary': (
                f'{review_cluster["canonical_name"]} still shows naming or formulation ambiguity. '
                'Agnes wants this checked before it becomes a scaled recommendation lane.'
            ),
            'reason': review_cluster['decision_readiness']['summary'],
            'status': review_cluster['decision_readiness']['status'],
            'status_label': review_cluster['decision_readiness']['label'],
            'priority_score': review_cluster['priority_score'],
            'chips': [
                review_cluster['decision_readiness']['label'],
                f'{review_cluster["supplier_count"]} suppliers',
                f'{review_cluster["finished_good_count"]} finished goods',
            ],
            'target': {
                'page': 'standardization',
                'cluster_id': review_cluster['cluster_id'],
            },
            'cta': 'Open review',
        })

    actions.sort(key=lambda action: (-action['priority_score'], action['title']))
    for index, action in enumerate(actions, start=1):
        action['step'] = index

    return actions[:4]


def query_sourcing_data():
    evidence_store = load_evidence_store()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    overview_queries = {
        'products': "SELECT COUNT(*) FROM Product",
        'raw_materials': "SELECT COUNT(*) FROM Product WHERE Type = 'raw-material'",
        'finished_goods': "SELECT COUNT(*) FROM Product WHERE Type = 'finished-good'",
        'boms': "SELECT COUNT(*) FROM BOM",
        'bom_components': "SELECT COUNT(*) FROM BOM_Component",
        'suppliers': "SELECT COUNT(*) FROM Supplier",
        'supplier_links': "SELECT COUNT(*) FROM Supplier_Product",
        'companies': "SELECT COUNT(*) FROM Company",
    }
    overview = {}
    for key, sql in overview_queries.items():
        cur.execute(sql)
        overview[key] = cur.fetchone()[0]

    # Raw material with most BOM usage among focus-material entries
    focus_pattern = f'%{FOCUS_MATERIAL}%'
    cur.execute("""
        SELECT p.Id, p.SKU, COUNT(DISTINCT bc.BOMId) AS bom_count
        FROM Product p
        JOIN BOM_Component bc ON bc.ConsumedProductId = p.Id
        WHERE p.SKU LIKE ? AND p.Type = 'raw-material'
        GROUP BY p.Id
        ORDER BY bom_count DESC
        LIMIT 1
    """, (focus_pattern,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise RuntimeError(f"No '{FOCUS_MATERIAL}' raw material found in db.sqlite")

    material_id = row['Id']
    material_sku = row['SKU']
    bom_count = row['bom_count']

    # Suppliers for this material
    cur.execute("""
        SELECT s.Name FROM Supplier_Product sp
        JOIN Supplier s ON sp.SupplierId = s.Id
        WHERE sp.ProductId = ?
    """, (material_id,))
    suppliers = [r['Name'] for r in cur.fetchall()]

    # Distinct brand companies that use this material
    cur.execute("""
        SELECT DISTINCT c.Name
        FROM BOM_Component bc
        JOIN BOM b ON bc.BOMId = b.Id
        JOIN Product fg ON b.ProducedProductId = fg.Id
        JOIN Company c ON fg.CompanyId = c.Id
        WHERE bc.ConsumedProductId = ?
    """, (material_id,))
    companies = [r['Name'] for r in cur.fetchall()]

    cur.execute("""
        SELECT
            s.Id,
            s.Name,
            COUNT(sp.ProductId) AS linked_products,
            SUM(CASE WHEN p.Type = 'raw-material' THEN 1 ELSE 0 END) AS raw_material_links
        FROM Supplier s
        LEFT JOIN Supplier_Product sp ON sp.SupplierId = s.Id
        LEFT JOIN Product p ON p.Id = sp.ProductId
        GROUP BY s.Id, s.Name
        ORDER BY s.Name
    """)
    all_suppliers = []
    selected_suppliers = set(suppliers)
    for supplier in cur.fetchall():
        all_suppliers.append({
            'id': supplier['Id'],
            'name': supplier['Name'],
            'linked_products': supplier['linked_products'],
            'raw_material_links': supplier['raw_material_links'] or 0,
            'selected_material_supplier': supplier['Name'] in selected_suppliers,
            'products': [],
        })

    supplier_lookup = {supplier['id']: supplier for supplier in all_suppliers}
    supplier_name_lookup = {supplier['name']: supplier for supplier in all_suppliers}
    max_supplier_raw_material_links = max(
        (supplier['raw_material_links'] for supplier in all_suppliers),
        default=1,
    )
    cur.execute("""
        SELECT
            sp.SupplierId,
            p.Id AS product_id,
            p.SKU,
            p.Type
        FROM Supplier_Product sp
        JOIN Product p ON p.Id = sp.ProductId
        ORDER BY sp.SupplierId, p.SKU
    """)
    for product in cur.fetchall():
        supplier_lookup[product['SupplierId']]['products'].append({
            'id': product['product_id'],
            'sku': product['SKU'],
            'name': humanize_product_name(product['SKU'], product['Type']),
            'type': product['Type'],
            'is_focus_material': product['product_id'] == material_id,
        })

    cur.execute("""
        SELECT COUNT(*) AS focus_boms
        FROM BOM_Component
        WHERE ConsumedProductId = ?
    """, (material_id,))
    focus_boms = cur.fetchone()['focus_boms']

    cur.execute("""
        SELECT
            MIN(cnt) AS min_items,
            MAX(cnt) AS max_items,
            ROUND(AVG(cnt), 1) AS avg_items
        FROM (
            SELECT COUNT(*) AS cnt
            FROM BOM_Component
            GROUP BY BOMId
        )
    """)
    bom_insights_row = cur.fetchone()

    cur.execute("""
        SELECT COUNT(DISTINCT c.Name) AS company_count
        FROM BOM b
        JOIN Product fg ON fg.Id = b.ProducedProductId
        JOIN Company c ON c.Id = fg.CompanyId
    """)
    company_count = cur.fetchone()['company_count']

    bom_insights = {
        'focus_boms': focus_boms,
        'min_items': bom_insights_row['min_items'],
        'max_items': bom_insights_row['max_items'],
        'avg_items': bom_insights_row['avg_items'],
        'company_count': company_count,
    }

    cur.execute("""
        SELECT
            c.Name AS company_name,
            COUNT(*) AS bom_count
        FROM BOM b
        JOIN Product fg ON fg.Id = b.ProducedProductId
        JOIN Company c ON c.Id = fg.CompanyId
        GROUP BY c.Name
        ORDER BY bom_count DESC, c.Name
        LIMIT 8
    """)
    top_bom_companies = []
    for company in cur.fetchall():
        top_bom_companies.append({
            'company_name': company['company_name'],
            'bom_count': company['bom_count'],
        })

    cur.execute("""
        SELECT
            b.Id AS bom_id,
            fg.Id AS product_id,
            fg.SKU AS product_sku,
            c.Name AS company_name,
            COUNT(bc.ConsumedProductId) AS item_count,
            MAX(CASE WHEN bc.ConsumedProductId = ? THEN 1 ELSE 0 END) AS contains_focus_material
        FROM BOM b
        JOIN Product fg ON fg.Id = b.ProducedProductId
        JOIN Company c ON c.Id = fg.CompanyId
        LEFT JOIN BOM_Component bc ON bc.BOMId = b.Id
        GROUP BY b.Id, fg.SKU, c.Name
        ORDER BY item_count DESC, b.Id
    """, (material_id,))
    all_boms = []
    for bom in cur.fetchall():
        all_boms.append({
            'bom_id': bom['bom_id'],
            'product_id': bom['product_id'],
            'product_sku': bom['product_sku'],
            'product_name': humanize_product_name(bom['product_sku'], 'finished-good'),
            'company_name': bom['company_name'],
            'item_count': bom['item_count'],
            'contains_focus_material': bool(bom['contains_focus_material']),
            'components': [],
        })

    bom_lookup = {bom['bom_id']: bom for bom in all_boms}
    cur.execute("""
        SELECT
            bc.BOMId,
            p.Id AS component_id,
            p.SKU,
            p.Type
        FROM BOM_Component bc
        JOIN Product p ON p.Id = bc.ConsumedProductId
        ORDER BY bc.BOMId, p.SKU
    """)
    for component in cur.fetchall():
        bom_lookup[component['BOMId']]['components'].append({
            'id': component['component_id'],
            'sku': component['SKU'],
            'name': humanize_product_name(component['SKU'], component['Type']),
            'type': component['Type'],
            'is_focus_material': component['component_id'] == material_id,
        })

    cur.execute("""
        SELECT
            fg.Id AS product_id,
            fg.SKU AS product_sku,
            c.Name AS company_name,
            b.Id AS bom_id,
            COUNT(bc.ConsumedProductId) AS raw_material_count,
            MAX(CASE WHEN bc.ConsumedProductId = ? THEN 1 ELSE 0 END) AS contains_focus_material
        FROM Product fg
        JOIN Company c ON c.Id = fg.CompanyId
        LEFT JOIN BOM b ON b.ProducedProductId = fg.Id
        LEFT JOIN BOM_Component bc ON bc.BOMId = b.Id
        WHERE fg.Type = 'finished-good'
        GROUP BY fg.Id, fg.SKU, c.Name, b.Id
        ORDER BY raw_material_count DESC, fg.SKU
    """, (material_id,))
    finished_goods = []
    for finished_good in cur.fetchall():
        finished_goods.append({
            'product_id': finished_good['product_id'],
            'product_sku': finished_good['product_sku'],
            'product_name': humanize_product_name(finished_good['product_sku'], 'finished-good'),
            'company_name': finished_good['company_name'],
            'bom_id': finished_good['bom_id'],
            'raw_material_count': finished_good['raw_material_count'],
            'contains_focus_material': bool(finished_good['contains_focus_material']),
            'raw_materials': [],
        })

    finished_good_lookup = {finished_good['product_id']: finished_good for finished_good in finished_goods}
    cur.execute("""
        SELECT
            b.ProducedProductId AS product_id,
            p.Id AS raw_material_id,
            p.SKU
        FROM BOM b
        JOIN BOM_Component bc ON bc.BOMId = b.Id
        JOIN Product p ON p.Id = bc.ConsumedProductId
        WHERE p.Type = 'raw-material'
        ORDER BY b.ProducedProductId, p.SKU
    """)
    for raw_material in cur.fetchall():
        finished_good_lookup[raw_material['product_id']]['raw_materials'].append({
            'id': raw_material['raw_material_id'],
            'sku': raw_material['SKU'],
            'name': humanize_product_name(raw_material['SKU'], 'raw-material'),
            'type': 'raw-material',
            'is_focus_material': raw_material['raw_material_id'] == material_id,
        })

    cur.execute("""
        SELECT
            ROUND(AVG(raw_material_count), 1) AS avg_raw_materials,
            MAX(raw_material_count) AS max_raw_materials,
            COUNT(DISTINCT company_name) AS company_count,
            SUM(CASE WHEN contains_focus_material = 1 THEN 1 ELSE 0 END) AS focus_finished_goods
        FROM (
            SELECT
                fg.Id AS product_id,
                c.Name AS company_name,
                COUNT(bc.ConsumedProductId) AS raw_material_count,
                MAX(CASE WHEN bc.ConsumedProductId = ? THEN 1 ELSE 0 END) AS contains_focus_material
            FROM Product fg
            JOIN Company c ON c.Id = fg.CompanyId
            LEFT JOIN BOM b ON b.ProducedProductId = fg.Id
            LEFT JOIN BOM_Component bc ON bc.BOMId = b.Id
            WHERE fg.Type = 'finished-good'
            GROUP BY fg.Id, c.Name
        )
    """, (material_id,))
    finished_good_insights_row = cur.fetchone()
    finished_good_insights = {
        'avg_raw_materials': finished_good_insights_row['avg_raw_materials'],
        'max_raw_materials': finished_good_insights_row['max_raw_materials'],
        'company_count': finished_good_insights_row['company_count'],
        'focus_finished_goods': finished_good_insights_row['focus_finished_goods'],
    }

    cur.execute("""
        SELECT
            c.Name AS company_name,
            COUNT(*) AS finished_good_count
        FROM Product fg
        JOIN Company c ON c.Id = fg.CompanyId
        WHERE fg.Type = 'finished-good'
        GROUP BY c.Name
        ORDER BY finished_good_count DESC, c.Name
        LIMIT 8
    """)
    top_finished_good_companies = []
    for company in cur.fetchall():
        top_finished_good_companies.append({
            'company_name': company['company_name'],
            'finished_good_count': company['finished_good_count'],
        })

    cur.execute("""
        SELECT p.SKU, COUNT(DISTINCT bc.BOMId) AS bom_count
        FROM Product p
        JOIN BOM_Component bc ON bc.ConsumedProductId = p.Id
        WHERE p.Type = 'raw-material'
        GROUP BY p.Id
        ORDER BY bom_count DESC, p.SKU ASC
        LIMIT 5
    """)
    top_raw_materials = []
    for raw in cur.fetchall():
        top_raw_materials.append({
            'sku': raw['SKU'],
            'name': humanize_product_name(raw['SKU'], 'raw-material'),
            'bom_count': raw['bom_count'],
        })

    raw_material_records = {}
    for supplier in all_suppliers:
        for product in supplier['products']:
            if product['type'] != 'raw-material':
                continue
            raw_material = raw_material_records.setdefault(product['id'], {
                'id': product['id'],
                'sku': product['sku'],
                'name': product['name'],
                'suppliers': set(),
                'bom_ids': set(),
                'companies': set(),
                'finished_goods': {},
                'is_focus_material': product['is_focus_material'],
            })
            raw_material['suppliers'].add(supplier['name'])

    for bom in all_boms:
        finished_good_ref = {
            'product_id': bom['product_id'],
            'product_name': bom['product_name'],
            'product_sku': bom['product_sku'],
            'company_name': bom['company_name'],
            'bom_id': bom['bom_id'],
            'contains_focus_material': bom['contains_focus_material'],
        }
        for component in bom['components']:
            if component['type'] != 'raw-material':
                continue
            raw_material = raw_material_records.setdefault(component['id'], {
                'id': component['id'],
                'sku': component['sku'],
                'name': component['name'],
                'suppliers': set(),
                'bom_ids': set(),
                'companies': set(),
                'finished_goods': {},
                'is_focus_material': component['is_focus_material'],
            })
            raw_material['bom_ids'].add(bom['bom_id'])
            raw_material['companies'].add(bom['company_name'])
            raw_material['finished_goods'][bom['product_id']] = finished_good_ref

    material_cluster_lookup = {}
    for raw_material in raw_material_records.values():
        strict_key = strict_material_key(raw_material['name'])
        alias_key, alias_label = material_alias_definition(strict_key)
        cluster = material_cluster_lookup.setdefault(alias_key, {
            'cluster_key': alias_key,
            'canonical_name': alias_label or raw_material['name'],
            'alias_label': alias_label,
            'uses_alias_mapping': False,
            'strict_keys': set(),
            'display_names': set(),
            'suppliers': set(),
            'bom_ids': set(),
            'companies': set(),
            'finished_goods': {},
            'raw_materials': [],
            'supplier_support': {},
            'contains_focus_material': False,
        })
        if alias_label is not None:
            cluster['uses_alias_mapping'] = True
        cluster['strict_keys'].add(strict_key)
        cluster['display_names'].add(raw_material['name'])
        cluster['suppliers'].update(raw_material['suppliers'])
        cluster['bom_ids'].update(raw_material['bom_ids'])
        cluster['companies'].update(raw_material['companies'])
        cluster['finished_goods'].update(raw_material['finished_goods'])
        cluster['contains_focus_material'] = cluster['contains_focus_material'] or raw_material['is_focus_material']
        cluster['raw_materials'].append({
            'id': raw_material['id'],
            'sku': raw_material['sku'],
            'name': raw_material['name'],
            'supplier_names': sorted(raw_material['suppliers']),
            'supplier_count': len(raw_material['suppliers']),
            'bom_count': len(raw_material['bom_ids']),
            'finished_good_count': len(raw_material['finished_goods']),
            'is_focus_material': raw_material['is_focus_material'],
        })
        for supplier_name in raw_material['suppliers']:
            supplier_support = cluster['supplier_support'].setdefault(supplier_name, {
                'raw_material_ids': set(),
                'bom_ids': set(),
                'finished_good_ids': set(),
            })
            supplier_support['raw_material_ids'].add(raw_material['id'])
            supplier_support['bom_ids'].update(raw_material['bom_ids'])
            supplier_support['finished_good_ids'].update(raw_material['finished_goods'].keys())

    material_clusters = []
    impacted_finished_good_ids = set()
    impacted_supplier_names = set()
    for cluster in material_cluster_lookup.values():
        if len(cluster['raw_materials']) < 2:
            continue
        if len(cluster['finished_goods']) == 0:
            continue

        supplier_names = sorted(cluster['suppliers'])
        display_names = sorted(cluster['display_names'])
        if len(supplier_names) < 2 and len(display_names) < 2:
            continue

        confidence = 'high' if len(cluster['strict_keys']) == 1 or cluster['uses_alias_mapping'] else 'review'
        if cluster['uses_alias_mapping'] and len(cluster['strict_keys']) > 1:
            match_reason = 'Curated ingredient alias matched'
        else:
            match_reason = 'Naming variants detected' if confidence == 'review' else 'Same canonical name repeated'
        priority_score = (
            len(cluster['finished_goods']) * 12
            + len(cluster['bom_ids']) * 3
            + len(cluster['raw_materials']) * 2
            + len(supplier_names) * 4
        )

        sorted_finished_goods = sorted(
            cluster['finished_goods'].values(),
            key=lambda item: (item['company_name'], item['product_name'], item['product_sku'])
        )
        sorted_raw_materials = sorted(
            cluster['raw_materials'],
            key=lambda item: (-item['finished_good_count'], item['name'], item['sku'])
        )

        supplier_candidates = []
        for supplier_name in supplier_names:
            supplier_support = cluster['supplier_support'][supplier_name]
            supplier_meta = supplier_name_lookup.get(supplier_name, {})
            raw_material_coverage = len(supplier_support['raw_material_ids']) / max(len(sorted_raw_materials), 1)
            finished_good_coverage = len(supplier_support['finished_good_ids']) / max(len(sorted_finished_goods), 1)
            bom_coverage = len(supplier_support['bom_ids']) / max(len(cluster['bom_ids']), 1)
            network_strength = supplier_meta.get('raw_material_links', 0) / max_supplier_raw_material_links
            focus_continuity = (
                1
                if cluster['contains_focus_material'] and supplier_meta.get('selected_material_supplier')
                else 0
            )

            score_components = {
                'cluster_coverage': round(raw_material_coverage * 40),
                'finished_good_coverage': round(finished_good_coverage * 20),
                'network_strength': round(network_strength * 25),
                'focus_continuity': 15 if focus_continuity else 0,
            }
            total_score = sum(score_components.values())

            rationale = []
            if raw_material_coverage == 1:
                rationale.append('Covers every raw-material record in the cluster')
            else:
                rationale.append(
                    f'Covers {len(supplier_support["raw_material_ids"])} of {len(sorted_raw_materials)} raw-material records'
                )
            rationale.append(
                f'Touches {len(supplier_support["finished_good_ids"])} of {len(sorted_finished_goods)} finished goods in this cluster'
            )
            rationale.append(
                f'Currently linked to {supplier_meta.get("raw_material_links", 0)} raw materials across the wider supplier network'
            )
            if focus_continuity:
                rationale.append('Already active on the current focus-material sourcing lane')

            supplier_candidates.append({
                'name': supplier_name,
                'score': total_score,
                'score_components': score_components,
                'cluster_raw_material_coverage': round(raw_material_coverage, 2),
                'cluster_finished_good_coverage': round(finished_good_coverage, 2),
                'cluster_bom_coverage': round(bom_coverage, 2),
                'raw_material_records_supported': len(supplier_support['raw_material_ids']),
                'finished_goods_supported': len(supplier_support['finished_good_ids']),
                'bom_support_count': len(supplier_support['bom_ids']),
                'raw_material_links': supplier_meta.get('raw_material_links', 0),
                'linked_products': supplier_meta.get('linked_products', 0),
                'focus_continuity': bool(focus_continuity),
                'rationale': rationale,
            })

        supplier_candidates.sort(
            key=lambda candidate: (
                -candidate['score'],
                -candidate['raw_material_links'],
                candidate['name'],
            )
        )
        for index, candidate in enumerate(supplier_candidates):
            candidate['role'] = 'preferred' if index == 0 else ('backup' if index == 1 else 'candidate')

        preferred_supplier = supplier_candidates[0] if supplier_candidates else None
        backup_supplier = supplier_candidates[1] if len(supplier_candidates) > 1 else None
        decision_readiness = build_cluster_decision_readiness(
            cluster,
            confidence,
            preferred_supplier,
            backup_supplier,
        )
        recommendation = {
            'preferred_supplier': preferred_supplier,
            'backup_supplier': backup_supplier,
            'method': 'Internal-only recommendation based on cluster coverage, finished-good reach, supplier network breadth, and focus-material continuity.',
            'open_gap': 'Quality, compliance, cost, lead time, and MOQ are not yet included in this score.',
        }

        material_clusters.append({
            'cluster_id': cluster['cluster_key'],
            'canonical_name': cluster['canonical_name'],
            'confidence': confidence,
            'match_reason': match_reason,
            'priority_score': priority_score,
            'raw_material_count': len(sorted_raw_materials),
            'supplier_count': len(supplier_names),
            'finished_good_count': len(sorted_finished_goods),
            'bom_count': len(cluster['bom_ids']),
            'company_count': len(cluster['companies']),
            'name_variant_count': len(display_names),
            'suppliers': supplier_names,
            'name_variants': display_names,
            'contains_focus_material': cluster['contains_focus_material'],
            'supplier_candidates': supplier_candidates,
            'recommendation': recommendation,
            'decision_readiness': decision_readiness,
            'raw_materials': sorted_raw_materials,
            'finished_goods': sorted_finished_goods,
        })
        impacted_finished_good_ids.update(cluster['finished_goods'].keys())
        impacted_supplier_names.update(supplier_names)

    material_clusters.sort(
        key=lambda cluster: (
            cluster['confidence'] != 'high',
            -cluster['priority_score'],
            cluster['canonical_name'],
        )
    )

    standardization_insights = {
        'total_clusters': len(material_clusters),
        'high_confidence_clusters': sum(1 for cluster in material_clusters if cluster['confidence'] == 'high'),
        'review_clusters': sum(1 for cluster in material_clusters if cluster['confidence'] == 'review'),
        'affected_finished_goods': len(impacted_finished_good_ids),
        'affected_suppliers': len(impacted_supplier_names),
        'internal_shortlist_ready_clusters': sum(
            1
            for cluster in material_clusters
            if cluster['decision_readiness']['status'] == 'internal_shortlist_ready'
        ),
        'needs_external_review_clusters': sum(
            1
            for cluster in material_clusters
            if cluster['decision_readiness']['status'] == 'needs_external_review'
        ),
        'procurement_review_clusters': sum(
            1
            for cluster in material_clusters
            if cluster['decision_readiness']['status'] == 'needs_procurement_review'
        ),
        'single_supplier_clusters': sum(
            1
            for cluster in material_clusters
            if cluster['decision_readiness']['status'] == 'single_supplier_exposure'
        ),
        'risk_flagged_clusters': sum(
            1
            for cluster in material_clusters
            if cluster['decision_readiness']['inferred_risk_flags']
        ),
    }

    conn.close()

    readable_name = humanize_product_name(material_sku, 'raw-material')
    sourcing_decision = build_sourcing_decision_payload(
        readable_name,
        material_sku,
        suppliers,
        companies,
        material_clusters,
        evidence_store,
    )
    action_queue = build_action_queue_payload(
        sourcing_decision,
        material_clusters,
        top_raw_materials,
    )

    return {
        'material': {
            'id': material_id,
            'sku': material_sku,
            'name': readable_name,
            'bom_count': bom_count,
        },
        'overview': overview,
        'suppliers': suppliers,
        'companies': companies,
        'all_suppliers': all_suppliers,
        'bom_insights': bom_insights,
        'top_bom_companies': top_bom_companies,
        'all_boms': all_boms,
        'finished_good_insights': finished_good_insights,
        'top_finished_good_companies': top_finished_good_companies,
        'finished_goods': finished_goods,
        'standardization_insights': standardization_insights,
        'material_clusters': material_clusters,
        'top_raw_materials': top_raw_materials,
        'sourcing_decision': sourcing_decision,
        'action_queue': action_queue,
        'evidence_store_meta': {
            'version': evidence_store.get('version', 1),
            'updated_at': evidence_store.get('updated_at'),
        },
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, xi-api-key')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, payload, content_type='application/octet-stream', status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, xi-api-key')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, xi-api-key')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def read_json_body(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length <= 0:
            return {}

        try:
            raw = self.rfile.read(length)
        except OSError:
            return {}

        if not raw:
            return {}

        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == '/api/agnes/voice-config':
            enabled = bool(ELEVENLABS_AGENT_ID)
            mode = 'private' if ELEVENLABS_API_KEY else ('public' if enabled else 'disabled')
            self.send_json({
                'enabled': enabled,
                'provider': 'elevenlabs' if enabled else 'local',
                'mode': mode,
                'agentId': ELEVENLABS_AGENT_ID or None,
                'ttsEnabled': bool(ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID),
                'ttsEndpoint': '/api/agnes/elevenlabs/tts' if ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID else None,
                'conversationTokenEndpoint': (
                    '/api/agnes/elevenlabs/conversation-token'
                    if enabled and ELEVENLABS_API_KEY
                    else None
                ),
                'clientTools': [
                    'lookupMaterialSuppliers',
                    'lookupSupplierCatalog',
                    'openSupplierDetail',
                    'openMaterialCluster',
                ],
                'serverTools': [
                    '/api/elevenlabs/material-suppliers',
                    '/api/elevenlabs/supplier-catalog',
                ],
            })
            return

        if parsed.path == '/api/agnes/elevenlabs/conversation-token':
            if not ELEVENLABS_AGENT_ID or not ELEVENLABS_API_KEY:
                self.send_json({
                    'error': 'ElevenLabs private voice mode is not configured on this server.',
                }, status=501)
                return

            try:
                token = fetch_elevenlabs_conversation_token()
            except RuntimeError as exc:
                self.send_json({'error': str(exc)}, status=502)
                return

            self.send_json({
                'token': token,
                'mode': 'private',
            })
            return

        if not self._dispatch_shared_api(parsed.path, query_params, {}):
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        payload = self.read_json_body()

        if not self._dispatch_shared_api(parsed.path, query_params, payload):
            self.send_json({'error': 'Unknown API endpoint.'}, status=404)

    def _dispatch_shared_api(self, path, query_params, payload):
        """Handle API routes shared between GET and POST. Returns True if handled."""
        if path in {
            '/api/elevenlabs/material-suppliers',
            '/api/agnes/elevenlabs/material-suppliers',
        }:
            query = extract_tool_value(payload, query_params, 'query', 'material', 'search')
            self.send_json(build_material_supplier_lookup_payload(get_cached_data(), query))
            return True

        if path in {
            '/api/elevenlabs/supplier-catalog',
            '/api/agnes/elevenlabs/supplier-catalog',
        }:
            supplier_query = extract_tool_value(payload, query_params, 'supplier_name', 'query', 'supplier')
            self.send_json(build_supplier_catalog_payload(get_cached_data(), supplier_query))
            return True

        if path in {
            '/api/elevenlabs/tts',
            '/api/agnes/elevenlabs/tts',
        }:
            text = extract_tool_value(payload, query_params, 'text')
            language_code = extract_tool_value(payload, query_params, 'language_code', 'language')
            if not text:
                self.send_json({'error': 'Missing text for TTS synthesis.'}, status=422)
                return True
            try:
                audio_bytes, content_type = synthesize_elevenlabs_speech(text, language_code or None)
            except RuntimeError as exc:
                self.send_json({'error': str(exc)}, status=502)
                return True
            self.send_bytes(audio_bytes, content_type=content_type, status=200)
            return True

        return False


if __name__ == '__main__':
    os.chdir(BASE_DIR)

    # Write data.json once at startup so the static server can serve it
    data = get_cached_data(force_refresh=True)
    with open(os.path.join(BASE_DIR, 'data.json'), 'w') as f:
        json.dump(data, f)
    print(f'data.json written ({data["material"]["bom_count"]} BOMs, {len(data["suppliers"])} suppliers)')

    with http.server.ThreadingHTTPServer(('', PORT), Handler) as httpd:
        print(f'Agnes server running on http://localhost:{PORT}')
        httpd.serve_forever()
