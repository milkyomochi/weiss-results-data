"""One pipeline for scheduled and manual runs, with explicit degraded status."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from discover import discover

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(path, value):
    target = ROOT / path
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)


def main():
    before = read("data/results.json")
    config = read("collector/x_sources.json")
    discovery = discover(config, os.environ.get("BRAVE_SEARCH_API_KEY", ""))
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
    state["sources"] = [s for s in state["sources"] if s["id"] != "discovery"] + [discovery]
    state["schedule"] = dict(enabled=True, label="毎朝8時ごろ（GitHub Actions）", timezone="Asia/Tokyo")
    state["manualUpdateUrl"] = "https://github.com/milkyomochi/weiss-results-data/actions/workflows/collect.yml"
    failures = [s["id"] for s in state["sources"] if s["status"] != "ok"]
    state["runStatus"] = "partial" if failures else "ok"
    state["migrationComplete"] = False  # Set only after end-to-end verification and retirement of Work.
    state["runUrl"] = os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "milkyomochi/weiss-results-data") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")
    write("data/collection.json", state)
    # Publish a single snapshot to avoid mismatched results/status across deployments.
    public = ROOT / "public-data"
    public.mkdir(exist_ok=True)
    write("public-data/snapshot.json", dict(dataset=after, collection=state))
    for name in ("results.json", "collection.json"):
        shutil.copyfile(ROOT / "data" / name, public / name)
    (public / "index.html").write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>WS入賞ウォッチ データ</title><h1>WS入賞ウォッチ データ</h1><p><a href="snapshot.json">最新データと収集状態</a></p><p>検索接続時: <a href="https://brave.com/search/api/">Powered by Brave Search</a></p></html>', encoding="utf-8")
    write(".run-status.json", dict(status=state["runStatus"], failedSources=failures))
    print(json.dumps(dict(records=len(after["results"]), status=state["runStatus"], failedSources=failures)))


if __name__ == "__main__":
    main()
