import asyncio
from datetime import datetime, timedelta
import json
import os

from web_crawler import scrape_website


def force_to_stop(url, depth, visited):
    if visited and len(visited) >= 50:
        return True
    return False

def write_to_file(page_content, source, status_code, is_success):
    with open("yahoonews.jsonl", "a", encoding="utf-8") as f:
        json.dump({"page_content": page_content, "source": source, "status_code": status_code, "is_success": is_success}, f, ensure_ascii=False)
        f.write("\n")
        return True
            
async def scrape_yahoonews():
    url = "https://news.yahoo.co.jp/"
    since = datetime.now() - timedelta(days=2)
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
