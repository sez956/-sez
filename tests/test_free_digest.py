import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import free_digest as digest

NOW = datetime(2026, 10, 30, 9, tzinfo=timezone(timedelta(hours=8)))
CONFIG = {'max_items': 20, 'min_score': 7, 'lookback_days': 7}


def paper(identifier='2610.12345', days=0):
    return digest.finish({
        'id': identifier, 'title': 'Vision-Language-Action for robot manipulation',
        'abstract': 'A world model evaluated on real-world robots. Code is available.',
        'authors': ['Author'], 'published': (NOW - timedelta(days=days, hours=1)).isoformat(),
        'updated': (NOW - timedelta(days=days, hours=1)).isoformat(),
        'announced': '', 'comment': '', 'categories': ['cs.RO'], 'date_kind': 'metadata',
    })


class DigestTests(unittest.TestCase):
    def test_time_window_and_no_nonrobot_papers(self):
        old, future, unrelated = paper(days=8), paper('2610.10001', days=-2), paper('2610.10002')
        unrelated.update(title='A benchmark of language models', abstract='Dataset evaluation for text generation')
        selected, _ = digest.select([old, future, unrelated, paper('2610.10003')], {}, CONFIG, NOW)
        self.assertEqual([p['id'] for p in selected], ['2610.10003'])

    def test_no_minimum_and_twenty_maximum(self):
        self.assertEqual(digest.select([], {}, CONFIG, NOW)[0], [])
        self.assertEqual(len(digest.select([paper()], {}, CONFIG, NOW)[0]), 1)
        batch = [paper(f'2610.{10000+i}') for i in range(25)]
        self.assertEqual(len(digest.select(batch, {}, CONFIG, NOW)[0]), 20)

    def test_dedup_same_version_and_changed_abstract(self):
        original = paper()
        history = {original['id']: {'fingerprint': original['fingerprint']}}
        self.assertEqual(digest.select([original, copy.deepcopy(original)], history, CONFIG, NOW)[0], [])
        updated = copy.deepcopy(original)
        updated['abstract'] += ' New contact evaluation.'
        updated['updated'] = NOW.isoformat()
        digest.finish(updated)
        result, _ = digest.select([original, updated], history, CONFIG, NOW)
        self.assertEqual(len(result), 1)
        self.assertIn('版本更新', result[0]['change'])

    def test_atom_preserves_dates_and_abstract(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2610.12345v2</id><title> Robot VLA </title>
        <summary>Original abstract.</summary><published>2026-10-28T01:00:00Z</published>
        <updated>2026-10-29T01:00:00Z</updated><author><name>A</name></author>
        <category term="cs.RO"/></entry></feed>'''
        result = digest.parse_atom(xml)[0]
        self.assertEqual(result['id'], '2610.12345')
        self.assertEqual(result['abstract'], 'Original abstract.')
        self.assertEqual(result['published'], '2026-10-28T01:00:00Z')
        with self.assertRaises(ValueError):
            digest.parse_atom(b'<html>Blocked</html>')

    def test_rss_announcement_is_not_first_publication(self):
        xml = b'''<rss><channel><pubDate>Thu, 29 Oct 2026 20:00:00 GMT</pubDate><item>
        <title>A Robot</title><link>https://arxiv.org/abs/2610.12345</link>
        <description>arXiv:2610.12345 Announce Type: new. Abstract: Original abstract.</description>
        </item></channel></rss>'''
        result = digest.parse_rss(xml)[0]
        self.assertEqual(result['published'], '')
        self.assertEqual(result['abstract'], 'Original abstract.')
        self.assertIsNotNone(digest.date(result['announced']))
        with self.assertRaises(ValueError):
            digest.parse_rss(xml.replace(b'<pubDate>Thu, 29 Oct 2026 20:00:00 GMT</pubDate>', b''))

    def test_html_escapes_untrusted_abstract(self):
        page = digest.html_page('# Paper\n<script>alert(1)</script>\n[Source](https://arxiv.org/abs/2610.12345)')
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('href="https://arxiv.org/abs/2610.12345"', page)

    def test_empty_rss_cannot_hide_total_api_failure(self):
        config = dict(CONFIG, queries=['cat:cs.RO'], page_size=50, max_pages_per_query=1,
                      rss_fallback='https://rss.arxiv.org/rss/cs.RO', request_interval_seconds=3.2)
        def failed_api(url, parser):
            if 'api/query' in url:
                raise RuntimeError('API blocked')
            return []
        with patch.object(digest.Client, 'parsed', side_effect=failed_api):
            with self.assertRaises(RuntimeError):
                digest.collect(config, NOW)

    def test_total_network_failure_preserves_last_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = dict(CONFIG, page_size=200, max_pages_per_query=3)
            (root / 'config.json').write_text(json.dumps(config), encoding='utf-8')
            (root / 'latest.html').write_text('Previous successful report', encoding='utf-8')
            args = SimpleNamespace(config=root / 'config.json', output_dir=root, force=True, quiet=True)
            with patch.object(digest, 'collect', side_effect=RuntimeError('Network unavailable')):
                self.assertEqual(digest.run(args), 1)
            self.assertEqual((root / 'latest.html').read_text('utf-8'), 'Previous successful report')
            self.assertEqual(json.loads((root / 'status.json').read_text('utf-8'))['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
