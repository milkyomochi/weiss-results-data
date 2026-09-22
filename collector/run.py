"""One pipeline for scheduled and manual runs, with explicit degraded status."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from discover import discover
from cs_discover import discover_cs

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(path, value):
    target = ROOT / path
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)


def freshness(before, after, now=None):
    now=now or datetime.now(timezone(timedelta(hours=9)))
    cutoff=(now-timedelta(days=14)).date().isoformat()
    known={r["id"] for r in before["results"]}
    added=[r for r in after["results"] if r["id"] not in known]
    recent=[r for r in added if r.get("evidence")=="primary" and (r.get("publishedAt") or "")>=cutoff]
    articles=[s.get("publishedAt") for r in after["results"] for s in r.get("relatedSources",[]) if s.get("publishedAt")]
    articles.extend(r["publishedAt"] for r in after["results"] if r.get("evidence")=="repost" and r.get("publishedAt"))
    latest=max((r.get("publishedAt") or "" for r in after["results"] if r.get("evidence")=="primary"),default="") or None
    return dict(latestResultPublishedAt=latest, latestArticlePublishedAt=max(articles,default=None),
                recentAdded=len(recent), historicalAdded=len(added)-len(recent),
                daysSinceLatest=(now.date()-datetime.fromisoformat(latest).date()).days if latest else None)


def main():
    before = read("data/results.json")
    config = read("collector/x_sources.json")
    try:
        discovery = discover(config, os.environ.get("TAVILY_API_KEY", ""),
                             checkpoint=lambda: write("collector/x_sources.json", config))
    except Exception as error:
        # Do not log exception text, request headers or response bodies.
        discovery = dict(id="discovery", name="X・優先CSの新規検索（Tavily）", status="error",
                         count=0, checkedAt=None, message="検索処理でエラー。直接取得は継続します。",
                         errors=[dict(type=type(error).__name__)])
    cs_discovery = discover_cs(config)
    write("collector/x_sources.json", config)
    result = subprocess.run([sys.executable, "-X", "utf8", "collector/collect.py", "--pages", "6"], cwd=ROOT, timeout=1200)
    if result.returncode:
        raise RuntimeError("Collector failed; no data will be published")
    subprocess.run([sys.executable, "-X", "utf8", "collector/collect.py", "--validate-only"], cwd=ROOT, check=True)
    after = read("data/results.json")
    rejected = {r["id"] for r in read("data/reviewed.json").get("rejectedResults", [])}
    if not ({r["id"] for r in before["results"]} - rejected).issubset({r["id"] for r in after["results"]}):
        raise RuntimeError("Unexpected loss of existing result IDs; publication stopped")
    state = read("data/collection.json")
    state["freshness"] = freshness(before,after)
    state["sources"] = [s for s in state["sources"] if s["id"] not in {"discovery", "cs_discovery"}] + [discovery, cs_discovery]
    state["schedule"] = dict(enabled=True, label="毎朝8時ごろ（GitHub Actions）", timezone="Asia/Tokyo")
    state["manualUpdateUrl"] = "https://github.com/milkyomochi/weiss-results-data/actions/workflows/collect.yml"
    failures = [s["id"] for s in state["sources"] if s["status"] != "ok"]
    state["runStatus"] = "partial" if failures else "ok"
    state["migrationComplete"] = True  # Verified end-to-end; old Work schedule paused on 2026-09-16.
    state["runUrl"] = os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "milkyomochi/weiss-results-data") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")
    write("data/collection.json", state)
    # Publish a single snapshot to avoid mismatched results/status across deployments.
    public = ROOT / "public-data"
    public.mkdir(exist_ok=True)
    write("public-data/snapshot.json", dict(dataset=after, collection=state))
    for name in ("results.json", "collection.json"):
        shutil.copyfile(ROOT / "data" / name, public / name)
    (public / "index.html").write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>WS入賞ウォッチ データ</title><h1>WS入賞ウォッチ データ</h1><p><a href="snapshot.json">最新データと収集状態</a></p><p>検索接続時: <a href="https://www.tavily.com/">Powered by Tavily</a></p></html>', encoding="utf-8")
    write(".run-status.json", dict(status=state["runStatus"], failedSources=failures, discovery=discovery))
    print(json.dumps(dict(records=len(after["results"]), status=state["runStatus"], failedSources=failures, freshness=state["freshness"])))


if __name__ == "__main__":
    main()
