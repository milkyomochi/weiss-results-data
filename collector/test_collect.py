import unittest
import xml.etree.ElementTree as ET
from collect import parse_repost, official_blocks, category, canonical, merge, deck_images, Tree, parse_x, blank, validate, prioritize_posts, archive_review_statuses

def item(title, text, date="Tue, 08 Sep 2026 07:00:00 +0000"):
    x=ET.Element("item")
    for k,v in {"title":title,"link":"https://ws4696.xyz/2026/09/08/example/","pubDate":date}.items():ET.SubElement(x,k).text=v
    ET.SubElement(x,"{http://purl.org/rss/1.0/modules/content/}encoded").text='<blockquote><a href="https://twitter.com/store/status/123456789">投稿</a><div class="blogcard-snippet">'+text+'</div></blockquote>'
    return x

class Regressions(unittest.TestCase):
    def test_official_wrapped_metadata_and_incomplete_next_player(self):
        def dl(fields):
            return '<dl>'+''.join('<div><dt>'+k+'</dt><dd>'+v+'</dd></div>' for k,v in fields.items())+'</dl>'
        complete={'参加大会':'WGP2026','成績':'優勝','ハンドルネーム':'A','ネオスタンダード区分':'タイトルA'}
        incomplete={'参加大会':'WGP2026','成績':'準優勝','ハンドルネーム':'B'}
        r=official_blocks(dl(complete)+dl(incomplete),'https://ws-tcg.com/deckrecipe/999/')
        self.assertEqual([(x['player'],x['title']) for x in r],[('A','タイトルA')])
    def test_official_primary_enriches_search_record_without_losing_id(self):
        old=blank(event='WGP2026',player='A',placement='優勝',sourceUrl='https://ws-tcg.com/deckrecipe/999/',sourceName='WS公式',evidence='search')
        new=blank(event='WGP2026',player='A',placement='優勝',title='タイトルA',sourceUrl=old['sourceUrl'],sourceName='WS公式',evidence='primary')
        rows=merge([old],[new]);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],old['id']);self.assertEqual(rows[0]['title'],'タイトルA');self.assertEqual(rows[0]['evidence'],'primary')
        self.assertEqual(len(merge(rows,[old,new])),1)
    def test_review_history_preserves_limitations_and_active_errors(self):
        review=dict(id='cs_reviewed',status='partial',message='開催日未確認')
        active=dict(id='cs',status='error')
        state=dict(sources=[review,active]);archive_review_statuses(state);archive_review_statuses(state)
        self.assertEqual(state['reviewHistory'],[review]);self.assertEqual(state['sources'],[active])
    def test_non_sanctioned_is_not_sanctioned(self):
        self.assertEqual(category("WS非公認大会で優勝")[0],"independent")
    def test_shop_does_not_imply_sanctioned(self):
        self.assertEqual(category("ショップ大会で優勝")[0],"unknown")
    def test_repost_today_does_not_mean_publication_date(self):
        r=parse_repost(item("【WS】GA文庫優勝デッキレシピ(店舗)【ヴァイスシュヴァルツ】","本日開催の非公認大会、優勝はGA文庫でした。"))[0]
        self.assertEqual(r["publishedAt"],"2026-09-08")
        self.assertIsNone(r["eventDate"])
        self.assertEqual(r["category"],"independent")
    def test_misleading_winner_headline_with_multiple_ranks_is_skipped(self):
        self.assertEqual(parse_repost(item("【WS】サマポケ優勝デッキレシピ(店舗)【ヴァイスシュヴァルツ】","優勝 A MTI 準優勝 B UMA 3位 C SMP 4位 D LL")),[])
    def test_other_game_is_excluded(self):
        self.assertEqual(parse_repost(item("【WSR】Navel優勝デッキレシピ【ヴァイスシュヴァルツロゼ】","本日の優勝")),[])
    def test_tweet_permalink_normalization(self):
        self.assertEqual(canonical("https://twitter.com/store/status/12345/photo/1?s=20"),"https://x.com/store/status/12345")
    def test_rerun_is_idempotent(self):
        rows=parse_repost(item("【WS】GA文庫優勝デッキレシピ(店舗)【ヴァイスシュヴァルツ】","優勝者は「テスト」様"))
        self.assertEqual(merge(rows,rows),rows)
    def test_metadata_is_bound_to_each_official_entry(self):
        html='<dl><dt>参加大会</dt><dd>ネオスタンダード in BCF2026 京都会場</dd><dt>成績</dt><dd>優勝</dd><dt>ハンドルネーム</dt><dd>先鋒A</dd><dt>ネオスタンダード区分</dt><dd>タイトルA</dd></dl><dl><dt>参加大会</dt><dd>ネオスタンダード in BCF2026 京都会場</dd><dt>成績</dt><dd>準優勝</dd><dt>ハンドルネーム</dt><dd>先鋒B</dd><dt>ネオスタンダード区分</dt><dd>タイトルB</dd></dl>'
        r=official_blocks(html,"https://ws-tcg.com/deckrecipe/999/")
        self.assertEqual([(x["player"],x["placement"],x["title"]) for x in r],[("先鋒A","優勝","タイトルA"),("先鋒B","準優勝","タイトルB")])
    def test_deck_image_does_not_select_products_or_another_posts_recipe(self):
        html='<img src="https://ws4696.xyz/deck-123-0-300x180.jpg"><img src="https://ws4696.xyz/deck-123-0.jpg" alt="デッキレシピGA文庫"><img src="https://ws4696.xyz/deck-999-0.jpg" alt="デッキレシピGA文庫"><img src="https://ws4696.xyz/product.jpg" alt="GA文庫 BOX"><img src="https://ws4696.xyz/favorite.jpg" alt="お気に入りカード">'
        images=deck_images(Tree(html).root,'https://ws4696.xyz/article/','https://x.com/shop/status/123')
        self.assertEqual(len(images),1)
        self.assertEqual(images[0]['thumbnailUrl'],'https://ws4696.xyz/deck-123-0-300x180.jpg')
    def test_old_recipe_filename_must_match_featured_and_precede_report(self):
        html='<img class="webfeedsFeaturedVisual" src="https://ws4696.xyz/recipe-300x180.jpg"><img class="size-full" src="https://ws4696.xyz/recipe.jpg" alt="デッキレシピGA文庫"><blockquote>結果</blockquote><img class="size-full" src="https://ws4696.xyz/related.jpg" alt="デッキレシピGA文庫">'
        self.assertEqual(len(deck_images(Tree(html).root,'https://ws4696.xyz/article/','https://x.com/shop/status/123')),1)
    def test_x_primary_merge_keeps_images_and_separate_article_date(self):
        original=parse_repost(item("【WS】GA文庫優勝デッキレシピ(店舗)【ヴァイスシュヴァルツ】","本日開催の非公認大会、優勝はGA文庫でした。"))[0]
        url=original['originalUrl']
        original['images']=[dict(url='https://ws4696.xyz/deck.jpg',thumbnailUrl='https://ws4696.xyz/deck-small.jpg',sourceUrl=original['sourceUrl'],alt='デッキレシピGA文庫')]
        payload=dict(url=url,author_name='店舗',html='<blockquote><p>【WS】本日開催の非公認大会、参加者13名。優勝はGA文庫でした！</p><a href="'+url+'">August 29, 2026</a></blockquote>')
        direct=parse_x(payload,url,original)[0]
        rows=merge([original],[direct]);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['sourceName'],'X');self.assertEqual(rows[0]['publishedAt'],'2026-08-29');self.assertIsNone(rows[0]['eventDate'])
        self.assertEqual(rows[0]['relatedSources'][0]['publishedAt'],'2026-09-08')
        rows=merge(rows,[original]);self.assertEqual(rows[0]['images'],original['images']);self.assertEqual(rows[0]['sourceName'],'X')
    def test_unlabelled_x_deck_is_enriched_without_duplicate(self):
        url='https://x.com/shop/status/123';base=blank(event='大会結果',placement='優勝',sourceUrl=url,sourceName='X',evidence='primary')
        article=blank(event='大会結果',placement='優勝',sourceUrl='https://ws4696.xyz/article/',sourceName='紹介記事',originalUrl=url,title='GA文庫')
        rows=merge([base],[article]);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['sourceName'],'X');self.assertEqual(rows[0]['title'],'GA文庫');self.assertEqual(rows[0]['id'],article['id']);self.assertEqual(len(merge(rows,[article])),1)
    def test_x_response_must_match_requested_post_and_skip_ambiguous_results(self):
        url='https://x.com/shop/status/123'
        with self.assertRaises(ValueError):parse_x(dict(url='https://x.com/shop/status/456'),url)
        p=dict(url=url,html='<blockquote><p>WS大会結果 優勝A 準優勝B</p><a href="'+url+'">September 5, 2026</a></blockquote>')
        self.assertEqual(parse_x(p,url),[])
    def test_image_javascript_urls_are_rejected(self):
        r=blank(event='大会',placement='優勝',sourceUrl='https://x.com/shop/status/123',sourceName='X',images=[dict(url='javascript:alert(1)',thumbnailUrl='https://example.org/i.jpg',sourceUrl='https://example.org/',alt='デッキ')])
        with self.assertRaises(ValueError):validate(r)
    def test_x_deck_label_stops_before_comment_and_keeps_trigger_notation(self):
        url='https://x.com/shop/status/123'
        payload=dict(url=url,author_name='店舗',html='<blockquote><p>WS非公認大会の結果発表。参加者7名。優勝は「A」さんです！<br>デッキ：8電【推しの子】<br>コメント：楽しかったです。<br>次回もお待ちしています。</p><a href="'+url+'">August 11, 2026</a></blockquote>')
        r=parse_x(payload,url)[0]
        self.assertEqual(r['deck'],'8電【推しの子】');self.assertEqual(r['player'],'A');self.assertIsNone(r['eventDate'])

    def x_result(self,text,author='主催者',hint=None):
        url='https://x.com/organizer/status/123'
        return parse_x(dict(url=url,author_name=author,html='<blockquote><p>'+text+'</p><a href="'+url+'">August 30, 2026</a></blockquote>'),url,hint)

    def test_cs_separates_placings_and_keeps_same_title_for_two_players(self):
        rows=self.x_result('第3回WSテストCS 結果<br>優勝<br>A選手<br>使用タイトル:GA文庫<br>準優勝<br>B選手<br>使用タイトル:GA文庫')
        self.assertEqual([(r['player'],r['placement']) for r in rows],[('A','優勝'),('B','準優勝')])
        self.assertEqual(len(merge(rows,rows)),2)
        self.assertTrue(all(r['eventKind']=='cs' and r['category']=='unknown' and r['eventDate'] is None for r in rows))

    def test_team_members_and_images_are_not_conflated(self):
        rows=self.x_result('第3回WSテストCS 結果<br>優勝・チームA<br>大将・A選手「GA文庫」<br>中堅・B選手「GA文庫」<br>先鋒・C選手「サマポケ」',hint={'images':[{'url':'https://example.org/ambiguous.jpg'}]})
        self.assertEqual(len(rows),3)
        self.assertEqual(len({r['id'] for r in rows}),3)
        self.assertTrue(all(r['team']=='チームA' and not r['images'] for r in rows))

    def test_reply_requires_reviewed_game_and_event_context(self):
        text='2位🥈<br>A選手<br>使用:8扉GA文庫'
        self.assertEqual(self.x_result(text,author='WSとホロカCS主催'),[])
        rows=self.x_result(text,hint={'event':'第3回WSテストCS','game':'ws','contextSourceUrl':'https://x.com/organizer/status/100'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['placement'],'2位')
        self.assertEqual(rows[0]['publishedAt'],'2026-08-30')

    def test_cs_source_does_not_accept_holoca_or_announcements(self):
        hint={'event':'第3回WSテストCS','game':'ws','contextSourceUrl':'https://x.com/organizer/status/100'}
        self.assertEqual(self.x_result('ホロカCS結果<br>優勝<br>A選手<br>使用:デッキ',hint=hint),[])
        self.assertEqual(self.x_result('第3回WSテストCS開催します<br>優勝賞品:BOX'),[])
        row=self.x_result('WSショップ大会 本日開催の結果。優勝は「A」さんです！',author='CS_shiga')[0]
        self.assertNotEqual(row.get('eventKind'),'cs')

    def test_cs_repost_merges_only_into_the_matching_entrant(self):
        rows=self.x_result('第3回WSテストCS 結果<br>優勝<br>A選手<br>使用タイトル:GA文庫<br>準優勝<br>B選手<br>使用タイトル:GA文庫')
        article=blank(event='CS',placement='準優勝',title='GA文庫',originalUrl=rows[0]['sourceUrl'],sourceUrl='https://ws4696.xyz/article/',sourceName='紹介記事',images=[dict(url='https://ws4696.xyz/deck.jpg',thumbnailUrl='https://ws4696.xyz/deck.jpg',sourceUrl='https://ws4696.xyz/article/',alt='準優勝デッキ')])
        merged=merge(rows,[article]);self.assertEqual(len(merged),2)
        self.assertFalse(next(r for r in merged if r['player']=='A')['images'])
        self.assertTrue(next(r for r in merged if r['player']=='B')['images'])
        self.assertEqual(len(merge(merged,rows)),2)

    def test_named_cups_with_inline_rank_and_plain_team_rows(self):
        rows=self.x_result('ヴァイスシュヴァルツ 大会結果<br>第6回ヴァイスコギナゴカップ<br>優勝は「チームA」の皆様でした<br>先鋒 SOMY アサルトリリィ<br>中堅 きく サマポケ<br>大将 P デレマス<br>優勝おめでとうございます')
        self.assertEqual([(r['role'],r['player']) for r in rows],[('先鋒','SOMY'),('中堅','きく'),('大将','P')])
        self.assertTrue(all(r['team']=='チームA' and r['eventKind']=='cs' for r in rows))
        rows=self.x_result('第28回 キズナ杯 優勝<br>チーム名:チームB<br>先鋒:A【アサリ】<br>中堅:B【サマポケ】<br>大将:C【デレマス】',hint={'game':'ws','contextSourceUrl':'https://example.org/event'})
        self.assertEqual(len(rows),3)

    def test_fukufuku_unlabelled_roles_and_media_are_not_players(self):
        rows=self.x_result('【第112回福福杯 結果発表】<br>🏆優勝🏆<br>『チームA』<br>A/ダ・カーポ<br>B/Summer Pockets<br>C/アイドルマスターシンデレラガールズ<br>おめでとうございます🎉#ws pic.twitter.com/abc')
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['role'] is None and r['team']=='チームA' and 'チーム順位' in r['notes'] for r in rows))

    def test_ssss_keeps_three_players_with_same_abbreviation(self):
        rows=self.x_result('第63回SSSS杯お疲れ様でした!<br>今回優勝したのは『チームA』チームです!<br>先鋒:A選手 使用LHS<br>中堅:B選手 使用LHS<br>大将:C選手 使用LHS<br>以下、2位以下の結果です。',hint={'game':'ws','contextSourceUrl':'https://example.org/event'})
        self.assertEqual(len(merge(rows,rows)),3)
        self.assertTrue(all(r['placement']=='優勝' and r['title']=='LHS' for r in rows))

    def test_flame_parenthesized_individuals_and_missing_game_context(self):
        text='第92回ふらめ杯<br>優勝<br>A(蓮ノ空)<br>準優勝<br>B(ミリオン)<br>3位<br>C(オバロ)<br>4位<br>D(グラブル)'
        self.assertEqual(self.x_result(text),[])
        rows=self.x_result(text,hint={'game':'ws','contextSourceUrl':'https://example.org/event'})
        self.assertEqual([r['placement'] for r in rows],['優勝','準優勝','3位','4位'])
        self.assertTrue(all(r['team'] is None and r['eventDate'] is None for r in rows))

    def test_priority_cs_queue_reserves_a_turn_for_each_organizer(self):
        posts={f'https://x.com/{a}/status/{i}':{} for a,i in [('a',3),('a',2),('a',1),('b',4),('other',5)]}
        queue=prioritize_posts(posts,[{'account':'a','priority':True},{'account':'b','priority':True}])
        self.assertEqual([u.split('/')[3] for u,_ in queue],['a','b','a','a','other'])

if __name__=="__main__":unittest.main()
