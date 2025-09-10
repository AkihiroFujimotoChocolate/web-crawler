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

4) Run the sample script
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

4) Run the sample script
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