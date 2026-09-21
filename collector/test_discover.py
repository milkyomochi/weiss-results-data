import copy
import unittest
import json
from unittest.mock import patch
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
            return {"results": [{"url": "https://twitter.com/FLAME_CUP_unei/status/123?x=1", "content": "優勝 Foo 開催日2026/01/01"}], "usage": {"credits": 1}}
        result = discover(config, "test", search, lambda _: None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 13)
        self.assertEqual(result["creditsReported"], 13)
        for account in PRIORITY:
            self.assertEqual(sum(account in q for q in calls), 2)
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
        self.assertEqual(post_url("https://x.com/a/status/123/photo/1"), "https://x.com/a/status/123")

    def test_budget_and_error_redaction(self):
        config = self.config()
        def fail(*args):
            raise RuntimeError("secret-token-do-not-log")
        first = discover(config, "secret-token-do-not-log", fail, lambda _: None)
        self.assertEqual(first["searches"], 13)
        self.assertNotIn("secret-token-do-not-log", json.dumps(first))
        discover(config, "test", fail, lambda _: None)
        third = discover(config, "test", fail, lambda _: None)
        self.assertEqual(third["searches"], 0)
        config["tavilyBudget"]["dailyAttempts"] = 0
        config["tavilyBudget"]["monthlyAttempts"] = 899
        self.assertEqual(discover(config, "test", fail, lambda _: None)["searches"], 0)

    def test_request_uses_basic_and_header_only_key(self):
        from discover import search
        with patch("discover.urllib.request.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"results": []}'
            search("query", "2026-09-01", "secret-test")
            req = request.call_args.args[0]
            body = json.loads(req.data)
            self.assertEqual(body["search_depth"], "basic")
            self.assertFalse(body["auto_parameters"])
            self.assertNotIn("secret-test", req.data.decode())
            self.assertEqual(req.get_header("Authorization"), "Bearer secret-test")

    def test_x_search_is_restricted_and_japanese(self):
        from discover import search
        with patch("discover.urllib.request.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"results": []}'
            search('site:x.com "ヴァイスシュヴァルツ" "優勝"', "2026-09-01", "test")
            body=json.loads(request.call_args.args[0].data)
            self.assertEqual(body["include_domains"],["x.com","twitter.com"])
            self.assertEqual(body["include_domains_mode"],"restrict")
            self.assertEqual(body["language"],"ja")
            self.assertTrue(body["exact_match"])

    def test_extract_profile_post_link_without_copying_snippet(self):
        config=self.config()
        def search(*args):
            return {"results":[{"url":"https://x.com/FLAME_CUP_unei/all","content":"リンク https://x.com/FLAME_CUP_unei/status/999 優勝 Fake"}]}
        report=discover(config,"test",search,lambda _:None)
        self.assertEqual(report["count"],1)
        self.assertNotIn("title",config["posts"][0])


if __name__ == "__main__":
    unittest.main()
