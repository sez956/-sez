"""Local daily research digest. Standard library only; no API key storage."""
from __future__ import annotations

import argparse
import ctypes
import html
import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))


def write(path, content):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(content, encoding='utf-8')
    temp.replace(path)


def save_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2))


def canonical(url):
    p = urlsplit(url)
    if p.scheme not in ('https', 'http') or not p.netloc:
        raise ValueError('来源必须为有效的 HTTP(S) 链接')
    host = p.netloc.lower()
    path = p.path.rstrip('/')
    if host in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
        path = re.sub(r'^/(pdf|html)/', '/abs/', path)
        path = re.sub(r'v\d+$', '', path.removesuffix('.pdf'))
        host = 'arxiv.org'
    return urlunsplit(('https', host, path, '', ''))


def codex_executable():
    base = Path(os.environ['LOCALAPPDATA']) / 'OpenAI' / 'Codex' / 'bin'
    candidates = list(base.glob('*/codex.exe'))
    if not candidates:
        raise RuntimeError('找不到桌面应用附带的 Codex，请更新或修复应用。')
    return max(candidates, key=lambda p: p.stat().st_mtime)


def render(data, started, window):
    status = {'ok': '检索完成', 'no_updates': '无重要新增', 'partial': '部分来源未能核验', 'search_failed': '检索失败'}[data['status']]
    lines = [f'# 具身智能成果日报｜{started:%Y-%m-%d}', '',
             f'北京时间：{started:%Y-%m-%d %H:%M} 开始，{datetime.now(TZ):%H:%M} 完成',
             f'检索窗口：{window:%Y-%m-%d %H:%M} 至 {started:%Y-%m-%d %H:%M}（北京时间）',
             f'状态：{status}', '', data['overview'], '', '## 今日重点', '']
    lines += ['- ' + x for x in data['highlights']]
    for i, item in enumerate(data['items'], 1):
        lines += ['', f"## {i}. {item['title']}", '',
                  f"机构：{item['organization']}  |  日期：{item['date']}", '']
        for label, key in [('本次新增', 'change'), ('研究问题', 'problem'), ('核心方法', 'method'),
                           ('结果与条件', 'evidence'), ('局限', 'limitations'), ('验证状态', 'verification'),
                           ('开源情况', 'availability'), ('阅读价值', 'why_read')]:
            lines += [f'**{label}**：{item[key]}', '']
        lines += [f"- [{s['label']}]({s['url']})" for s in item['sources']]
    for label, key in [('精读候选（供人工选择）', 'reading'), ('可验证的研究问题', 'research_questions'),
                       ('检索覆盖', 'coverage'), ('不确定性与遗漏', 'uncertainties')]:
        lines += ['', '## ' + label, ''] + ['- ' + x for x in data[key]]
    lines += ['', '---', '原始证据以链接中的论文和官方发布为准。每日 09:00 开始检索，完成后本机通知。', '']
    return '\n'.join(lines)


def render_html(markdown):
    # Escape every source string before turning a small Markdown subset into HTML.
    out = []
    for line in markdown.splitlines():
        line = html.escape(line)
        line = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', line)
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        if line.startswith('# '):
            out.append('<h1>' + line[2:] + '</h1>')
        elif line.startswith('## '):
            out.append('<h2>' + line[3:] + '</h2>')
        elif line.startswith('- '):
            out.append('<p class="bullet">• ' + line[2:] + '</p>')
        elif line:
            out.append('<p>' + line + '</p>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>具身智能成果日报</title><style>body{font:17px/1.85 "Microsoft YaHei",sans-serif;max-width:900px;margin:44px auto;padding:0 28px;color:#203040;background:#fafbfd}h1{font-size:30px;line-height:1.4}h2{font-size:23px;border-top:1px solid #dbe1e8;padding-top:25px;margin-top:36px}a{color:#1264b2;overflow-wrap:anywhere}p{margin:10px 0}.bullet{padding-left:12px}strong{color:#142b4c}</style>''' + '\n'.join(out) + '</html>'


def notify(success):
    script = ROOT / 'notify.ps1'
    if script.exists():
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-WindowStyle', 'Hidden', '-File', str(script), '-Result', 'success' if success else 'failed'],
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=25, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(force=False, quiet=False):
    started = datetime.now(TZ)
    logs, reports = ROOT / '日志', ROOT / '日报'
    logs.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    # Kernel releases the lock after crashes; overlapping manual and scheduled runs are skipped.
    with (ROOT / '.run.lock').open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return 0
        state_path = ROOT / '运行状态.json'
        previous = json.loads(state_path.read_text('utf-8')) if state_path.exists() else {}
        if not force and previous.get('last_success_day') == started.strftime('%Y-%m-%d'):
            return 0
        history_path = ROOT / '已报道.json'
        history = json.loads(history_path.read_text('utf-8')) if history_path.exists() else []
        history = [x for x in history if x['reported_at'] >= (started - timedelta(days=30)).isoformat()]
        first_run = not previous.get('last_success_day')
        window = started - timedelta(days=7 if first_run else 1)
        stamp = started.strftime('%Y-%m-%d_%H%M%S')
        result_path = logs / (stamp + '.result.json')
        save_json(state_path, dict(previous, status='running', started_at=started.isoformat()))
        try:
            prompt = (ROOT / 'prompt.md').read_text('utf-8') + '\n\n' + (ROOT / 'workflow.md').read_text('utf-8')
            context = {'北京时间': started.isoformat(), '窗口开始': window.isoformat(),
                       '首次运行': first_run, '近30天已报道': history[-400:]}
            prompt += '\n\n本次上下文：\n' + json.dumps(context, ensure_ascii=False)
            args = [str(codex_executable()), '--no-daemon', '--search', '-a', 'never',
                    '--disable', 'shell_tool', '--disable', 'multi_agent', '--disable', 'apps',
                    '--disable', 'plugins', 'exec', '--ignore-user-config',
                    '-m', 'gpt-6.1-sol', '-s', 'read-only', '--skip-git-repo-check',
                    '-C', str(ROOT), '--color', 'never', '--json',
                    '--output-schema', str(ROOT / 'report.schema.json'),
                    '--output-last-message', str(result_path), '-']
            env = {k: v for k, v in os.environ.items() if k not in ('CODEX_THREAD_ID', 'CODEX_TURN_ID')}
            with (logs / (stamp + '.jsonl')).open('w', encoding='utf-8') as log:
                process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=log, stderr=log,
                                           text=True, encoding='utf-8', env=env,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    process.communicate(prompt, timeout=2400)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
                    raise RuntimeError('检索超过 40 分钟，已结束本次运行；详见日志。')
            if process.returncode != 0 or not result_path.exists():
                raise RuntimeError(f'Codex 执行失败，退出码 {process.returncode}，详见 日志/{stamp}.jsonl')
            data = json.loads(result_path.read_text('utf-8'))
            if data['status'] == 'search_failed':
                raise RuntimeError('联网检索失败：' + data['overview'])
            if len(data['items']) > 20 or (data['status'] == 'no_updates' and data['items']):
                raise ValueError('日报状态或条目数量无效')
            if data['status'] == 'ok' and not data['items']:
                raise ValueError('成功状态缺少成果条目')
            for item in data['items']:
                if not item['sources']:
                    raise ValueError('成果缺少原始来源')
                for source in item['sources']:
                    canonical(source['url'])
            markdown = render(data, started, window)
            page = render_html(markdown)
            write(reports / (stamp + '.md'), markdown)
            write(reports / (stamp + '.html'), page)
            write(ROOT / '最新日报.html', page)
            for item in data['items']:
                for source in item['sources']:
                    history.append({'title': item['title'], 'url': canonical(source['url']),
                                    'reported_at': started.isoformat()})
            unique = {x['url']: x for x in history}
            save_json(history_path, list(unique.values()))
            save_json(state_path, {'status': data['status'], 'started_at': started.isoformat(),
                                  'finished_at': datetime.now(TZ).isoformat(), 'last_success_day': started.strftime('%Y-%m-%d'),
                                  'item_count': len(data['items']), 'report': str(reports / (stamp + '.md')),
                                  'latest': str(ROOT / '最新日报.html')})
            if not quiet:
                try:
                    notify(True)
                except Exception as notification_error:
                    (logs / (stamp + '.notification.txt')).write_text(str(notification_error), encoding='utf-8')
            print(json.dumps({'status': data['status'], 'count': len(data['items']), 'report': str(ROOT / '最新日报.html')}, ensure_ascii=False))
            return 0
        except Exception as exc:
            save_json(state_path, dict(previous, status='failed', started_at=started.isoformat(),
                                      failed_at=datetime.now(TZ).isoformat(), error=str(exc)))
            (logs / (stamp + '.error.txt')).write_text(str(exc), encoding='utf-8')
            if not quiet:
                try:
                    notify(False)
                except Exception:
                    pass
            print(str(exc), file=sys.stderr)
            return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='同一天重新生成')
    parser.add_argument('--quiet', action='store_true', help='不发送桌面通知')
    options = parser.parse_args()
    sys.exit(run(options.force, options.quiet))
