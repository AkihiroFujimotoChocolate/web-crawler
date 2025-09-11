# web-crawler
Asynchronous crawler for extracting text content from web pages.

- Async with `aiohttp` + `asyncio`
- Depth-limited recursion
- Optional URL filtering (regex)
- Optional “since” filtering via HTTP `Last-Modified`
- Pluggable callbacks (`data_handler`, `stop_handler`, `link_extractor`)

---

## Requirements

- Python: 3.11+ (tested on 3.13)
- Dependencies (capped below the next major per PEP 440 intent):
  - `aiohttp>=3.9,<4`
  - `beautifulsoup4>=4.12,<5`

Install:
```shell
pip install -r requirements.txt
```

--

## How to Run on Windows

1) Create a Python 3.13 virtual environment in the project root
```powershell
python3.13 -m venv .venv
```

2) Activate the virtual environment
```powershell
.venv\Scripts\Activate.ps1
```

3) Install dependencies
```powershell
pip install -r requirements.txt
```

4) Run the sample script (aiohttp route)
```powershell
python scrape_test.py
```

---

## How to Run on Linux

1) Create a Python 3.13 virtual environment in the project root
```shell
python3.13 -m venv .venv
```

2) Activate the virtual environment
```shell
source .venv/bin/activate
```

3) Install dependencies
```shell
pip install -r requirements.txt
```

4) Run the sample script (aiohttp route)
```shell
python scrape_test.py
```

---

## Custom link extractor

You can customize how links are extracted from each page by providing `link_extractor`.
If omitted, a built-in default extractor is used (collects all `<a href>` links, resolves to absolute URLs, and keeps only http/https).

Signature:
```python
def link_extractor(page: ScrapedPage) -> list[str]: ...
```

Example:

```python
from urllib.parse import urlparse, urljoin
from web_crawler import scrape_website, ScrapedPage

def only_article_links(page: ScrapedPage) -> list[str]:
    links: list[str] = []
    # Example: keep only URLs containing "/articles/"
    for a in page.soup.select("a[href]"):
        href = a["href"]
        if "/articles/" not in href:
            continue
        abs_url = urljoin(page.url, href)
        if urlparse(abs_url).scheme in ("http", "https"):
            links.append(abs_url)
    return links

# Use it:
# await scrape_website(url, data_handler=..., link_extractor=only_article_links)
```

---

## Optional: Playwright-based rendering (JS-required pages)

You can optionally fetch “rendered” HTML using Playwright, which helps with SPA/JS-heavy pages. This is an additive feature: the default `aiohttp`-based crawler continues to work as-is. Playwright is only needed when you explicitly use it.

- No lxml is used; BeautifulSoup runs with the built-in `html.parser`.
- Playwright and a browser runtime (e.g., Chromium) are optional dependencies.

### Install (only if you use Playwright)

```bash
pip install -r requirements-playwright.txt
playwright install chromium
# On Linux (recommended to include OS deps)
# playwright install --with-deps chromium
```

Notes:
- You may also install `firefox` or `webkit` instead of `chromium`.
- If Playwright is not installed, everything still works as long as you don’t call the Playwright adapter.

### Quick start (Playwright route)

```bash
python scrape_test_playwright.py
```

This script will:
- Navigate to the Yahoo News top page with Playwright
- Extract the rendered HTML, page title, links, and visible text (same extraction logic as the default path)
- Apply the same filters as `scrape_test.py` (since within last 2 days and Yahoo article URL pattern)

### Integrate with your crawler (minimal change)

If you want to switch to Playwright only for certain pages, enable the flag:

```python
await scrape_website(
  url=...,
  data_handler=...,
  use_playwright=True,
  playwright_options={
    "wait_until": "networkidle",
    "timeout_ms": 30000,
    "headless": True,
    # "wait_for_selector": "article",
  },
)
```

Design notes:
- Delayed import: Playwright is imported inside functions, so environments without Playwright/Chromium are unaffected unless you enable it.
- Headers: Response headers are accessed in a case-insensitive way (`last-modified`/`Last-Modified`).
- Concurrency: Playwright is heavier than aiohttp; limit parallelism when using it.