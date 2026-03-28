"""News Sentiment Analysis — Stocksight-inspired, Elasticsearch-free.

Fetches news headlines for a stock symbol from Google News RSS and
Indian financial news sources, then scores sentiment using VADER.

Inspired by shirosaidev/stocksight but runs standalone with no
Elasticsearch dependency — stores nothing, returns analysis in real-time.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from utils.logging import get_logger

logger = get_logger(__name__)

# ─── VADER Sentiment ─────────────────────────────────────────────────

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _analyzer = SentimentIntensityAnalyzer()
except ImportError:
    _analyzer = None
    logger.warning("vaderSentiment not installed — sentiment scores will be 0")


def score_sentiment(text: str) -> dict:
    """Return VADER sentiment scores for a text string."""
    if not _analyzer or not text:
        return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}
    return _analyzer.polarity_scores(text)


def classify_sentiment(compound: float) -> str:
    """Classify compound score into human label."""
    if compound >= 0.25:
        return "Bullish"
    elif compound >= 0.05:
        return "Slightly Bullish"
    elif compound <= -0.25:
        return "Bearish"
    elif compound <= -0.05:
        return "Slightly Bearish"
    return "Neutral"


# ─── News Fetching ───────────────────────────────────────────────────

@dataclass
class NewsArticle:
    title: str
    source: str
    url: str
    published: str
    sentiment: dict = field(default_factory=dict)
    label: str = "Neutral"


def fetch_google_news(query: str, max_articles: int = 15) -> list[NewsArticle]:
    """Fetch news from Google News RSS feed."""
    articles = []
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item", limit=max_articles)

        for item in items:
            title = item.title.text if item.title else ""
            source_tag = item.source
            source = source_tag.text if source_tag else "Google News"
            link = item.link.text if item.link else ""
            pub_date = item.pubDate.text if item.pubDate else ""

            sentiment = score_sentiment(title)
            articles.append(NewsArticle(
                title=title,
                source=source,
                url=link,
                published=pub_date,
                sentiment=sentiment,
                label=classify_sentiment(sentiment["compound"]),
            ))
    except Exception as e:
        logger.warning("Google News fetch failed for %s: %s", query, e)

    return articles


def fetch_moneycontrol_news(symbol: str, max_articles: int = 10) -> list[NewsArticle]:
    """Fetch news from MoneyControl RSS for Indian stocks."""
    articles = []
    try:
        # MoneyControl general market news RSS
        url = "https://www.moneycontrol.com/rss/latestnews.xml"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item", limit=50)

        symbol_clean = symbol.replace(".NS", "").replace(".BO", "").upper()
        count = 0
        for item in items:
            title = item.title.text if item.title else ""
            if symbol_clean.lower() not in title.lower() and count >= 3:
                continue  # Include first 3 general market news + symbol-specific

            link = item.link.text if item.link else ""
            pub_date = item.pubDate.text if item.pubDate else ""

            sentiment = score_sentiment(title)
            articles.append(NewsArticle(
                title=title,
                source="MoneyControl",
                url=link,
                published=pub_date,
                sentiment=sentiment,
                label=classify_sentiment(sentiment["compound"]),
            ))
            count += 1
            if count >= max_articles:
                break
    except Exception as e:
        logger.warning("MoneyControl fetch failed: %s", e)

    return articles


def fetch_economic_times_news(symbol: str, max_articles: int = 10) -> list[NewsArticle]:
    """Fetch from Economic Times RSS."""
    articles = []
    try:
        url = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item", limit=30)

        symbol_clean = symbol.replace(".NS", "").replace(".BO", "").upper()
        count = 0
        for item in items:
            title = item.title.text if item.title else ""
            link = item.link.text if item.link else ""
            pub_date = item.pubDate.text if item.pubDate else ""

            sentiment = score_sentiment(title)
            articles.append(NewsArticle(
                title=title,
                source="Economic Times",
                url=link,
                published=pub_date,
                sentiment=sentiment,
                label=classify_sentiment(sentiment["compound"]),
            ))
            count += 1
            if count >= max_articles:
                break
    except Exception as e:
        logger.warning("ET fetch failed: %s", e)

    return articles


# ─── Main Analysis Function ──────────────────────────────────────────

def analyze_news_sentiment(
    symbol: str,
    exchange: str = "NSE",
    max_per_source: int = 10,
) -> dict:
    """Aggregate news sentiment from multiple sources for a stock.

    Returns:
        dict with articles, aggregate sentiment, and summary.
    """
    # Clean symbol name for search
    symbol_clean = re.sub(r"\.(NS|BO)$", "", symbol).upper()
    search_query = f"{symbol_clean} stock {exchange}"

    # Fetch from multiple sources
    google_articles = fetch_google_news(search_query, max_per_source)
    mc_articles = fetch_moneycontrol_news(symbol_clean, max_per_source)
    et_articles = fetch_economic_times_news(symbol_clean, max_per_source)

    all_articles = google_articles + mc_articles + et_articles

    # Deduplicate by title similarity
    seen_titles = set()
    unique_articles = []
    for a in all_articles:
        title_key = a.title.lower().strip()[:80]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_articles.append(a)

    # Compute aggregate sentiment
    if unique_articles:
        compounds = [a.sentiment.get("compound", 0) for a in unique_articles]
        avg_compound = sum(compounds) / len(compounds)
        bullish_count = sum(1 for c in compounds if c >= 0.05)
        bearish_count = sum(1 for c in compounds if c <= -0.05)
        neutral_count = len(compounds) - bullish_count - bearish_count
    else:
        avg_compound = 0
        bullish_count = bearish_count = neutral_count = 0

    overall_label = classify_sentiment(avg_compound)

    # Source breakdown
    source_counts: dict[str, int] = {}
    source_sentiment: dict[str, list[float]] = {}
    for a in unique_articles:
        source_counts[a.source] = source_counts.get(a.source, 0) + 1
        source_sentiment.setdefault(a.source, []).append(a.sentiment.get("compound", 0))

    source_breakdown = []
    for src, count in source_counts.items():
        avg = sum(source_sentiment[src]) / len(source_sentiment[src])
        source_breakdown.append({
            "source": src,
            "count": count,
            "avg_sentiment": round(avg, 4),
            "label": classify_sentiment(avg),
        })

    return {
        "symbol": symbol_clean,
        "exchange": exchange,
        "total_articles": len(unique_articles),
        "overall_sentiment": {
            "compound": round(avg_compound, 4),
            "label": overall_label,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
        },
        "source_breakdown": source_breakdown,
        "articles": [
            {
                "title": a.title,
                "source": a.source,
                "url": a.url,
                "published": a.published,
                "sentiment": {
                    "compound": round(a.sentiment.get("compound", 0), 4),
                    "pos": round(a.sentiment.get("pos", 0), 3),
                    "neg": round(a.sentiment.get("neg", 0), 3),
                    "neu": round(a.sentiment.get("neu", 0), 3),
                },
                "label": a.label,
            }
            for a in unique_articles
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
