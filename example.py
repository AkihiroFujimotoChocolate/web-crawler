#!/usr/bin/env python3
"""
Example script demonstrating the Python 3.13 optimized web crawler.
This matches the example in the README.md.
"""
import asyncio
from datetime import datetime, timedelta
from web_crawler import scrape_website


# data_handler receives: page_text, url, http_status, ok_flag
def data_handler(text: str, url: str, status: int, ok: bool) -> bool:
    print(f"[{status} {('OK' if ok else 'NG')}] {url} - {len(text)} chars")
    # Return True to continue recursion; return False to stop at this page.
    return True


# Optional: stop_handler(current_url, current_depth, visited_set) -> bool
def stop_handler(current_url: str, depth: int, visited) -> bool:
    # Example: hard stop if too many pages were visited
    return len(visited) > 200


async def main():
    start_url = "https://example.com"
    since = datetime.utcnow() - timedelta(days=2)
    # Crawl up to depth 2, 1 second delay between requests, and only same-domain links.
    await scrape_website(
        url=start_url,
        data_handler=data_handler,
        stop_handler=stop_handler,
        depth=2,
        delay=1000,              # milliseconds
        since=since,
        url_regex=None           # or r"^https://example\.com/articles/.*$"
    )


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=300))