"""
Daily Claude & Anthropic news digest generator.
Uses stdlib xml.etree + requests only (no feedparser dependency).
"""

import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

try:
    import requests
except ImportError:
    import urllib.request as _urllib
    requests = None

TODAY  = datetime.now(timezone.utc)
CUTOFF = TODAY - timedelta(days=7)

SOURCES = [
    {
        "label": "Google News – Anthropic Claude",
        "url": (
            "https://news.google.com/rss/search"
            "?q=Anthropic+Claude+AI&hl=en-US&gl=US&ceid=US:en"
        ),
    },
    {
        "label": "Google News – Claude features",
        "url": (
            "https://news.google.com/rss/search"
            "?q=Claude+AI+new+feature+release&hl=en-US&gl=US&ceid=US:en"
        ),
    },
    {
        "label": "Google News – Anthropic news",
        "url": (
            "https://news.google.com/rss/search"
            "?q=Anthropic+AI+update&hl=en-US&gl=US&ceid=US:en"
        ),
    },
]

NAMESPACES = {
    "atom":    "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}


def fetch_text(url: str) -> str | None:
    headers = {"User-Agent": "claude-news-bot/1.0"}
    if requests:
        try:
            r = requests.get(url, timeout=15, headers=headers)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"    [WARN] requests failed for {url}: {e}")
            return None
    else:
        import urllib.request
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"    [WARN] urllib failed for {url}: {e}")
            return None


def parse_date(text: str) -> datetime:
    """Try RFC-2822 (RSS) then ISO-8601 (Atom)."""
    if not text:
        return TODAY
    text = text.strip()
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        # handle trailing Z
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return TODAY


def strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text or "")
    clean = " ".join(clean.split())
    return clean[:300] + ("…" if len(clean) > 300 else "")


def parse_feed(xml_text: str, label: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"    [WARN] XML parse error ({label}): {e}")
        return []

    entries = []

    # RSS 2.0
    for item in root.findall(".//item"):
        def tx(tag, ns=None):
            el = item.find(f"{{{ns}}}{tag}" if ns else tag)
            return el.text or "" if el is not None else ""

        title   = tx("title")
        link    = tx("link")
        date    = tx("pubDate") or tx("date", NAMESPACES["dc"])
        summary = tx("description") or tx("summary")
        entries.append({
            "title":   title,
            "link":    link,
            "date":    parse_date(date),
            "summary": summary,
            "source":  label,
        })

    # Atom
    for entry in root.findall(f"{{{NAMESPACES['atom']}}}entry"):
        def ax(tag):
            el = entry.find(f"{{{NAMESPACES['atom']}}}{tag}")
            return el.text or "" if el is not None else ""

        title   = ax("title")
        updated = ax("updated") or ax("published")
        summary = ax("summary") or ax("content")
        link_el = entry.find(f"{{{NAMESPACES['atom']}}}link")
        link    = link_el.get("href", "") if link_el is not None else ""
        entries.append({
            "title":   title,
            "link":    link,
            "date":    parse_date(updated),
            "summary": summary,
            "source":  label,
        })

    return entries


def build_markdown(all_entries: list[dict]) -> str:
    recent = [e for e in all_entries if e["date"] >= CUTOFF]
    recent.sort(key=lambda e: e["date"], reverse=True)

    lines = [
        "# Claude & Anthropic — Daily News Digest",
        "",
        f"> **Generated:** {TODAY.strftime('%Y-%m-%d %H:%M UTC')}  ",
        "> **Coverage:** Last 7 days · Auto-updated daily via GitHub Actions",
        "",
    ]

    if not recent:
        lines += [
            "## No new posts in the last 7 days",
            "",
            "Check [anthropic.com/news](https://www.anthropic.com/news) for the latest.",
            "",
        ]
    else:
        lines += ["## Latest Updates", ""]
        for entry in recent:
            date_str = entry["date"].strftime("%b %d, %Y")
            lines.append(f"### [{entry['title']}]({entry['link']})")
            lines.append(f"*{date_str} · {entry['source']}*")
            lines.append("")
            summary = strip_html(entry["summary"])
            if summary:
                lines.append(summary)
                lines.append("")

    lines += [
        "---",
        "",
        "## Quick Reference — Recent Major Releases",
        "",
        "| Date | Release | Key Highlights |",
        "|------|---------|----------------|",
        "| Apr 2026 | **Claude Opus 4.7** | High-res images (3.75 MP), task budgets, xhigh effort, 1M context |",
        "| Feb 2026 | **Claude Sonnet 4.6** | Hybrid reasoning, 1M context, best-in-class agent planning |",
        "| 2026 | **Claude Mythos Preview** | Security-focused model, Project Glasswing |",
        "| 2026 | **Claude Code GA** | GitHub Actions, VS Code & JetBrains integrations, /ultrareview |",
        "| 2026 | **Claude for Healthcare** | HIPAA-ready tools for providers & health-tech |",
        "",
        "---",
        "",
        "*Sources: Anthropic Blog RSS · GitHub Changelog*  ",
        "*View the interactive dashboard: [claude-news.html](./claude-news.html)*",
    ]

    return "\n".join(lines) + "\n"


def main():
    print(f"Generating Claude news digest — {TODAY.strftime('%Y-%m-%d')} UTC")
    all_entries: list[dict] = []

    for source in SOURCES:
        print(f"  Fetching: {source['label']} …")
        text = fetch_text(source["url"])
        if not text:
            print("    → skipped (fetch failed)")
            continue
        entries = parse_feed(text, source["label"])
        all_entries.extend(entries)
        print(f"    → {len(entries)} entries")

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for e in all_entries:
        if e["link"] not in seen:
            seen.add(e["link"])
            unique.append(e)

    md = build_markdown(unique)
    with open("CLAUDE_NEWS_DIGEST.md", "w", encoding="utf-8") as f:
        f.write(md)

    count = len([e for e in unique if e["date"] >= CUTOFF])
    print(f"Done — {count} recent entries written to CLAUDE_NEWS_DIGEST.md")


if __name__ == "__main__":
    main()
