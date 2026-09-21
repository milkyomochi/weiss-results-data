import unittest
from datetime import datetime, timezone, timedelta
from collect import due_posts
from run import freshness

class FreshnessTests(unittest.TestCase):
    def test_recent_article_does_not_make_original_post_recent(self):
        before={"results":[]}
        after={"results":[dict(id="a",publishedAt="2026-08-28",evidence="primary",relatedSources=[dict(publishedAt="2026-09-21")])]}
        report=freshness(before,after,datetime(2026,9,21,tzinfo=timezone.utc))
        self.assertEqual(report["latestResultPublishedAt"],"2026-08-28")
        self.assertEqual(report["latestArticlePublishedAt"],"2026-09-21")
        self.assertEqual(report["recentAdded"],0)
        self.assertEqual(report["historicalAdded"],1)

    def test_unseen_newest_first_and_negative_checks_cool_down(self):
        now=datetime(2026,9,21,tzinfo=timezone.utc)
        def post(n):return f"https://x.com/a/status/{n}"
        entries={post(100):{},post(400):dict(lastCheckedAt=now.isoformat(),lastCheckOutcome="no_result"),post(200):{},post(300):dict(lastCheckedAt=(now-timedelta(days=8)).isoformat(),lastCheckOutcome="no_result")}
        self.assertEqual([u for u,_ in due_posts(entries,now)],[post(200),post(100),post(300)])

    def test_errors_are_retried_next_day(self):
        now=datetime(2026,9,21,tzinfo=timezone.utc)
        entries={"https://x.com/a/status/1":dict(lastCheckedAt=(now-timedelta(days=2)).isoformat(),lastCheckOutcome="error")}
        self.assertEqual(len(due_posts(entries,now)),1)
