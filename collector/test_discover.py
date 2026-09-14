import copy
import unittest
from discover import PRIORITY, discover, post_url


class DiscoveryTests(unittest.TestCase):
    def config(self):
        return {"lastDiscoveryAt": "2020-01-01", "posts": [], "csOrganizers": [dict(account=a, name=a, priority=True) for a in PRIORITY] + [dict(account="hrccsws", name="ハリケーンCS", priority=False)]}

    def test_missing_key_does_not_claim_search(self):
        config = self.config()
        original = copy.deepcopy(config)
        result = discover(config, "")
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["checkedAt"])
        self.assertEqual(config, original)

    def test_all_priority_organizers_search_twice_and_no_snippet_hints(self):
        config = self.config()
        calls = []
        def search(q, freshness, key):
            calls.append(q)
            return [{"url": "https://twitter.com/FLAME_CUP_unei/status/123?x=1", "description": "優勝 Foo 開催日2026/01/01"}]
        result = discover(config, "test", search, lambda _: None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 14)
        self.assertEqual(len(config["posts"]), 1)
        self.assertEqual(set(config["posts"][0]), {"url", "discoveredAt", "eventKind"})
        self.assertFalse(config["csOrganizers"][-1]["priority"])

    def test_failure_does_not_change_last_success(self):
        config = self.config()
        def failed(*args):
            raise RuntimeError("failed")
        result = discover(config, "test", failed, lambda _: None)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(config["lastDiscoveryAt"], "2020-01-01")
        self.assertTrue(all(o["lastSearchOutcome"] == "error" for o in config["csOrganizers"]))

    def test_url_allowlist(self):
        for value in ["https://x.com.evil.test/a/status/123", "https://evil@x.com/a/status/123", "http://x.com/a/status/123", "https://x.com/a"]:
            self.assertIsNone(post_url(value))
        self.assertEqual(post_url("https://twitter.com/a/status/123"), "https://x.com/a/status/123")


if __name__ == "__main__":
    unittest.main()
