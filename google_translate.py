"""Optional, keyless Google web translation. No Cloud API billing or GPT calls.

This consumer endpoint is undocumented and can reject requests. Never switch
domains/proxies to evade limits; stop the current batch on HTTP 403/429.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

ENDPOINT = 'https://translate.googleapis.com/translate_a/single'
PROVIDER = 'google-web-unofficial-v1'


def split_text(text, limit=1200):
    """Keep every character, preferring sentence boundaries within URL limits."""
    if not 100 <= limit <= 2500:
        raise ValueError('translation.chunk_chars 需在 100–2500')
    chunks = []
    remaining = text
    while remaining:
        size = min(limit, len(remaining))
        while len(urlencode({'q': remaining[:size]})) > 4000:
            size = max(1, size * 4 // 5)
        if size < len(remaining):
            boundaries = list(re.finditer(r'(?<=[.!?。！？])\s+', remaining[:size]))
            end = boundaries[-1].end() if boundaries else remaining.rfind(' ', 0, size) + 1
            if end >= size // 2:
                size = end
        chunks.append(remaining[:size])
        remaining = remaining[size:]
    return chunks


def parse_translation(payload):
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list) or not payload[0]:
        raise ValueError('Google 翻译响应格式无效')
    parts = []
    for row in payload[0]:
        if not isinstance(row, list) or not row or not isinstance(row[0], str):
            raise ValueError('Google 翻译句段缺失，未保存不完整译文')
        parts.append(row[0])
    text = ''.join(parts).strip()
    if not text:
        raise ValueError('Google 翻译返回空译文')
    return text


class GoogleTranslator:
    def __init__(self, settings, proxy=''):
        self.settings = settings
        self.target = settings.get('target_language', 'zh-CN')
        self.timeout = max(1, min(30, settings.get('timeout_seconds', 12)))
        self.interval = max(1, settings.get('request_interval_seconds', 1.5))
        self.chunk_chars = settings.get('chunk_chars', 1200)
        self.opener = build_opener(ProxyHandler({'http': proxy, 'https': proxy})) if proxy else build_opener()
        self.last = 0.0
        self.requests = 0
        self.stopped = ''

    def key(self, text):
        return hashlib.sha256(json.dumps([PROVIDER, 'auto', self.target, text], ensure_ascii=False).encode('utf-8')).hexdigest()

    def translate(self, text):
        if self.stopped:
            raise RuntimeError(self.stopped)
        try:
            translated = []
            for chunk in split_text(text, self.chunk_chars):
                time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
                self.last = time.monotonic()
                params = {'client': 'gtx', 'sl': 'auto', 'tl': self.target, 'dt': 't', 'q': chunk}
                request = Request(ENDPOINT + '?' + urlencode(params),
                                  headers={'User-Agent': 'EmbodiedAI-Digest/2.1 (+https://github.com/sez956/-sez)'})
                self.requests += 1
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError('Google 翻译响应超过大小限制')
                translated.append(parse_translation(json.loads(body)))
            if not translated:
                raise ValueError('摘要为空，无需翻译')
            return '\n'.join(translated)
        except HTTPError as exc:
            if exc.code in (403, 429):
                self.stopped = f'Google 翻译返回 HTTP {exc.code}（拒绝或限流），本轮停止后续请求；稍后再试或使用手动入口。'
            else:
                self.stopped = f'Google 翻译返回 HTTP {exc.code}，本轮停止后续请求。'
            exc.close()
            raise RuntimeError(self.stopped) from exc
        except Exception as exc:
            self.stopped = f'Google 翻译暂不可用（{type(exc).__name__}），本轮停止后续请求。'
            raise RuntimeError(self.stopped) from exc


def translate_items(items, settings, cache_path, proxy=''):
    """Translate only selected abstracts; cache only complete successful results."""
    enabled = settings.get('enabled', False)
    stats = {'enabled': enabled, 'provider': PROVIDER, 'translated': 0, 'cached': 0,
             'failed': 0, 'requests': 0, 'target_language': settings.get('target_language', 'zh-CN')}
    if not enabled or not items:
        for item in items:
            item.pop('abstract_zh', None)
            item['translation_status'] = 'disabled'
            item.pop('translation_error', None)
        return stats, []
    translator = GoogleTranslator(settings, proxy)
    cache_path = Path(cache_path)
    try:
        cache = json.loads(cache_path.read_text('utf-8')) if cache_path.exists() else {}
        if not isinstance(cache, dict):
            cache = {}
    except (ValueError, OSError):
        cache = {}
    warnings = []
    for item in items:
        item.pop('abstract_zh', None)
        item.pop('translation_error', None)
        text = item['abstract']
        key = translator.key(text)
        cached = cache.get(key)
        if isinstance(cached, dict) and isinstance(cached.get('text'), str) and cached['text'].strip():
            item.update(abstract_zh=cached['text'], translation_status='cached', translation_provider=PROVIDER)
            stats['cached'] += 1
            continue
        try:
            result = translator.translate(text)
            item.update(abstract_zh=result, translation_status='translated', translation_provider=PROVIDER)
            cache[key] = {'text': result, 'provider': PROVIDER, 'target_language': translator.target}
            stats['translated'] += 1
        except Exception as exc:
            item.update(translation_status='failed', translation_error=str(exc))
            stats['failed'] += 1
            if not warnings:
                warnings.append(str(exc))
    stats['requests'] = translator.requests
    if stats['translated']:
        # Limit local cache growth without changing report history/dedup rules.
        cache = dict(list(cache.items())[-2000:])
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(cache_path)
        except OSError:
            warnings.append('Google 译文已生成，但本地翻译缓存无法保存。')
    return stats, warnings


def manual_url(text):
    params = {'sl': 'auto', 'tl': 'zh-CN', 'op': 'translate'}
    # Keep links usable when an unusually long abstract exceeds browser URL limits.
    if len(urlencode({'text': text})) <= 6000:
        params['text'] = text
    return 'https://translate.google.com/?' + urlencode(params)
