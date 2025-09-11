import asyncio
from datetime import datetime, timedelta, timezone
import json

from web_crawler import scrape_website, ScrapedPage, DEFAULT_USER_AGENT


def force_to_stop(url, depth, visited):
    # same logic as scrape_test.py: stop after visiting 50 pages
    return bool(visited and len(visited) >= 50)


def write_to_file(page: ScrapedPage) -> bool:
    # store as JSONL (separate file name for Playwright run)
    record = {
        "title": page.title,
        "page_content": page.text,
        "source": page.url,
        "status_code": page.status,
        "is_success": page.success,
        "last_modified": page.last_modified.isoformat() if page.last_modified else None,
        "links": page.links,
        # "headers": page.headers,  # optional include if needed
    }
    with open("yahoonews_playwright.jsonl", "a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")
    return True


async def scrape_yahoonews_playwright():
    url = "https://news.yahoo.co.jp/"
    # URL must be modified within the last 2 days (same as scrape_test.py)
    since = datetime.now(timezone.utc) - timedelta(days=2)
    url_regex = r"https://news\.yahoo\.co\.jp/articles/[^/]+/?$"

    # Use Playwright route by setting use_playwright=True
    await scrape_website(
        url=url,
        data_handler=write_to_file,
        stop_handler=force_to_stop,
        since=since,
        url_regex=url_regex,
        user_agent=DEFAULT_USER_AGENT,
        use_playwright=True,
        playwright_options={
            "wait_until": "networkidle",   # "load" | "domcontentloaded" | "networkidle" | "commit"
            "timeout_ms": 30000,
            "headless": True,
            # "wait_for_selector": "article"  # set if you need to wait for a specific element
        },
    )


if __name__ == "__main__":
    asyncio.run(scrape_yahoonews_playwright())