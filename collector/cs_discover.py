"""Supplement indexed search with public realtime links, never excerpt facts."""
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape


def candidate_urls(html, account):
    # Accept only exact organizer status URLs. Search excerpts are not results.
    pattern = r'https://(?:x|twitter)\.com/(' + re.escape(account) + r')/status/(\d+)'
    posts = {m[1]: f'https://x.com/{account}/status/{m[1]}'
             for m in re.findall(pattern, unescape(html), re.I)}
    return [posts[k] for k in sorted(posts, key=int, reverse=True)[:12]]


def fetch_html(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'WSResultsWatch/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(2_000_000).decode('utf-8')


def discover_cs(config, fetch=fetch_html):
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    report = dict(id='cs_discovery', name='CS投稿URLの補助収集',
                  url='https://search.yahoo.co.jp/realtime', checkedAt=stamp,
                  status='ok', count=0, requests=0, errors=[], organizers=[])
    posts = config.setdefault('posts', [])
    known = {p['url'].rsplit('/', 1)[-1] for p in posts}
    for organizer in config.get('csOrganizers', [])[:10]:
        name = organizer.get('discoveryQuery', organizer['name'])
        url = 'https://search.yahoo.co.jp/realtime/search?' + urllib.parse.urlencode(dict(p=name, ei='UTF-8'))
        report['requests'] += 1
        try:
            html = fetch(url)
            if 'リアルタイム検索' not in html:
                raise ValueError('Unexpected search response')
            urls = candidate_urls(html, organizer['account'])
            report['organizers'].append(dict(name=organizer['name'], urls=urls))
            for candidate in urls:
                post_id = candidate.rsplit('/', 1)[-1]
                if post_id in known: continue
                posts.append(dict(url=candidate, eventKind='cs', discoveredAt=stamp,
                                  discoveredVia=url))
                known.add(post_id)
                report['count'] += 1
        except Exception as error:
            report['errors'].append(dict(name=organizer['name'], type=type(error).__name__,
                                         httpStatus=getattr(error, 'code', None)))
    report['status'] = 'partial' if report['errors'] else 'ok'
    report['message'] = f"公開検索ページを{report['requests']}件確認し、主催者の新しい投稿URLを{report['count']}件発見。本文はX公式oEmbedで別途確認します。"
    if report['errors']: report['message'] += f"取得失敗{len(report['errors'])}件。既存の収集は継続します。"
    return report
