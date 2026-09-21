#!/usr/bin/env python3
"""Conservative WS result collector. Standard library only; no account/API key."""
from __future__ import annotations
import argparse, hashlib, json, re, time, unicodedata, signal
import urllib.request, urllib.error, urllib.parse, urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
JST = ZoneInfo("Asia/Tokyo")
AGENT = "WSResultsWatch/1.0"
VOID = {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}
ALIASES = {"サマポケ":"Summer Pockets", "ウマ娘":"ウマ娘 プリティーダービー", "推しの子":"【推しの子】"}

class Node:
    def __init__(self, tag="", attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []
    def text(self):
        if self.tag in {"script","style"}: return ""
        return clean(" ".join(c.text() if isinstance(c,Node) else c for c in self.children))
    def find(self, tag=None, cls=None):
        out=[]
        for c in self.children:
            if isinstance(c,Node):
                if (tag is None or c.tag==tag) and (cls is None or cls in c.attrs.get("class","").split()):
                    out.append(c)
                out.extend(c.find(tag,cls))
        return out

class Tree(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root=Node();self.cur=self.root;self.feed(source)
    def handle_starttag(self,tag,attrs):
        n=Node(tag,attrs,self.cur);self.cur.children.append(n)
        if tag not in VOID:self.cur=n
    def handle_startendtag(self,tag,attrs):
        self.cur.children.append(Node(tag,attrs,self.cur))
    def handle_endtag(self,tag):
        n=self.cur
        while n.parent:
            if n.tag==tag:self.cur=n.parent;return
            n=n.parent
    def handle_data(self,data):self.cur.children.append(data)

def clean(s):return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",s or "")).strip()
def match(pattern,s):
    m=re.search(pattern,s,re.I)
    return clean(m.group(1)) if m else None
def strip_tags(s):return Tree(s).root.text()
def utcnow():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def canonical(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in {"https","http"}:raise ValueError("Unsupported source URL")
    host=(p.hostname or "").lower()
    if host in {"www.twitter.com","twitter.com","www.x.com","x.com"}:
        m=re.search(r"/([^/]+)/status/(\d+)",p.path)
        if m:return "https://x.com/"+m[1]+"/status/"+m[2]
    if host.endswith("c-labo.jp"):
        m=re.search(r"/blog/(\d+)/?",p.path)
        if m:return "https://www.c-labo.jp/blog/"+m[1]+"/"
    return urllib.parse.urlunsplit(("https",host,p.path.rstrip("/")+"/","",""))
def title_name(t):return ALIASES.get(clean(t),clean(t)) or None
def key(record):
    url=canonical(record.get("originalUrl") or record["sourceUrl"])
    # The article headline is not an event id. X post identity survives reposts.
    discriminator=record.get("title") or record.get("deck") or ""
    if record.get("entryKey"):
        discriminator="entry|"+record["entryKey"]
    if "ws-tcg.com/" in url:
        discriminator+="|"+clean(record.get("event"))+"|"+clean(record.get("player"))
    return hashlib.sha256((url+"|"+discriminator).encode()).hexdigest()[:24]
def category(text):
    # Test non-sanctioned first: 非公認 contains 公認.
    if "非公認" in text:return "independent","発表文に「非公認」の明記あり"
    if "公認" in text:return "sanctioned","発表文に「公認」の明記あり"
    return "unknown","公認・非公認の明記を確認できず"
def rank_from(text):
    found=set(re.findall(r"準優勝|(?<!準)優勝|[2-8]位|ベスト(?:4|8|16)|全勝",clean(text)))
    if len(found)!=1:return None
    return next(iter(found))
def explicit_date(text):
    m=re.search(r"(?<!\d)(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?",text)
    if not m:return None
    try:return datetime(*map(int,m.groups()),tzinfo=JST).date().isoformat()
    except ValueError:return None
def published_date(text):
    try:return parsedate_to_datetime(text).astimezone(JST).date().isoformat()
    except (ValueError,TypeError,AttributeError):return explicit_date(text or "")
def blank(**kwargs):
    r=dict(event="",eventDate=None,publishedAt=None,category="unknown",categoryReason="公認・非公認の明記を確認できず",format=None,placement="",player=None,title=None,deck=None,organizer=None,area=None,sourceUrl="",sourceName="",originalUrl=None,deckUrl=None,evidence="repost",notes="",collectedAt=utcnow())
    r.update(images=[],relatedSources=[])
    r.update(kwargs);r["id"]=key(r);return r

def safe_url(url):
    p=urllib.parse.urlsplit(url)
    return p.scheme=="https" and bool(p.hostname) and not p.username and not p.password

def deck_images(root,source_url,post_url=None):
    """Only explicitly labelled recipe images belonging to this report, not ads/OG cards."""
    images=[];seen=set()
    post_id=post_url.rsplit("/",1)[-1] if post_url else None
    nodes=root.find("img")
    for node in nodes:
        alt=clean(node.attrs.get("alt",""))
        url=urllib.parse.urljoin(source_url,node.attrs.get("data-src") or node.attrs.get("src",""))
        if not safe_url(url) or not re.search(r"デッキ(?:レシピ|リスト)",alt):continue
        if re.search(r"お気に入り|商品|BOX|ボックス|パック|広告",alt,re.I):continue
        # The repost image filename carries the embedded post ID. Never borrow
        # a related article's recipe or an affiliate product image.
        post_match=post_id and re.search(r"(?:^|[-_/])"+re.escape(post_id)+r"(?:[-_.]|$)",urllib.parse.urlsplit(url).path)
        if re.search(r"-\d+x\d+\.[a-z]+$",url,re.I):continue
        if url in seen:continue
        thumb=url
        featured_match=False
        for candidate in nodes:
            small=urllib.parse.urljoin(source_url,candidate.attrs.get("src",""))
            if re.sub(r"-\d+x\d+(?=\.[a-z]+$)","",small,flags=re.I)==url and safe_url(small):
                if small!=url:thumb=small
                if "webfeedsFeaturedVisual" in candidate.attrs.get("class","").split():featured_match=True;break
        if post_id and not post_match:
            ordered=root.find();quotes=root.find("blockquote")
            # Older articles have Japanese filenames: accept only the main full
            # recipe image before the single report, matching its featured image.
            if not featured_match or "size-full" not in node.attrs.get("class","").split() or not quotes or ordered.index(node)>ordered.index(quotes[0]):continue
        seen.add(url)
        images.append(dict(url=url,thumbnailUrl=thumb,sourceUrl=source_url,alt=alt))
    return images[:4]

def deadline(signum, frame):
    raise TimeoutError("取得時間が上限を超えました")

class Fetcher:
    def __init__(self):self.robots={};self.requests=0
    def raw(self,url):
        if self.requests>=100:raise RuntimeError("収集上限に到達")
        self.requests+=1
        req=urllib.request.Request(url,headers={"User-Agent":AGENT,"Accept":"application/json,text/html,application/rss+xml,application/xml"})
        # Socket timeout alone does not bound a slowly streaming response.
        has_alarm=hasattr(signal,"SIGALRM")
        if has_alarm:
            prior=signal.signal(signal.SIGALRM,deadline);signal.alarm(22)
        try:
            with urllib.request.urlopen(req,timeout=12) as r:
                b=r.read(4_000_001)
                if len(b)>4_000_000:raise RuntimeError("ページ容量の上限を超過")
                return b.decode(r.headers.get_content_charset() or "utf-8",errors="replace")
        finally:
            if has_alarm:signal.alarm(0);signal.signal(signal.SIGALRM,prior)
    def get(self,url):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!="https" or parsed.hostname not in {"ws-tcg.com","www.c-labo.jp","ws4696.xyz"}:
            raise ValueError("収集対象外のURL")
        origin=parsed.scheme+"://"+parsed.netloc
        if origin not in self.robots:
            rp=urllib.robotparser.RobotFileParser()
            try:rp.parse(self.raw(origin+"/robots.txt").splitlines())
            except urllib.error.HTTPError as e:
                if e.code==404:rp.parse([])
                else:raise
            self.robots[origin]=rp
        if not self.robots[origin].can_fetch(AGENT,url):raise RuntimeError("robots.txtで収集が許可されていないURL")
        time.sleep(.5)
        return self.raw(url)

def parse_repost(item):
    heading=clean(item.findtext("title"))
    if not heading.startswith("【WS】") or any(x in heading for x in ("【WSR】","ヴァイスシュヴァルツロゼ","ヴァイスシュヴァルツブラウ")):return []
    game=match(r"【WS】(.+?)(?:優勝|入賞|準優勝|全勝)デッキレシピ",heading)
    if not game:return []
    content=item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or item.findtext("description") or ""
    root=Tree(content).root
    quotes=root.find("blockquote")
    # Only the embedded report is evidence, never generic boilerplate or related posts.
    if len(quotes)!=1:return []
    quote=quotes[0]
    snippets=quote.find(cls="blogcard-snippet")
    text=snippets[0].text() if snippets else quote.text()
    rank=rank_from(text)
    if not rank:return []
    originals=[a.attrs.get("href","") for a in quote.find("a") if re.match(r"https://(?:twitter|x)\.com/[^/]+/status/\d+",a.attrs.get("href",""))]
    if not originals:return []
    source=item.findtext("link")
    source=canonical(source)
    name=match(r"デッキレシピ\((.+)\)【ヴァイス",heading)
    name=re.sub(r"(?:✨)?(?:アルバイト|スタッフ)募集中.*$","",name or "").strip()
    cat,reason=category(text)
    player=(match(r"優勝(?:者)?(?:は|:|は…)?\s*[「『【]([^」』】]{1,50})[」』】]\s*(?:様|さん)",text)
            or match(r"優勝者は[^\w「『【]*([A-Za-z0-9_]{1,30})様",text))
    deck=match(r"デッキ名\s*[:：]?\s*[【「『]([^】」』]+)[】」』]",text)
    deck=deck or match(r"[【「『]デッキ名\s*[:：]\s*([^】」』]+)[】」』]",text)
    fmt= "ネオスタンダード" if "ネオスタンダード" in text else ("タイトル限定" if "タイトルカップ" in text else None)
    event_type="非公認大会" if cat=="independent" else "公認ショップ大会" if cat=="sanctioned" else "ショップ大会" if "ショップ大会" in text else "大会結果"
    # Repost dates cannot resolve 本日 or a yearless date in an old embedded tweet.
    event_date=explicit_date(text)
    notes="紹介記事内の投稿から成績を確認。使用タイトルは記事の表記。"
    if not event_date:notes+="元投稿の「本日」等から開催日を推定していません。"
    return [blank(event=(name+" / " if name else "")+event_type,eventDate=event_date,publishedAt=published_date(item.findtext("pubDate")),category=cat,categoryReason=reason,format=fmt,placement=rank,player=player,title=title_name(game),deck=deck,organizer=name or None,sourceUrl=source,sourceName="しろくろ速報",sourceId="reposts",originalUrl=canonical(originals[0]),deckUrl=source,notes=notes,images=deck_images(root,source,canonical(originals[0])))]

def official_blocks(html,url,pub=None):
    root=Tree(html).root
    # Current official recipe pages use dt/dd metadata; cards/comments are not copied.
    blocks=[];current={}
    for dl in root.find("dl"):
        for child in dl.children:
            if not isinstance(child,Node) or child.tag!="dt":continue
            siblings=dl.children;idx=siblings.index(child)
            dd=next((n for n in siblings[idx+1:] if isinstance(n,Node)),None)
            if not dd or dd.tag!="dd":continue
            k,v=child.text(),dd.text()
            if k=="参加大会":
                if current:blocks.append(current)
                current={}
            if k in {"参加大会","成績","ハンドルネーム","デッキ名","デッキ種別","ネオスタンダード区分","役職"}:current[k]=v
    if current:blocks.append(current)
    results=[]
    for b in blocks:
        if not b.get("参加大会") or not b.get("成績") or not b.get("ネオスタンダード区分"):continue
        rank=rank_from(b["成績"])
        if not rank:continue
        event=b["参加大会"]
        cat="official" if re.search(r"BCF\d|WGP\d|しろくろフェス|世界決勝|全国決勝",event) else "unknown"
        fmt=b.get("デッキ種別")
        if fmt and "ネオスタンダード" in fmt:fmt="ネオスタンダード"
        results.append(blank(event=event,publishedAt=pub,category=cat,categoryReason="公式サイトに掲載された公式大会の結果" if cat=="official" else "公式サイト掲載だが大会区分の明記は未確認",format=fmt,placement=rank,player=b.get("ハンドルネーム"),title=b.get("ネオスタンダード区分"),deck=b.get("デッキ名"),organizer="ブシロード" if cat=="official" else None,sourceUrl=url,sourceName="WS公式",deckUrl=url,evidence="primary",notes="公式掲載情報。1st/2ndデッキ・チーム内の役職はプレイヤー表記に保持。"))
    return results

def collect_official(fetch,source,pages,old):
    html=fetch.get(source["url"]);root=Tree(html).root
    links={}
    for a in root.find("a"):
        url=urllib.parse.urljoin(source["url"],a.attrs.get("href",""))
        if re.fullmatch(r"https://ws-tcg.com/deckrecipe/\d+/?",url):
            # The nearest list item supplies article publication date.
            ancestor=a
            for _ in range(4):
                if ancestor.tag=="li" or not ancestor.parent:break
                ancestor=ancestor.parent
            links[canonical(url)]=explicit_date(ancestor.text())
    if not links:raise RuntimeError("公式一覧の形式を確認できず")
    results=[];failures=0
    for url,pub in list(links.items())[:15]:
        try:
            found=official_blocks(fetch.get(url),url,pub)
            if not found:failures+=1
            results.extend(found)
        except Exception:failures+=1
    return results,failures,"公式の入賞者一覧を確認。"+(f"{failures}ページは取得・解析できませんでした。" if failures else "")

def parse_labo(html,url):
    root=Tree(html).root
    hs=root.find(cls="article_title");bodies=root.find(cls="article_body")
    if not hs or not bodies:return []
    title=hs[0].text()
    if "ヴァイスシュヴァルツ" not in title or any(x in title for x in ("ロゼ","ブラウ")):return []
    if not re.search(r"結果|優勝|入賞",title):return []
    # Remove links to previous results and related pages before deriving fields.
    body=bodies[0].text().split("前回の記事")[0]
    text=title+" "+body
    rank=rank_from(body)
    if not rank:return []
    cat,reason=category(text)
    dates=root.find(cls="article_date")
    pub=explicit_date(dates[0].text()) if dates else None
    event_date=explicit_date(title) or explicit_date(body)
    if not event_date and "本日" in body:event_date=pub
    deck=match(r"[【「『]([^】」』]+)[】」』]\s*デッキ(?:を|で)",body)
    player=match(r"デッキを使用された\s*[「『【]([^」』】]+)[」』】]",body) or match(r"優勝(?:者)?(?:は|:)\s*[「『【]([^」』】]+)[」』】]",body)
    page_title=(root.find("title") or [Node()])[0].text()
    shop=match(r"/\s*(.+?)の店舗ブログ",page_title)
    return [blank(event=title,eventDate=event_date,publishedAt=pub,category=cat,categoryReason=reason,placement=rank,player=player,deck=deck,organizer=shop,title=None,sourceUrl=canonical(url),sourceName="カードラボ",deckUrl=canonical(url),evidence="primary",notes="店舗ブログの発表。デッキ名から使用タイトルを推測していません。")]

def collect_labo(fetch,source,pages,old):
    root=Tree(fetch.get(source["url"])).root
    links=[]
    for a in root.find("a"):
        title=a.attrs.get("title","") or a.text()
        href=urllib.parse.urljoin(source["url"],a.attrs.get("href",""))
        if re.search(r"/blog/\d+/",href) and "ヴァイス" in title and re.search(r"結果|優勝|入賞",title) and "ロゼ" not in title and "ブラウ" not in title:
            if href not in links:links.append(href)
    results=[];failures=0
    for url in links[:12]:
        try:
            found=parse_labo(fetch.get(url),url)
            if not found:failures+=1
            results.extend(found)
        except Exception:failures+=1
    return results,failures,"WSの店舗ブログ一覧を確認。"+(f"{len(links)}件の結果記事を検出。" if links else "一覧内に新しい結果記事はありませんでした。")

def collect_feed(fetch,source,pages,old):
    records=[];skipped=0;failures=0
    for page in range(1,pages+1):
        url=source["url"]+("?paged="+str(page) if page>1 else "")
        try:items=ET.fromstring(fetch.get(url)).findall("./channel/item")
        except Exception:
            if page==1:raise
            failures+=1;break
        if not items:break
        for item in items:
            queue_repost_x(item)
            parsed=parse_repost(item);records.extend(parsed)
            if not parsed:skipped+=1
    message=f"最新{page}ページを確認。順位の対応が不明な投稿と対象外の記事は除外（{skipped}記事）。"
    if failures:message+="一部ページの取得に失敗。"
    return records,failures,message

def queue_repost_x(item):
    """Keep source discovery even when a multi-placing article cannot be parsed."""
    heading=clean(item.findtext("title"))
    if not heading.startswith("【WS】") or not re.search(r"入賞|優勝|全勝",heading):return
    body=item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or item.findtext("description") or ""
    quotes=Tree(body).root.find("blockquote")
    if len(quotes)!=1:return
    urls=[canonical(a.attrs["href"]) for a in quotes[0].find("a") if re.match(r"https://(?:x|twitter)\.com/[^/]+/status/\d+",a.attrs.get("href",""))]
    if not urls:return
    path=ROOT/"collector/x_sources.json";config=json.loads(path.read_text())
    if any(canonical(p["url"])==urls[0] for p in config.get("posts",[])):return
    entry=dict(url=urls[0])
    text=heading+" "+quotes[0].text()
    if re.search(r"(?<![A-Za-z_])CS(?![A-Za-z_])",text,re.I) or any(o["name"] in text for o in config.get("csOrganizers",[])):entry["eventKind"]="cs"
    config.setdefault("posts",[]).append(entry)
    # lastDiscoveryAt belongs only to an actual public Web search.
    write_json(path,config)

def parse_x_single(payload,url,hint=None):
    hint=hint or {};url=canonical(url)
    if not re.fullmatch(r"https://x.com/[A-Za-z0-9_]+/status/\d+",url):raise ValueError("Invalid X post URL")
    if canonical(payload.get("url",""))!=url:raise ValueError("X response does not match post")
    root=Tree(payload.get("html","")).root
    quotes=root.find("blockquote")
    if len(quotes)!=1:return []
    paragraphs=quotes[0].find("p")
    if len(paragraphs)!=1:return []
    text=paragraphs[0].text()
    if not re.search(r"ヴァイス|(?<![A-Za-z])WS(?![A-Za-z])",text,re.I) or not re.search(r"大会|ショップ|CS|杯",text):return []
    if re.search(r"ヴァイスシュヴァルツ(?:ロゼ|ブラウ)|\bWSR\b|【WSB】",text,re.I):return []
    rank=rank_from(text)
    if not rank or not re.search(r"結果|優勝(?:者|は|:|おめでとう)|全勝(?:は|者)|参加者|開催(?:の|された)",text):return []
    published=None
    for a in quotes[0].find("a"):
        href=a.attrs.get("href","")
        if re.match(r"https://(?:x|twitter)\.com/[^/]+/status/\d+",href) and canonical(href)==url:
            try:published=datetime.strptime(a.text(),"%B %d, %Y").date().isoformat()
            except ValueError:pass
    if not published:return []
    cat,reason=category(text)
    author=clean(payload.get("author_name")) or "Xの公開投稿"
    event_type="非公認大会" if cat=="independent" else "公認大会" if cat=="sanctioned" else "大会結果"
    title=hint.get("title")
    deck=hint.get("deck") or match(r"(?:使用デッキ|デッキ名)\s*[:：]?\s*[「『【]([^」』】]+)[」』】]",text)
    if not deck:
        def with_breaks(node):
            if isinstance(node,str):return node
            if node.tag=="br":return "\n"
            return "".join(with_breaks(c) for c in node.children)
        for line in with_breaks(paragraphs[0]).splitlines():
            deck=match(r"^(?:使用デッキ(?:名)?|デッキ名|デッキ)\s*[:：]\s*(.+?)(?=\s*(?:コメント\s*[:：]|次回|#|pic\.twitter)|$)",clean(line))
            if deck:break
    if not title and deck in ALIASES:title=title_name(deck)
    player=match(r"優勝(?:者)?(?:は|:)\s*[「『【]([^」』】]+)[」』】]\s*(?:さん|様)",text) or hint.get("player")
    related=list(hint.get("relatedSources") or [])
    if hint.get("sourceUrl") and canonical(hint["sourceUrl"])!=url:
        related.append(dict(url=hint["sourceUrl"],name=hint["sourceName"],publishedAt=hint.get("publishedAt")))
    notes="Xの公開投稿本文で成績を確認。公開日は元投稿に表示された日付。"
    if title and (hint.get("evidence")=="repost" or related):notes+="使用タイトル・画像は紹介記事も参照。"
    event_date=explicit_date(text) or hint.get("eventDate")
    if not event_date:notes+="開催日を「本日」や年のない日付から推定していません。"
    return [blank(event=author+" / "+event_type,eventDate=event_date,publishedAt=published,category=cat,categoryReason=reason,placement=rank,player=player,title=title_name(title),deck=deck,organizer=author,format=hint.get("format"),sourceUrl=url,sourceName="X",sourceId="x",originalUrl=url,deckUrl=hint.get("deckUrl") or url,evidence="primary",notes=notes,images=hint.get("images") or [],relatedSources=related,xCheckedAt=utcnow())]

def with_breaks(node):
    if isinstance(node,str):return node
    if node.tag=="br":return "\n"
    return "".join(with_breaks(c) for c in node.children)

def named_event(text):
    return match(r"(第\s*\d+\s*回\s*[^\n【】]{1,45}?(?:CS|杯|カップ))",text)

def known_cs(event):
    config=json.loads((ROOT/"collector/x_sources.json").read_text())
    return any(o["name"] in (event or "") for o in config.get("csOrganizers",[]))

def ranked_entries(lines):
    """Parse explicitly separated placing blocks; never assign a headline to all decks."""
    blocks=[];current=None
    for line in lines:
        # A result may put the placing after the numbered event, or announce a
        # quoted winning team in prose. Congratulatory lines are not new blocks.
        event=named_event(line)
        if event and re.fullmatch(re.escape(event)+r"\s+(準優勝|優勝|[1-8]位)[🏆🥇🥈🥉\s]*",line):
            line=line[len(event):].strip()
        announced=re.match(r"^(?:今回)?(準優勝|優勝)(?:したのは|は)\s*[「『]([^」』]+)[」』](?:チーム|の皆様)",line)
        if announced:
            current=[announced[1],[announced[2]]];blocks.append(current);continue
        m=re.match(r"^[🏆🥇🥈🥉【\s]*(準優勝|優勝|[1-8]位|ベスト(?:4|8|16))(.*)$",line)
        if m and not re.match(r"(?:賞品|景品|商品|者は|は|おめでとう|した)",m[2]):
            current=[m[1],[m[2].strip(" 🏆🥇🥈🥉・:】")]];blocks.append(current)
        elif current:current[1].append(line)
    entries=[]
    for rank,body in blocks:
        team=[]
        for raw in body:
            line=re.split(r"\s+(?:pic\.twitter|https://|#)",raw)[0]
            m=re.match(r"^(先鋒|中堅|大将)\s*[・:]?\s*(.+?)\s*[「『【(]([^」』】)]+)[」』】)]",line)
            if not m:m=re.fullmatch(r"(先鋒|中堅|大将)\s*[・:]?\s*(.+?)(?:選手|さん|様)\s+使用(?:タイトル|デッキ)?\s*:?\s*(.+)",line)
            if not m:m=re.fullmatch(r"(先鋒|中堅|大将)\s*[・:]?\s*(\S+)\s+(.+)",line)
            if m:
                player=re.sub(r"(?:選手|さん|様)$","",m[2]).strip()
                team.append(dict(placement=rank,role=m[1],player=player,title=title_name(m[3])))
        if team:
            # A malformed teammate must not receive another teammate's deck.
            if len({e["role"] for e in team})!=len(team):continue
            first=next((s for s in body if s),"")
            label=first if first and not re.match(r"先鋒|中堅|大将",first) else None
            label=next((match(r"^チーム名\s*:\s*(.+)",s) for s in body if s.startswith("チーム名")),None) or label
            for e in team:e["team"]=label
            entries.extend(team);continue
        label=next((match(r"^[「『]([^」』]+)[」』]$",s) for s in body if re.match(r"^[「『]",s)),None)
        # Some trio announcements omit roles. Preserve the explicit team and
        # player/title pairs without inventing a seat from their display order.
        pairs=[re.fullmatch(r"([^/]{1,50})/([^/]+)",s) for s in body if not re.search(r"https?://|pic\.twitter|#",s)]
        pairs=[m for m in pairs if m]
        if label and len(pairs)>1:
            entries.extend(dict(placement=rank,team=label,player=clean(m[1]),title=title_name(m[2])) for m in pairs)
            continue
        player=None;deck=None;title=None
        for line in body:
            m=re.match(r"^(.{1,50}?)(?:選手|さん|様)\s*(?:[「『【(]([^」』】)]+)[」』】)])?$",line)
            if not m:m=re.fullmatch(r"([^()]{1,50})\(([^()]+)\)",line)
            if m:player=clean(m[1]);title=title_name(m[2]) if m[2] else title
            d=match(r"^使用(?:タイトル|デッキ(?:名)?)?\s*:?\s*(.+?)(?=\s*(?:#|pic\.twitter|https://)|$)",line)
            if d:
                if line.startswith("使用タイトル"):title=title_name(d)
                else:deck=d
        if player and (deck or title):entries.append(dict(placement=rank,player=player,deck=deck,title=title))
    return entries

def parse_x(payload,url,hint=None):
    hint=hint or {};url=canonical(url)
    if canonical(payload.get("url",""))!=url:raise ValueError("X response does not match post")
    root=Tree(payload.get("html","")).root;quotes=root.find("blockquote")
    if len(quotes)!=1 or len(quotes[0].find("p"))!=1:return []
    paragraph=quotes[0].find("p")[0]
    lines=[clean(s) for s in with_breaks(paragraph).splitlines() if clean(s)]
    text="\n".join(lines)
    event=named_event(text) or hint.get("event")
    is_cs=bool(event and re.search(r"(?<![A-Za-z_])CS(?![A-Za-z_])",event,re.I)) or hint.get("eventKind")=="cs" or known_cs(event)
    multi=len(set(re.findall(r"準優勝|(?<!準)優勝|[1-8]位|ベスト(?:4|8|16)",text)))>1
    if not is_cs and not multi:return parse_x_single(payload,url,hint)
    # Reply posts can omit the game and event. Only a reviewed link to their
    # parent/event source supplies that context; an account name never does.
    context=hint.get("contextSourceUrl")
    reviewed_context=hint.get("game")=="ws" and event and context and safe_url(context)
    if not re.search(r"ヴァイス|(?<![A-Za-z])WS(?![A-Za-z])",text,re.I) and not reviewed_context:return []
    if re.search(r"ヴァイスシュヴァルツ(?:ロゼ|ブラウ)|\bWSR\b|\bWSB\b|ホロカ|ホロライブカードゲーム",text,re.I):return []
    entries=ranked_entries(lines)
    if not entries:return []
    published=None
    for a in quotes[0].find("a"):
        href=a.attrs.get("href","")
        if re.match(r"https://(?:x|twitter)\.com/[^/]+/status/\d+",href) and canonical(href)==url:
            try:published=datetime.strptime(a.text(),"%B %d, %Y").date().isoformat()
            except ValueError:pass
    if not published:return []
    cat,reason=category(text);author=clean(payload.get("author_name")) or "Xの公開投稿"
    event=event or author+" / 大会結果"
    rows=[]
    for e in entries:
        candidates=[h for h in hint.get("entries",[]) if h.get("player")==e["player"] and h.get("role")==e.get("role") and h.get("placement")==e["placement"]]
        h=candidates[0] if len(candidates)==1 else hint if len(entries)==1 else {}
        related=list(h.get("relatedSources") or hint.get("relatedSources") or [])
        if context and context!=url and not any(s["url"]==context for s in related):
            related.append(dict(url=context,name="大会・返信元の確認資料",publishedAt=None))
        notes="Xの公開投稿本文で順位・選手・使用デッキの対応を確認。公開日は元投稿の表示日付。"
        if e.get("role") or e.get("team"):notes+="成績はチーム順位。各選手の掲載デッキを1件として記録。"
        if e.get("title"):notes+="使用タイトルの略称は投稿表記を保持（既存の表記統一を除く）。"
        if context:notes+="大会名・競技は関連する主催者の発表も参照。"
        event_date=hint.get("eventDate")
        if not event_date:notes+="開催日は未確認。"
        entry_key="|".join([e["placement"],e.get("role") or "",e["player"],h.get("deckSlot") or ""])
        rows.append(blank(event=event,eventKind="cs" if is_cs else None,eventDate=event_date,publishedAt=published,
            category=cat,categoryReason=reason,placement=e["placement"],player=e["player"],role=e.get("role"),team=e.get("team"),
            title=e.get("title") or h.get("title"),deck=e.get("deck") or h.get("deck"),organizer=author,format=h.get("format") or hint.get("format"),
            sourceUrl=url,sourceName="X",sourceId="x",originalUrl=url,deckUrl=h.get("deckUrl") or url,evidence="primary",
            notes=notes,images=h.get("images") or [],relatedSources=related,xCheckedAt=utcnow(),entryKey=entry_key,
            game="ws",contextSourceUrl=context))
    return rows

def prioritize_posts(posts,organizers):
    """Round-robin priority organizers before the remaining discovered posts."""
    groups={o["account"].lower():[] for o in organizers if o.get("priority")}
    other=[]
    for url,entry in posts.items():
        account=urllib.parse.urlsplit(url).path.split("/")[1].lower()
        (groups[account] if account in groups else other).append((url,entry))
    ordered=[]
    while any(groups.values()):
        for group in groups.values():
            if group:ordered.append(group.pop(0))
    return ordered+other


def due_posts(posts, now=None):
    """Unseen posts first, newest IDs first; negative checks must not monopolize the queue."""
    now=now or datetime.now(timezone.utc)
    ready=[]
    for url,entry in posts.items():
        last=entry.get("lastCheckedAt")
        if last:
            try:
                age=(now-datetime.fromisoformat(last)).total_seconds()
                cooldown=7*86400 if entry.get("lastCheckOutcome") in {"parsed","no_result","outside_window"} else 86400
                if age<cooldown:continue
            except (ValueError,TypeError):pass
        ready.append((url,entry))
    return sorted(ready,key=lambda pair:(bool(pair[1].get("lastCheckedAt")), -int(pair[0].rsplit("/",1)[-1]) if pair[0].rsplit("/",1)[-1].isdigit() else 0))

def collect_x(fetch,source,pages,old):
    discovery=json.loads((ROOT/"collector/x_sources.json").read_text())
    hints={}
    for r in old:
        url=r.get("originalUrl") or r["sourceUrl"]
        if re.fullmatch(r"https://x.com/[A-Za-z0-9_]+/status/\d+",url):hints.setdefault(url,[]).append(r)
    posts={canonical(p["url"]):p for p in reversed(discovery.get("posts",[]))}
    for url in hints:posts.setdefault(url,{"url":url})
    results=[];failures=0;skipped=0;attempts=0
    cs_mode=source["id"]=="cs"
    ready=due_posts(posts)
    # Preserve unseen-before-retry ordering across the organizer round-robin.
    ordered=[]
    for unseen in (True,False):
        batch=dict((u,e) for u,e in ready if (not e.get("lastCheckedAt"))==unseen)
        ordered.extend(prioritize_posts(batch,discovery.get("csOrganizers",[])) if cs_mode else batch.items())
    audit=[]
    for url,entry in ordered:
        if not re.fullmatch(r"https://x.com/[A-Za-z0-9_]+/status/\d+",url):continue
        existing=hints.get(url,[])
        is_cs=entry.get("eventKind")=="cs" or any(r.get("eventKind")=="cs" for r in existing)
        if is_cs!=cs_mode:continue
        hint={**(existing[0] if existing else {}),**{k:v for k,v in entry.items() if k!="url"}}
        if existing:hint["entries"]=merge_entry_hints(existing,entry.get("entries",[]))
        checked=[r.get("xCheckedAt") for r in existing]
        if checked and all(t and (datetime.now(timezone.utc)-datetime.fromisoformat(t)).total_seconds()<7*86400 for t in checked):continue
        if attempts>=20:break
        attempts+=1
        outcome="error";found=[];http_status=None
        try:
            # Use X's official public embed API; no login/session scraping.
            endpoint="https://publish.twitter.com/oembed?"+urllib.parse.urlencode(dict(url=url,omit_script="true",dnt="true"))
            payload=json.loads(fetch.raw(endpoint))
            found=parse_x(payload,url,hint)
            outcome="parsed" if found else "no_result"
            if found:results.extend(found)
            else:skipped+=1
            print(f"  X {attempts}: {len(found)} result(s)",flush=True)
        except urllib.error.HTTPError as e:
            failures+=1
            http_status=e.code
            print(f"  X {attempts}: HTTP {e.code}",flush=True)
        except Exception as e:
            failures+=1
            print(f"  X {attempts}: {type(e).__name__}: {str(e)[:120]}",flush=True)
        entry.update(lastCheckedAt=utcnow(),lastCheckOutcome=outcome)
        audit.append(dict(url=url,outcome=outcome,records=len(found),httpStatus=http_status))
        if http_status==429:break
        time.sleep(.5)
    # Existing queue objects are updated in place. Preserve candidates added by the feed.
    write_json(ROOT/"collector/x_sources.json",discovery)
    write_json(ROOT/(".x-audit-"+source["id"]+".json"),audit)
    message=("CS主催者の" if cs_mode else "")+f"公開投稿を{attempts}件確認し、{len(results)}件の結果を取得。"
    if skipped:message+=f"対応が曖昧な投稿等は{skipped}件除外。"
    if failures:message+=f"{failures}件は取得できませんでした。"
    if cs_mode:
        watched=[o for o in discovery.get("csOrganizers",[]) if o.get("priority")]
        if watched:message+="優先確認："+"・".join(o["name"] for o in watched)+"。"
        for o in watched:
            if o.get("lastDiscoveryOutcome")=="no_recent_result":message+=f"{o['name']}は{o.get('lastDiscoveryAt','日付不明')}の検索で直近結果を未確認。"
            if o.get("discoveryFailure"):
                message+=o["discoveryFailure"];failures+=1
    message+="検索・紹介記事で見つかった投稿が対象で、全投稿は網羅しません。"
    return results,failures,message

def merge_entry_hints(existing,reviewed):
    by_entrant={(r.get("placement"),r.get("role"),r.get("player")):r for r in existing}
    for r in reviewed:
        k=(r.get("placement"),r.get("role"),r.get("player"))
        by_entrant[k]={**by_entrant.get(k,{}),**r}
    return list(by_entrant.values())

def validate(record):
    required={"id","event","category","placement","sourceUrl","sourceName","evidence","collectedAt","categoryReason","notes"}
    if not required.issubset(record):raise ValueError("Missing required result fields")
    if record["category"] not in {"official","sanctioned","independent","unknown"}:raise ValueError("Invalid category")
    if record["evidence"] not in {"primary","repost","search"}:raise ValueError("Invalid evidence")
    if record.get("eventKind") not in {None,"cs"}:raise ValueError("Invalid event kind")
    if record.get("role") not in {None,"先鋒","中堅","大将"}:raise ValueError("Invalid team role")
    if not record["placement"] or not record["event"]:raise ValueError("Missing event/placement")
    for field in ("sourceUrl","originalUrl","deckUrl","contextSourceUrl"):
        if record.get(field):
            p=urllib.parse.urlsplit(record[field])
            if p.scheme!="https" or not p.hostname or p.username or p.password:raise ValueError("Unsafe URL")
    if len(record.get("images",[]))>4:raise ValueError("Too many deck images")
    for img in record.get("images",[]):
        if not all(safe_url(img.get(f,"")) for f in ("url","thumbnailUrl","sourceUrl")):raise ValueError("Unsafe image URL")
        if not img.get("alt"):raise ValueError("Missing image description")
    for source in record.get("relatedSources",[]):
        if not safe_url(source.get("url","")):raise ValueError("Unsafe related source URL")
    for field in ("eventDate","publishedAt"):
        if record.get(field):
            day=datetime.strptime(record[field][:10],"%Y-%m-%d").date()
            if day>datetime.now(JST).date():raise ValueError("Future result date")
    if any(k in record.get("event","")+str(record.get("title") or "") for k in ("ヴァイスシュヴァルツロゼ","ヴァイスシュヴァルツブラウ")):raise ValueError("Excluded game")
    return True

def write_json(path,value):
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    temp.replace(path)

def merge(previous,incoming):
    out={r["id"]:r for r in previous}
    weights={"search":0,"repost":1,"primary":2}
    for r in incoming:
        validate(r);existing=out.get(r["id"])
        if not existing:
            url=canonical(r.get("originalUrl") or r["sourceUrl"])
            matches=[v for v in out.values() if url.startswith("https://x.com/") and canonical(v.get("originalUrl") or v["sourceUrl"])==url]
            entrant_matches=[v for v in matches if v.get("placement")==r.get("placement") and v.get("player")==r.get("player") and r.get("player") and v.get("role")==r.get("role")]
            if len(entrant_matches)==1 and (r.get("entryKey") or entrant_matches[0].get("entryKey")):
                existing=entrant_matches[0];r={**r,"id":existing["id"],"entryKey":existing.get("entryKey") or r.get("entryKey")}
            elif not r.get("entryKey") and any(v.get("entryKey") for v in matches):
                # A repost with no player is attachable only to one matching deck/rank.
                exact=[v for v in matches if v["placement"]==r["placement"] and r.get("title") and v.get("title")==r["title"] and (not r.get("player") or r["player"]==v.get("player"))]
                if len(exact)==1:existing=exact[0];r={**r,"id":existing["id"]}
                elif matches:continue
            elif len(matches)==1 and not r.get("entryKey") and not matches[0].get("entryKey") and (not (r.get("title") or r.get("deck")) or not (matches[0].get("title") or matches[0].get("deck"))):
                existing=matches[0]
                if not (r.get("title") or r.get("deck")):r={**r,"id":existing["id"]}
                else:del out[existing["id"]]
        if existing:
            lower=weights[r["evidence"]]<weights[existing["evidence"]]
            merged=dict(existing) if lower else {**existing,**{k:v for k,v in r.items() if v is not None}}
            merged["id"]=r["id"]
            for field in ("title","deck","player","organizer","area","format"):
                if not merged.get(field) and r.get(field):merged[field]=r[field]
            merged["images"]=list({img["url"]:img for img in [*existing.get("images",[]),*r.get("images",[])]}.values())[:4]
            related=[*existing.get("relatedSources",[]),*r.get("relatedSources",[])]
            secondary=r if lower else existing
            if secondary["sourceUrl"]!=merged["sourceUrl"]:
                related.append(dict(url=secondary["sourceUrl"],name=secondary["sourceName"],publishedAt=secondary.get("publishedAt")))
            merged["relatedSources"]=list({s["url"]:s for s in related if s["url"]!=merged["sourceUrl"]}.values())
            merged["collectedAt"]=existing["collectedAt"]
            # A parser with no category evidence cannot undo a verified classification.
            if r["category"]=="unknown" and existing["category"]!="unknown":
                merged["category"]=existing["category"];merged["categoryReason"]=existing["categoryReason"]
            out[r["id"]]=merged
        else:out[r["id"]]=r
    return sorted(out.values(),key=lambda r:(r.get("publishedAt") or "",r["id"]),reverse=True)

def main():
    args=argparse.ArgumentParser()
    args.add_argument("--pages",type=int,default=3)
    args.add_argument("--merge-only",action="store_true")
    args.add_argument("--validate-only",action="store_true")
    args.add_argument("--source",action="append",choices=["official","reposts","labo","x","cs"],help="Run only selected sources; preserve other source statuses")
    opt=args.parse_args()
    if not 1<=opt.pages<=8:args.error("--pages must be 1..8")
    result_path=ROOT/"data/results.json";state_path=ROOT/"data/collection.json"
    data=json.loads(result_path.read_text());state=json.loads(state_path.read_text())
    if opt.validate_only:
        for r in data["results"]:validate(r)
        assert len({r["id"] for r in data["results"]})==len(data["results"]),"Duplicate result ids"
        print(json.dumps({"valid":True,"records":len(data["results"])}));return
    before={r["id"] for r in data["results"]};incoming=[];statuses=[]
    if not opt.merge_only:
        fetch=Fetcher()
        for source in json.loads((ROOT/"collector/sources.json").read_text()):
            if opt.source and source["id"] not in opt.source:continue
            print("Checking "+source["id"],flush=True)
            stamp=utcnow()
            try:
                found,errors,message={"repost_feed":collect_feed,"official":collect_official,"labo":collect_labo,"x":collect_x,"x_cs":collect_x}[source["adapter"]](fetch,source,opt.pages,merge(data["results"],incoming))
                print(f"  {len(found)} records; {errors} failed pages",flush=True)
                incoming.extend(found)
                statuses.append(dict(id=source["id"],name=source["name"],url=source["url"],status="partial" if errors else "ok",checkedAt=stamp,count=len(found),message=message))
            except Exception as e:
                print("  "+str(e)[:100],flush=True)
                statuses.append(dict(id=source["id"],name=source["name"],url=source["url"],status="error",checkedAt=stamp,count=0,message="取得できませんでした。既存の結果は保持しています。 "+str(e)[:100]))
        state["lastRun"]=utcnow();state["sources"]=list({s["id"]:s for s in [*state["sources"],*statuses]}.values())
    reviewed_path=ROOT/"data/reviewed.json"
    rejected_ids=set()
    if reviewed_path.exists():
        reviewed=json.loads(reviewed_path.read_text())
        incoming.extend(reviewed["results"])
        rejected_ids={r["id"] for r in reviewed.get("rejectedResults",[]) if r.get("id")}
        # Supplemental searches report their own checked time; stale searches never
        # overwrite a fresh successful feed status or pretend to run again.
        for s in reviewed.get("sources",[]):
            current=next((x for x in state["sources"] if x["id"]==s["id"]),None)
            if not current:state["sources"].append(s)
            elif (s.get("checkedAt") or "") >= (current.get("checkedAt") or ""):
                current.update(s)
    # Retired collection source; retain its previously published results.
    state["sources"]=[s for s in state["sources"] if s["id"]!="labo"]
    data["results"]=[r for r in merge(data["results"],incoming) if r["id"] not in rejected_ids]
    data["updatedAt"]=utcnow();data["schemaVersion"]=3
    added=len({r["id"] for r in data["results"]}-before)
    state["lastAdded"]=(state.get("lastAdded",0)+added) if opt.merge_only else added
    write_json(result_path,data);write_json(state_path,state)
    print(json.dumps({"records":len(data["results"]),"added":added,"sources":state["sources"]},ensure_ascii=False))

if __name__=="__main__":main()
