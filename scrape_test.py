import asyncio
from datetime import datetime, timedelta
import json
import os

from web_crawler import scrape_website


def force_to_stop():
    if os.path.isfile("yahoonews.jsonl"):
        with open("yahoonews.jsonl", "r", encoding="utf-8") as f:
            lines = f.readlines()
            if len(lines) >= 30:
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
    url_regex = "https:\/\/news\.yahoo\.co\.jp\/articles\/[^\/]+\/?$"
    await scrape_website(
        url=url,
        data_handler=write_to_file,
        stop_handler=force_to_stop,
        since=since,
        url_regex=url_regex
    )


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(scrape_yahoonews())
