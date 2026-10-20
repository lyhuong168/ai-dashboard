"""Feed parsing and tiering. No network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.market_news import parse_feed, tier_for  # noqa: E402

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Chipmaker hits record - Reuters</title><link>https://news.google.com/rss/articles/abc</link>
<pubDate>Fri, 16 Oct 2026 14:30:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source><description>&lt;a&gt;Shares rose&lt;/a&gt; 3%</description></item>
<item><title>Anthropic news item</title><link>https://www.anthropic.com/news/x</link><pubDate>Thu, 15 Oct 2026 09:00:00 GMT</pubDate>
<source url="https://www.anthropic.com">anthropic.com</source></item></channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Apple reports results</title>
<link href="https://www.apple.com/newsroom/2026/10/x/"/><updated>2026-10-16T09:00:00Z</updated><summary>Quarterly results</summary></entry></feed>"""


def test_rss_items_are_parsed_with_publisher_and_cleaned_summary():
    items = parse_feed(RSS)
    assert [i["title"] for i in items] == ["Chipmaker hits record - Reuters", "Anthropic news item"]
    assert items[0]["publisher"] == "Reuters" and items[0]["date"].year == 2026 and items[0]["summary"] == "Shares rose 3%"


def test_atom_entries_work_too():
    items = parse_feed(ATOM)
    assert items[0]["title"] == "Apple reports results" and items[0]["link"].endswith("/x/") and items[0]["date"].month == 10


def test_own_domains_are_tier_one_and_press_is_tier_two():
    a, b = parse_feed(RSS)
    assert tier_for(a) == "2" and tier_for(b) == "1"
    assert tier_for(parse_feed(ATOM)[0]) == "1"
