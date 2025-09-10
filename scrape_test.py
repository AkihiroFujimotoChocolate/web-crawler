import asyncio
from datetime import datetime, timedelta, timezone
import json

from web_crawler import scrape_website, ScrapedPage


def force_to_stop(url, depth, visited):
    return bool(visited and len(visited) >= 50)


def write_to_file(page: ScrapedPage) -> bool:
    # store as JSONL
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
    with open("yahoonews.jsonl", "a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")
    return True


async def scrape_yahoonews():
    url = "https://news.yahoo.co.jp/"
    # URL must be modified within the last 2 days
    since = datetime.now(timezone.utc) - timedelta(days=2)
    url_regex = r"https://news\.yahoo\.co\.jp/articles/[^/]+/?$"
    await scrape_website(
        url=url,
        data_handler=write_to_file,
        stop_handler=force_to_stop,
        since=since,
        url_regex=url_regex
    )


if __name__ == "__main__":
    asyncio.run(scrape_yahoonews())