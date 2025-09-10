# web-crawler

Asynchronous crawler for extracting text content from web pages.

- Async with `aiohttp` + `asyncio`
- Depth-limited recursion
- Optional URL filtering via regex
- Optional "since" filtering via HTTP `Last-Modified`
- Pluggable callbacks (`data_handler`, `stop_handler`)

## Requirements

- Python: 3.13 (fixed)
- Install dependencies:
```bash
pip install -r requirements.txt
```

Notes:
- Be considerate: respect `robots.txt` and site Terms of Service.
- Use a reasonable delay and a descriptive `User-Agent` to avoid overloading servers.
- For faster and more lenient HTML parsing, this project uses BeautifulSoup with the `lxml` parser.

## Usage

The main entry point is `scrape_website` in [`web_crawler.py`](web_crawler.py). Provide a `data_handler` callback to consume scraped text.

```python
# example.py
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
```

Run:
```bash
python example.py
```

### Function signature (summary)

- `scrape_website(url, data_handler, stop_handler=None, depth=3, visited=None, delay=1000, since=None, url_regex=None, user_agent='web-crawler/1.0') -> None`
  - `data_handler(text: str, url: str, status: int, ok: bool) -> bool`: process page text; return `True` to continue recursion, `False` to stop.
  - `stop_handler(current_url: str, current_depth: int, visited: set[str]) -> bool`: return `True` to abort the crawl early.

## Common error messages when a wheel is unavailable or a source build is triggered (concise)

- "Building wheel for lxml …": pip didn't find a compatible prebuilt wheel and is compiling from source.
- "No matching distribution found for lxml==x.y.z": no distribution matches your Python/OS/architecture for that version.
- `fatal error: libxml/xmlversion.h: No such file or directory`: missing libxml2 headers.
- `fatal error: xslt.h: No such file or directory`: missing libxslt headers.
- "unable to execute 'gcc'" (Linux) / "'cl.exe' not found" (Windows): C/C++ build tools are not installed or not on PATH.
- macOS "xcrun: error: invalid active developer path": Command Line Tools for Xcode are not installed.
- "Skipping link … none of the wheel's tags match": a wheel exists but is incompatible with your Python/ABI/platform tags.

## References (binary wheels / installation)

If you run into issues related to binary wheels or source builds, consult these official resources:

- [lxml – Installation](https://lxml.de/installation.html)
- [pip install — pip documentation (CLI)](https://pip.pypa.io/en/stable/cli/pip_install/)
- [pip Configuration — pip documentation](https://pip.pypa.io/en/stable/topics/configuration/)
- [Installing packages — packaging.python.org](https://packaging.python.org/en/latest/tutorials/installing-packages/)
- [lxml — PyPI](https://pypi.org/project/lxml/)
