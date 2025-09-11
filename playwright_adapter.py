from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Callable

from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from datetime import datetime
from urllib.parse import urljoin, urlparse

# Reuse existing types and functions from web_crawler.py
from web_crawler import (
    ScrapedPage,
    extract_page_text,
    DEFAULT_USER_AGENT,
)


def _parse_last_modified(headers: Dict[str, str]) -> Optional[datetime]:
    lm = headers.get("last-modified") or headers.get("Last-Modified")
    if not lm:
        return None
    try:
        return parsedate_to_datetime(lm)
    except Exception:
        return None


def _resolve_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """
    Extract a[href] and resolve to absolute URLs, keeping only http/https.
    """
    out: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        scheme = urlparse(abs_url).scheme
        if scheme in ("http", "https"):
            out.append(abs_url)
    # De-dup while preserving order
    return list(dict.fromkeys(out))


async def fetch_html_with_playwright(
    url: str,
    user_agent: str = DEFAULT_USER_AGENT,
    wait_until: str = "networkidle",  # "load" | "domcontentloaded" | "networkidle" | "commit"
    timeout_ms: int = 30000,
    headless: bool = True,
    extra_headers: Optional[Dict[str, str]] = None,
    wait_for_selector: Optional[str] = None,
) -> Dict:
    """
    Navigate to the URL with Playwright and return HTML and response info.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError  # lazy import
    except ImportError as e:
        raise RuntimeError(
            "Playwright is required when using the Playwright path. "
            "Please run: pip install playwright && playwright install chromium"
        ) from e

    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        try:
            try:
                browser = await p.chromium.launch(headless=headless)
            except Exception as e:
                raise RuntimeError(
                    "Chromium not found. Please run: playwright install chromium"
                ) from e

            context = await browser.new_context(
                user_agent=user_agent,
                extra_http_headers=extra_headers or {},
            )
            page = await context.new_page()

            resp = await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    pass

            html = await page.content()
            title = await page.title()

            status = resp.status if resp else 0
            headers = resp.headers if resp else {}

            return {
                "html": html,
                "status": status,
                "headers": headers,
                "title": title,
            }
        finally:
            try:
                if page:
                    await page.close()
            except Exception:
                pass
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            try:
                if browser:
                    await browser.close()
            except Exception:
                pass


async def crawl_url_with_playwright(
    url: str,
    user_agent: str = DEFAULT_USER_AGENT,
    link_extractor: Optional[Callable[[ScrapedPage], List[str]]] = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 30000,
    headless: bool = True,
    extra_headers: Optional[Dict[str, str]] = None,
    wait_for_selector: Optional[str] = None,
) -> ScrapedPage:
    """
    Render a single URL with Playwright and build a ScrapedPage.
    """
    fetched = await fetch_html_with_playwright(
        url=url,
        user_agent=user_agent,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        headless=headless,
        extra_headers=extra_headers,
        wait_for_selector=wait_for_selector,
    )

    html: str = fetched["html"]
    status: int = fetched["status"]
    headers: Dict[str, str] = fetched["headers"]
    title: Optional[str] = fetched["title"]

    soup = BeautifulSoup(html, "html.parser")
    text = extract_page_text(soup)

    page = ScrapedPage(
        url=url,
        status=status,
        success=bool(status) and 200 <= status < 400,
        html=html,
        text=text,
        soup=soup,
        headers=headers,
        last_modified=_parse_last_modified(headers),
        title=title,
        links=[],
    )

    # Resolve links
    if link_extractor is not None:
        links = link_extractor(page)
    else:
        try:
            from web_crawler import default_link_extractor as _default_link_extractor  # type: ignore
            links = _default_link_extractor(page)
        except Exception:
            links = _resolve_links(soup, url)

    page.links = links
    return page


# Demo: python playwright_adapter.py https://example.com
if __name__ == "__main__":
    import sys

    async def _main():
        target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
        page = await crawl_url_with_playwright(
            target,
            wait_until="networkidle",
            wait_for_selector=None,
        )
        print("URL:", page.url)
        print("Status:", page.status)
        print("Title:", page.title)
        print("Links:", len(page.links))
        print("Text sample:", (page.text[:200] + "...") if page.text else "")

    asyncio.run(_main())