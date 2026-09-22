import unittest
from cs_discover import candidate_urls, discover_cs


class CSDiscoveryTests(unittest.TestCase):
    def test_exact_account_dedup_newest_first_and_no_excerpt_facts(self):
        html='https://x.com/host/status/12 https://twitter.com/HOST/status/12 https://x.com/host/status/25 https://x.com/host_fake/status/99 https://evil.com/host/status/98'
        self.assertEqual(candidate_urls(html,'host'),['https://x.com/host/status/25','https://x.com/host/status/12'])

    def test_failure_does_not_stop_other_organizers(self):
        config=dict(csOrganizers=[dict(name='A',account='a'),dict(name='B',account='b')],posts=[])
        def fetch(url):
            if 'p=A&' in url:raise TimeoutError()
            return 'リアルタイム検索 https://x.com/b/status/25 優勝 架空の選手'
        report=discover_cs(config,fetch)
        self.assertEqual(report['status'],'partial')
        self.assertEqual(len(report['errors']),1)
        self.assertEqual(report['count'],1)
        self.assertEqual(config['posts'][0]['eventKind'],'cs')
        self.assertNotIn('player',config['posts'][0])
        self.assertNotIn('game',config['posts'][0])

    def test_no_new_result_is_not_fetch_failure(self):
        report=discover_cs(dict(csOrganizers=[dict(name='A',account='a')]),lambda _: 'リアルタイム検索 一致する情報は見つかりませんでした')
        self.assertEqual(report['status'],'ok')
        self.assertEqual(report['count'],0)

    def test_wrong_page_is_failure_not_empty_success(self):
        report=discover_cs(dict(csOrganizers=[dict(name='A',account='a')]),lambda _: 'Access denied')
        self.assertEqual(report['status'],'partial')

if __name__=='__main__':unittest.main()
