"""Zero-model arXiv digest. Python standard library; no GPT, API key or Codex."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

from google_translate import manual_url, translate_items

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
ATOM = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom',
        'o': 'http://a9.com/-/spec/opensearch/1.1/'}
RULES = [
    ('VLA / 机器人基础模型', r'vision[\s-]+language[\s-]+action|\bvla\b|robot foundation|generalist robot', 8),
    ('具身世界模型', r'world model|world[\s-]+action|physical dynamics', 5),
    ('操作与灵巧手', r'manipulation|dexterous|grasping|visuomotor', 4),
    ('具身导航与移动操作', r'embodied navigation|robot navigation|mobile manipulation|visual navigation', 4),
    ('人形与运动控制', r'humanoid|legged|locomotion|whole[\s-]+body', 4),
    ('机器人数据与评测', r'dataset|benchmark|evaluation suite', 3),
    ('机器人学习与迁移', r'imitation learning|reinforcement learning|sim[\s-]+to[\s-]+real|diffusion polic', 2),
    ('摘要提及实机/现实实验（未核验）', r'real[\s-]+world|real[\s-]+robot|physical robot|hardware experiment', 3),
    ('摘要提及开放材料（未核验）', r'open[\s-]+source|github\.com|code (?:is |and .*?)(?:available|released)', 1),
]
ROBOT_ANCHOR = re.compile(r'robot|embodied|humanoid|dexterous|locomotion|visuomotor|vision[\s-]+language[\s-]+action|mobile manipulation', re.I)


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def dump(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path, default):
    return json.loads(path.read_text('utf-8')) if path.exists() else default


def date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        result = parsedate_to_datetime(value)
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def compact(value):
    return ' '.join((value or '').split())


def paper_id(value):
    match = re.search(r'(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?', value)
    if not match:
        raise ValueError('无法解析 arXiv ID：' + value[:100])
    return match.group(1)


def finish(paper):
    paper['url'] = 'https://arxiv.org/abs/' + paper['id']
    paper['fingerprint'] = hashlib.sha256((paper['title'] + paper['abstract'] + paper.get('comment', '')).encode()).hexdigest()
    return paper


def parse_atom(payload):
    root = ET.fromstring(payload)
    if root.tag != '{http://www.w3.org/2005/Atom}feed':
        raise ValueError('API 未返回有效的 Atom feed')
    papers = []
    for entry in root.findall('a:entry', ATOM):
        identifier = entry.findtext('a:id', '', ATOM)
        if '/errors' in identifier:
            raise ValueError(entry.findtext('a:summary', 'arXiv API error', ATOM))
        paper = {
            'id': paper_id(identifier), 'title': compact(entry.findtext('a:title', '', ATOM)),
            'abstract': compact(entry.findtext('a:summary', '', ATOM)),
            'authors': [compact(x.findtext('a:name', '', ATOM)) for x in entry.findall('a:author', ATOM)],
            'published': entry.findtext('a:published', '', ATOM),
            'updated': entry.findtext('a:updated', '', ATOM),
            'announced': '', 'date_kind': '论文元数据',
            'comment': compact(entry.findtext('x:comment', '', ATOM)),
            'categories': [x.get('term', '') for x in entry.findall('a:category', ATOM)],
        }
        if not paper['title'] or not paper['abstract'] or not date(paper['updated']):
            raise ValueError('论文缺少标题、摘要或更新时间')
        papers.append(finish(paper))
    return papers


def parse_rss(payload):
    root = ET.fromstring(payload)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('RSS 返回内容无效')
    channel = root.find('channel')
    feed_date = channel.findtext('pubDate', '') or channel.findtext('lastBuildDate', '')
    papers = []
    for item in channel.findall('item'):
        description = html.unescape(item.findtext('description', ''))
        # RSS includes an announcement preamble; keep only the author abstract.
        description = re.sub(r'^.*?Abstract:\s*', '', description, flags=re.S)
        abstract = compact(re.sub(r'<[^>]*>', ' ', description))
        dc = '{http://purl.org/dc/elements/1.1/}'
        announced = item.findtext('pubDate', '') or item.findtext(dc + 'date', '') or feed_date
        if not date(announced):
            raise ValueError('RSS 未提供公告日期，无法安全筛选新成果')
        papers.append(finish({
            'id': paper_id(item.findtext('link', '') or item.findtext('guid', '')),
            'title': compact(item.findtext('title', '')), 'abstract': abstract,
            'authors': [compact(item.findtext(dc + 'creator', '未提供'))],
            'published': '', 'updated': '', 'announced': announced, 'date_kind': 'RSS 公告时间（非首次发表日期）',
            'comment': '', 'categories': [x.text or '' for x in item.findall('category')],
        }))
    return papers


def rank(paper, now):
    text = paper['title'] + ' ' + paper['abstract']
    if not ROBOT_ANCHOR.search(text):
        return 0, []
    reasons = [(name, weight) for name, pattern, weight in RULES if re.search(pattern, text, re.I)]
    event = date(paper['updated'] or paper['announced'])
    if event and timedelta(0) <= now - event <= timedelta(days=1):
        reasons.append(('最近 24 小时发布/更新或公告', 1))
    return sum(weight for _, weight in reasons), reasons


def select(papers, history, config, now):
    recent = now - timedelta(days=config['lookback_days'])
    unique = {}
    for paper in papers:
        event = date(paper['updated'] or paper['announced'])
        if event is None or event < recent or event > now:
            continue
        old = unique.get(paper['id'])
        if old is None or event > date(old['updated'] or old['announced']):
            unique[paper['id']] = paper
    chosen = []
    for paper in unique.values():
        previous = history.get(paper['id'], {})
        if previous.get('fingerprint') == paper['fingerprint']:
            continue
        score, reasons = rank(paper, now)
        if score < config['min_score']:
            continue
        item = dict(paper, score=score, reasons=reasons)
        item['change'] = '新发现论文'
        if paper['updated'] and paper['published'] and date(paper['updated']) > date(paper['published']):
            item['change'] = '版本更新；未核对全文差异，不代表实质进展'
        if now - date(paper['updated'] or paper['announced']) > timedelta(days=1):
            item['change'] += '；最近 7 天补录/初次回顾'
        chosen.append(item)
    chosen.sort(key=lambda p: (p['score'], date(p['updated'] or p['announced'])), reverse=True)
    return chosen[:config['max_items']], len(unique)


class Client:
    def __init__(self, config):
        self.config = config
        proxy = config.get('proxy') or os.environ.get('DIGEST_PROXY', '')
        self.opener = build_opener(ProxyHandler({'http': proxy, 'https': proxy})) if proxy else build_opener()
        self.last = 0.0

    def fetch(self, url):
        for attempt in range(2):
            pause = max(0, self.config['request_interval_seconds'] - (time.monotonic() - self.last))
            time.sleep(pause)
            self.last = time.monotonic()
            try:
                request = Request(url, headers={'User-Agent': 'EmbodiedAI-Digest/2.0 (+https://github.com/sez956/-sez)'})
                with self.opener.open(request, timeout=self.config['timeout_seconds']) as response:
                    data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise ValueError('来源响应超过 8MB，已停止读取')
                return data
            except HTTPError as exc:
                if attempt == 0 and exc.code in (429, 500, 502, 503, 504):
                    try:
                        delay = min(60, max(4, int(exc.headers.get('Retry-After', 4))))
                    except ValueError:
                        delay = 4
                    time.sleep(delay)
                else:
                    raise

    def parsed(self, url, parser):
        # A proxy may return a truncated XML body with HTTP 200. Retry with the
        # same rate limit, then surface the failure instead of treating it as empty.
        for attempt in range(2):
            try:
                return parser(self.fetch(url))
            except ET.ParseError:
                if attempt:
                    raise


def collect(config, now):
    client, papers, coverage, warnings = Client(config), [], [], []
    successes = 0
    cutoff = now - timedelta(days=config['lookback_days'])
    for query in config['queries']:
        count = 0
        try:
            for page in range(config['max_pages_per_query']):
                params = {'search_query': query, 'sortBy': 'lastUpdatedDate', 'sortOrder': 'descending',
                          'start': page * config['page_size'], 'max_results': config['page_size']}
                batch = client.parsed('https://export.arxiv.org/api/query?' + urlencode(params), parse_atom)
                papers.extend(batch)
                count += len(batch)
                if len(batch) < config['page_size'] or (batch and min(date(p['updated']) for p in batch) < cutoff):
                    break
            else:
                warnings.append('达到分页上限，可能遗漏较早候选：' + query)
            successes += 1
            coverage.append(f'arXiv API：{query}；读取 {count} 条元数据。')
        except Exception as exc:
            warnings.append(f'arXiv API 查询失败：{query}；{type(exc).__name__}: {exc}')
            if count:
                successes += 1
                coverage.append(f'arXiv API：{query}；已读取 {count} 条，后续分页失败，覆盖受限。')
    if successes < len(config['queries']):
        try:
            batch = client.parsed(config['rss_fallback'], parse_rss)
            papers.extend(batch)
            if batch:
                successes += 1
            coverage.append(f'RSS 备用源：读取 {len(batch)} 条；只提供公告窗口，不保证补全最近 7 天。')
        except Exception as exc:
            warnings.append(f'RSS 备用源失败：{type(exc).__name__}: {exc}')
    if not successes:
        raise RuntimeError('全部公开来源检索失败；不能据此判断没有新论文。\n' + '\n'.join(warnings))
    return papers, coverage, warnings


def display_date(value):
    return date(value).astimezone(TZ).strftime('%Y-%m-%d %H:%M（北京时间）') if value else '来源未提供'


def markdown(items, now, candidates, coverage, warnings):
    lines = [f'# 具身智能论文日报｜{now:%Y-%m-%d}｜免模型版', '',
             f'检索截止：{now:%Y-%m-%d %H:%M}（北京时间）；最近 7 天滚动补漏，历史去重。',
             f'有效窗口内候选 {candidates} 篇，按规则选入 {len(items)} 篇，最多 20 篇，不设最低数量。', '',
             '**本报告未调用 GPT 或 Codex。评分是关键词相关性与线索排序，不是学术质量评审；中文摘要若存在，为 Google 网页接口机器翻译，术语与指标应对照保留的原文；未核对全文或独立验证实验。**', '',
             '状态：' + ('部分来源或翻译受限' if warnings else ('检索完成' if items else '无达到筛选阈值的新增论文')), '']
    if not items:
        lines += [('本次未选入论文；来源覆盖受限，不能判断是否没有重要新增。' if warnings
                   else '本次没有达到规则阈值且未报道的论文；不使用旧文凑数。'), '']
    for i, p in enumerate(items, 1):
        lines += [f"## {i}. {p['title']}", '', f"作者：{', '.join(p['authors'])}",
                  f"首次提交：{display_date(p['published'])}", f"版本更新：{display_date(p['updated'])}"]
        if p['announced']:
            lines.append('RSS 公告：' + display_date(p['announced']) + '；不能据此认定首次发表时间。')
        lines += [p['change'], '', f"规则分：{p['score']}；" + '；'.join(f'{name} +{weight}' for name, weight in p['reasons']), '',
                  f"[论文原页]({p['url']})", '']
        if p.get('abstract_zh'):
            lines += ['**中文摘要（Google 机器翻译，未人工校对）**', '', p['abstract_zh'], '']
        elif p.get('translation_status') == 'failed':
            lines += ['**中文翻译暂不可用，原文已保留**：' + p.get('translation_error', ''), '']
        elif p.get('translation_status') == 'disabled':
            lines += ['中文摘要翻译未启用。', '']
        lines += ['**作者原始摘要（未核验）**', '', p['abstract'], '',
                  f"[打开 Google 翻译（长摘要请复制原文）]({manual_url(p['abstract'])})", '']
        if p.get('comment'):
            lines += ['作者备注：' + p['comment'], '']
        urls = re.findall(r'https?://[^\s<>]+', p['abstract'] + ' ' + p.get('comment', ''))
        for url in dict.fromkeys(u.rstrip('.,;)') for u in urls):
            lines += [f'- [摘要/备注中的外链（未核验）]({url})']
    lines += ['## 检索覆盖', ''] + ['- ' + x for x in coverage]
    lines += ['', '## 限制与失败来源', '']
    lines += ['- ' + x for x in warnings]
    lines += ['- 仅覆盖配置中的 arXiv 论文与备用公告；不覆盖所有机构新闻、会议独立发布和仓库新版本。',
              '- 规则可能漏掉没有常见关键词的重要论文，也可能选入措辞匹配但价值一般的论文。',
              '- 版本变化仅依据元数据和摘要/备注变化，不证明新增了有效结果；完整学术判断需要人工或模型精读。',
              '- 这是一份候选文献汇总；作者摘要中的指标和实机声明均尚未核验。', '']
    return '\n'.join(lines)


def html_page(text):
    parts = []
    for line in text.splitlines():
        safe = html.escape(line)
        safe = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', safe)
        safe = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', safe)
        if line.startswith('# '):
            parts.append('<h1>' + safe[2:] + '</h1>')
        elif line.startswith('## '):
            parts.append('<h2>' + safe[3:] + '</h2>')
        elif line:
            parts.append('<p>' + safe + '</p>')
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>具身智能日报 · 免模型版</title><style>body{max-width:960px;margin:40px auto;padding:0 24px;font:16px/1.9 system-ui,sans-serif;color:#233449;background:#fafbfd}h1{font-size:28px}h2{margin-top:35px;border-top:1px solid #ddd;padding-top:22px;font-size:22px}a{color:#1765ad;overflow-wrap:anywhere}p{overflow-wrap:anywhere}</style>' + '\n'.join(parts) + '</html>'


@contextmanager
def run_lock(path):
    with path.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def notify(success, output):
    if os.name == 'nt':
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-WindowStyle', 'Hidden', '-File', str(ROOT / 'notify.ps1'),
                        '-Result', 'success' if success else 'failed', '-ReportPath', str(output / 'latest.html'),
                        '-StatusPath', str(output / 'status.json')], check=False, timeout=25,
                       creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(args):
    config = read_json(args.config, {})
    if not 1 <= config.get('max_items', 0) <= 20 or not 1 <= config.get('lookback_days', 0) <= 30:
        raise ValueError('max_items 需在 1–20，lookback_days 需在 1–30')
    if not 1 <= config.get('page_size', 0) <= 200 or not 1 <= config.get('max_pages_per_query', 0) <= 10:
        raise ValueError('分页参数无效')
    config['request_interval_seconds'] = max(3.2, config.get('request_interval_seconds', 3.2))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with run_lock(output / '.run.lock') as acquired:
        if not acquired:
            print('已有免模型版任务正在运行，跳过本次。')
            return 0
        now = datetime.now(TZ)
        state = read_json(output / 'status.json', {})
        refresh_translation = getattr(args, 'translate_latest', False)
        if not args.force and not refresh_translation and state.get('last_success_day') == now.strftime('%Y-%m-%d'):
            print('今日免模型日报已经生成。')
            return 0
        try:
            history = read_json(output / 'history.json', {})
            history = {key: value for key, value in history.items() if date(value['reported_at']) >= now - timedelta(days=30)}
            dump(output / 'status.json', dict(state, status='running', started_at=now.isoformat(), engine='rules-no-model'))
            if refresh_translation:
                saved = sorted((output / 'reports').glob('*.json'))
                if not saved:
                    raise RuntimeError('还没有日报，请先正常运行一次，再使用 --translate-latest。')
                bundle = read_json(saved[-1], {})
                items = bundle['items']
                candidates = bundle.get('candidates', len(items))
                coverage = bundle['coverage']
                source_warnings = bundle.get('source_warnings', bundle['warnings'])
                retrieved_at = date(bundle.get('retrieved_at')) or datetime.strptime(saved[-1].stem, '%Y-%m-%d_%H%M%S').replace(tzinfo=TZ)
            else:
                papers, coverage, source_warnings = collect(config, now)
                items, candidates = select(papers, history, config, now)
                retrieved_at = datetime.now(TZ)
            translation, translation_warnings = translate_items(
                items, config.get('translation', {}), output / 'translation_cache.json',
                config.get('proxy') or os.environ.get('DIGEST_PROXY', ''))
            warnings = source_warnings + translation_warnings
            # Record the actual completion time instead of claiming retrieval ended at startup.
            completed = datetime.now(TZ)
            report = markdown(items, retrieved_at, candidates, coverage, warnings)
            if translation['enabled']:
                report += (f"\n## 摘要翻译\n\nGoogle 网页翻译：新译 {translation['translated']} 篇，"
                           f"复用缓存 {translation['cached']} 篇，失败 {translation['failed']} 篇；"
                           "无需 API Key，不调用 GPT。非官方接口可能受限；译文仅供阅读辅助，原文始终保留。\n")
            page = html_page(report)
            stamp = now.strftime('%Y-%m-%d_%H%M%S')
            dump(output / 'reports' / (stamp + '.json'), {'engine': 'rules-no-model', 'items': items, 'coverage': coverage,
                 'warnings': warnings, 'source_warnings': source_warnings, 'translation': translation,
                 'retrieved_at': retrieved_at.isoformat(), 'candidates': candidates})
            atomic(output / 'reports' / (stamp + '.md'), report)
            atomic(output / 'reports' / (stamp + '.html'), page)
            atomic(output / 'latest.md', report)
            atomic(output / 'latest.html', page)
            if output == (ROOT / 'outputs' / 'free').resolve():
                atomic(ROOT / '最新日报.html', page)
            if not refresh_translation:
                for paper in items:
                    history[paper['id']] = {'fingerprint': paper['fingerprint'], 'reported_at': now.isoformat()}
                dump(output / 'history.json', history)
            dump(output / 'status.json', {'status': 'partial' if warnings else ('ok' if items else 'no_updates'),
                                        'engine': 'rules-no-model', 'translation': translation,
                                        'last_success_day': state.get('last_success_day') if refresh_translation else now.strftime('%Y-%m-%d'),
                                        'finished_at': completed.isoformat(), 'count': len(items), 'report': str(output / 'latest.html')})
            summary = os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary, 'a', encoding='utf-8') as stream:
                    stream.write(report)
            if not args.quiet:
                try:
                    notify(True, output)
                except Exception as exc:
                    atomic(output / 'notification-error.txt', str(exc))
            print(f'免模型日报已生成：{len(items)} 篇；{output / "latest.html"}')
            return 0
        except Exception as exc:
            dump(output / 'status.json', dict(state, status='failed', engine='rules-no-model',
                                             failed_at=datetime.now(TZ).isoformat(), error=str(exc)))
            if not args.quiet:
                try:
                    notify(False, output)
                except Exception:
                    pass
            print(str(exc), file=sys.stderr)
            return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.free.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'free')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--translate-latest', action='store_true', help='只翻译最近一期已有日报，不重新检索或改变去重历史')
    sys.exit(run(parser.parse_args()))
