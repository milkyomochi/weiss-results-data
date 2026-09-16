"""Find candidate URLs; only collect.py's primary-source parser creates results."""
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://api.tavily.com/search"
PRIORITY = ("FLAME_CUP_unei", "fukufuku_ws", "corgi_nagoya", "SSSS37336553297", "kizunahi_ijanai")


def post_url(value):
    p = urllib.parse.urlsplit(value)
    if p.scheme != "https" or p.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} or p.username or p.password:
        return None
    m = re.fullmatch(r"/([A-Za-z0-9_]+)/status/(\d+)/?", p.path)
    return f"https://x.com/{m[1]}/status/{m[2]}" if m else None


def search(query, freshness, key):
    params = dict(query=query, start_date=freshness, search_depth="basic", auto_parameters=False,
                  max_results=10, topic="general", include_answer=False, include_raw_content=False,
                  include_images=False, include_usage=True)
    req = urllib.request.Request(ENDPOINT, data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.load(response)
    if not isinstance(payload.get("results"), list):
        raise ValueError("Invalid search response")
    return payload


def discover(config, key, search_fn=search, pause=time.sleep, checkpoint=lambda: None):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = dict(id="discovery", name="X・優先CSの新規検索（Tavily）", url="https://www.tavily.com/", checkedAt=None, count=0, status="pending", searches=0, errors=[], creditsReported=0, resultUrls=[], webCandidates=[])
    if not key:
        report["message"] = "検索サービス未接続。新規X投稿と優先CS5大会の検索は未実行です。登録済み投稿と紹介記事の収集は継続します。"
        return report
    organizers = {o["account"].lower(): o for o in config.get("csOrganizers", [])}
    if any(account.lower() not in organizers for account in PRIORITY):
        report.update(status="error", message="優先CS設定が不足しています。直接取得は継続します。")
        return report
    now = datetime.now(timezone(timedelta(hours=9))).date()
    freshness = str(now - timedelta(days=14))
    plans = []
    for account in PRIORITY:
        organizer = organizers[account.lower()]
        plans.append((organizer, [f'{organizer["name"]} ヴァイス 大会結果', f'site:x.com/{account}/status/ 優勝 準優勝 3位 4位']))
    # Normal organizers (including Hurricane) remain in collection, outside the priority five.
    normal = [o for o in config.get("csOrganizers", []) if o["account"].lower() not in {a.lower() for a in PRIORITY}]
    if normal:
        organizer = normal[now.toordinal() % len(normal)]
        plans.append((organizer, [f'{organizer["name"]} {organizer["account"]} ヴァイス 結果']))
    plans.append((None, ["site:x.com ヴァイスシュヴァルツ 公認 非公認 優勝 大会結果", "ヴァイスシュヴァルツ CS 大会結果 入賞 デッキ"]))
    budget = config.setdefault("tavilyBudget", {})
    if budget.get("month") != str(now)[:7]: budget.update(month=str(now)[:7], monthlyAttempts=0)
    if budget.get("day") != str(now): budget.update(day=str(now), dailyAttempts=0)
    planned = sum(len(queries) for _, queries in plans)
    if budget["dailyAttempts"] + planned > 26 or budget["monthlyAttempts"] + planned > 900:
        report.update(message="Tavilyの検索上限（日26回・月900回）により新規検索を見送りました。直接取得は継続します。", budget=dict(budget))
        return report
    existing = {post_url(p["url"]) for p in config.get("posts", [])}
    errors = []
    for organizer, queries in plans:
        urls = set()
        failed = False
        for query in queries:
            try:
                budget["dailyAttempts"] += 1
                budget["monthlyAttempts"] += 1
                checkpoint()
                report["searches"] += 1
                payload = search_fn(query, freshness, key)
                report["creditsReported"] += payload.get("usage", {}).get("credits", 0)
                for result in payload["results"]:
                    url = post_url(result.get("url", ""))
                    if url:
                        urls.add(url)
                        if url not in report["resultUrls"]: report["resultUrls"].append(url)
                    else:
                        raw = result.get("url", "")
                        parsed = urllib.parse.urlsplit(raw)
                        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and raw not in report["webCandidates"]:
                            report["webCandidates"].append(raw)
            except Exception as error:
                failed = True
                errors.append(dict(query=query, type=type(error).__name__, httpStatus=getattr(error,"code",None)))
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
        checkpoint()
    report.update(checkedAt=stamp, status="partial" if errors else "ok")
    report.update(errors=errors, budget=dict(budget))
    report["message"] = f"Tavily basicで{report['searches']}検索。優先CS5大会を各2検索。X候補{len(report['resultUrls'])}件（新規{report['count']}件）、その他Web候補{len(report['webCandidates'])}件。本文で確認できた入賞情報だけ採用します。Web候補は未検証です。今月の検索試行{budget['monthlyAttempts']}/900回。"
    if errors:
        report["message"] += f" 検索失敗{len(errors)}件。"
    else:
        config["lastDiscoveryAt"] = now.isoformat()
    return report
