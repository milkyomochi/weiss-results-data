"""Find candidate URLs; only collect.py's primary-source parser creates results."""
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
PRIORITY = ("FLAME_CUP_unei", "fukufuku_ws", "corgi_nagoya", "SSSS37336553297", "kizunahi_ijanai")


def post_url(value):
    p = urllib.parse.urlsplit(value)
    if p.scheme != "https" or p.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} or p.username or p.password:
        return None
    m = re.fullmatch(r"/([A-Za-z0-9_]+)/status/(\d+)/?", p.path)
    return f"https://x.com/{m[1]}/status/{m[2]}" if m else None


def search(query, freshness, key):
    params = dict(q=query, freshness=freshness, count=20, country="JP", search_lang="ja", safesearch="moderate")
    req = urllib.request.Request(ENDPOINT + "?" + urllib.parse.urlencode(params), headers={"Accept": "application/json", "X-Subscription-Token": key})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.load(response)
    if not isinstance(payload.get("query"), dict):
        raise ValueError("Invalid search response")
    return payload.get("web", {}).get("results", [])


def discover(config, key, search_fn=search, pause=time.sleep):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = dict(id="discovery", name="X・優先CSの新規検索", url="https://brave.com/search/api/", checkedAt=None, count=0, status="pending")
    if not key:
        report["message"] = "検索サービス未接続。新規X投稿と優先CS5大会の検索は未実行です。登録済み投稿と紹介記事の収集は継続します。"
        return report
    organizers = {o["account"].lower(): o for o in config.get("csOrganizers", [])}
    if any(account.lower() not in organizers for account in PRIORITY):
        raise ValueError("Missing priority organizer")
    now = datetime.now(timezone.utc).date()
    freshness = f"{now - timedelta(days=14)}to{now}"
    plans = []
    for account in PRIORITY:
        organizer = organizers[account.lower()]
        plans.append((organizer, [f'site:x.com "{organizer["name"]}" 結果', f'site:x.com/{account}/status/ 優勝 準優勝 3位 4位']))
    # Normal organizers (including Hurricane) remain in collection, outside the priority five.
    for organizer in config.get("csOrganizers", []):
        if organizer["account"].lower() not in {a.lower() for a in PRIORITY}:
            plans.append((organizer, [f'site:x.com/{organizer["account"]}/status/ 結果']))
    plans.append((None, ["site:x.com ヴァイスシュヴァルツ 公認 優勝", "site:x.com ヴァイスシュヴァルツ 非公認 大会結果", "site:x.com ヴァイス CS 結果"]))
    existing = {post_url(p["url"]) for p in config.get("posts", [])}
    errors = []
    for organizer, queries in plans:
        urls = set()
        failed = False
        for query in queries:
            try:
                for result in search_fn(query, freshness, key):
                    url = post_url(result.get("url", ""))
                    if url:
                        urls.add(url)
            except Exception as error:
                failed = True
                errors.append(type(error).__name__)
            pause(1.1)
        if organizer:
            organizer["lastSearchAttemptAt"] = stamp
            organizer["lastSearchOutcome"] = "error" if failed else "candidates_found" if urls else "no_candidates"
            if not failed:
                organizer["lastDiscoveryAt"] = now.isoformat()
                organizer["lastDiscoveryOutcome"] = "candidates_found" if urls else "no_recent_result"
            # Do not clear old primary-source failures merely because search succeeded.
        for url in sorted(urls, key=lambda u: int(u.rsplit("/", 1)[1])):
            if url in existing:
                continue
            entry = dict(url=url, discoveredAt=stamp)
            # Queue separately, but never infer game/event/date/player from search excerpts.
            account = urllib.parse.urlsplit(url).path.split("/")[1].lower()
            if account in organizers:
                entry["eventKind"] = "cs"
            config.setdefault("posts", []).append(entry)
            existing.add(url)
            report["count"] += 1
    report.update(checkedAt=stamp, status="partial" if errors else "ok")
    report["message"] = f"優先CS5大会を大会名・主催者アカウントで検索。新規候補{report['count']}投稿。入賞情報は本文を確認できた場合だけ採用します。"
    if errors:
        report["message"] += f" 検索失敗{len(errors)}件。"
    else:
        config["lastDiscoveryAt"] = now.isoformat()
    return report
