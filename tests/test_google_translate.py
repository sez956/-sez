import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlencode

import google_translate as google
import free_digest as digest


class GoogleTranslationTests(unittest.TestCase):
    def test_all_translated_segments_are_joined(self):
        response = [[['机器人可以操作物体。', 'Robots manipulate objects.', None],
                     ['代码公开。', 'Code is public.', None]], None, 'en']
        self.assertEqual(google.parse_translation(response), '机器人可以操作物体。代码公开。')
        for malformed in (None, {}, [], [[['ok'], [None]]], [[['']]]):
            with self.assertRaises(ValueError):
                google.parse_translation(malformed)

    def test_split_keeps_every_character_and_encoded_url_budget(self):
        original = ('Robot manipulation. ' * 140) + ('接触力与控制' * 500)
        chunks = google.split_text(original)
        self.assertEqual(''.join(chunks), original)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(urlencode({'q': chunk})) <= 4000 for chunk in chunks))

    def test_cache_avoids_requests_and_invalidates_on_abstract_change(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'cache.json'
            items = [{'abstract': 'A robot policy.'}]
            with patch.object(google.GoogleTranslator, 'translate', return_value='机器人策略。') as translated:
                stats, _ = google.translate_items(items, {'enabled': True}, cache)
                self.assertEqual(stats['translated'], 1)
                self.assertEqual(translated.call_count, 1)
            second = [{'abstract': 'A robot policy.'}]
            with patch.object(google.GoogleTranslator, 'translate', side_effect=AssertionError('must use cache')):
                stats, _ = google.translate_items(second, {'enabled': True}, cache)
            self.assertEqual(stats['cached'], 1)
            self.assertEqual(second[0]['abstract_zh'], '机器人策略。')
            with patch.object(google.GoogleTranslator, 'translate', return_value='新的机器人策略。'):
                stats, _ = google.translate_items([{'abstract': 'A new robot policy.'}], {'enabled': True}, cache)
            self.assertEqual(stats['translated'], 1)

    def test_http_429_stops_remaining_requests_and_keeps_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = Mock()
            opener.open.side_effect = HTTPError(google.ENDPOINT, 429, 'Too Many Requests', {}, None)
            items = [{'abstract': 'First robot.'}, {'abstract': 'Second robot.'}]
            original = copy.deepcopy(items)
            with patch.object(google, 'build_opener', return_value=opener):
                stats, warnings = google.translate_items(items, {'enabled': True}, Path(directory) / 'cache.json')
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(stats['requests'], 1)
            self.assertEqual(stats['failed'], 2)
            self.assertEqual([x['abstract'] for x in items], [x['abstract'] for x in original])
            self.assertTrue(all(x['translation_status'] == 'failed' for x in items))
            self.assertIn('429', warnings[0])
            self.assertFalse((Path(directory) / 'cache.json').exists())

    def test_disabled_translation_never_connects(self):
        items = [{'abstract': 'Original', 'abstract_zh': 'Old translation'}]
        with patch.object(google, 'build_opener', side_effect=AssertionError('must not connect')):
            stats, warnings = google.translate_items(items, {'enabled': False}, Path('unused.json'))
        self.assertFalse(stats['enabled'])
        self.assertEqual(warnings, [])
        self.assertNotIn('abstract_zh', items[0])

    def test_failed_later_chunk_does_not_cache_partial_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Mock()
            first.__enter__ = Mock(return_value=first)
            first.__exit__ = Mock(return_value=False)
            first.read.return_value = json.dumps([[['片段一', 'Part one']]]).encode('utf-8')
            opener = Mock()
            opener.open.side_effect = [first, TimeoutError('timeout')]
            items = [{'abstract': 'A robot sentence. ' * 30}]
            with patch.object(google, 'build_opener', return_value=opener), patch.object(google.time, 'sleep'):
                stats, _ = google.translate_items(items, {'enabled': True, 'chunk_chars': 100}, Path(directory) / 'cache.json')
            self.assertEqual(stats['failed'], 1)
            self.assertNotIn('abstract_zh', items[0])
            self.assertFalse((Path(directory) / 'cache.json').exists())

    def test_refresh_translates_existing_report_without_retrieval_or_history_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'max_items': 20, 'lookback_days': 7, 'page_size': 50, 'max_pages_per_query': 6,
                      'translation': {'enabled': True}}
            digest.dump(root / 'config.json', config)
            digest.dump(root / 'status.json', {'last_success_day': '2026-10-29'})
            history = {'2610.12345': {'fingerprint': 'keep', 'reported_at': '2026-10-29T09:00:00+08:00'}}
            digest.dump(root / 'history.json', history)
            item = {'title': 'Robot research', 'authors': ['Author'], 'id': '2610.12345',
                    'published': '2026-10-28T01:00:00Z', 'updated': '2026-10-28T01:00:00Z', 'announced': '',
                    'url': 'https://arxiv.org/abs/2610.12345', 'change': 'New', 'score': 10,
                    'reasons': [['robot', 10]], 'abstract': 'Original robot abstract.', 'comment': ''}
            digest.dump(root / 'reports' / '2026-10-29_090000.json', {
                'items': [item], 'coverage': ['arXiv'], 'warnings': [],
                'retrieved_at': '2026-10-29T09:00:00+08:00', 'candidates': 1})
            args = SimpleNamespace(config=root / 'config.json', output_dir=root, force=False, quiet=True, translate_latest=True)
            with patch.object(digest, 'collect', side_effect=AssertionError('must not search again')), \
                 patch.object(google.GoogleTranslator, 'translate', return_value='机器人研究原始摘要。'):
                self.assertEqual(digest.run(args), 0)
            report = (root / 'latest.md').read_text('utf-8')
            self.assertIn('机器人研究原始摘要。', report)
            self.assertIn('Original robot abstract.', report)
            self.assertIn('2026-10-29 09:00', report)
            self.assertEqual(json.loads((root / 'history.json').read_text('utf-8')), history)
            self.assertEqual(json.loads((root / 'status.json').read_text('utf-8'))['last_success_day'], '2026-10-29')


if __name__ == '__main__':
    unittest.main()
