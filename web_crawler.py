from typing import Optional, Set, Callable, Dict, List, Any
import aiohttp
import asyncio
from bs4 import BeautifulSoup, Comment
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
import re
import threading


# Polite default User-Agent (helps avoid blocks on some sites)
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible)"


class ThreadSafeSet:
    def __init__(self):
        self.lock = threading.Lock()
        self.set = set()

    def add(self, item):
        with self.lock:
            self.set.add(item)

    def __contains__(self, item):
        with self.lock:
            return item in self.set

    def __len__(self):
        with self.lock:
            return len(self.set)


@dataclass
class ScrapedPage:
    """
    Structured payload passed to data_handler for flexible processing.
    """
    url: str
    status: int
    success: bool
    html: str
    text: str
    soup: BeautifulSoup
    headers: Dict[str, str]
    last_modified: Optional[datetime]
    title: Optional[str]
    links: List[str]


def extract_page_text(soup: BeautifulSoup) -> str:
    """
    Extract visible, structured text from a BeautifulSoup document.

    - Removes scripts/styles/noscript/template/svg/iframe
    - Removes common boilerplate sections (nav/footer/header/aside)
    - Inserts <img alt> into text (or drops the image if no alt)
    - Removes HTML comments
    - Preserves structure with newlines and normalizes whitespace per line
    """
    # Remove non-content tags
    for tag in soup(['script', 'style', 'noscript', 'template', 'svg', 'iframe']):
        tag.decompose()

    # Remove common boilerplate sections
    for tag in soup.find_all(['nav', 'footer', 'header', 'aside']):
        tag.decompose()

    # Replace images with their alt text (or drop if no alt)
    for img in soup.find_all('img'):
        alt = (img.get('alt') or '').strip()
        if alt:
            img.replace_with(alt)
        else:
            img.decompose()

    # Remove comments
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # Get text with structure and normalize
    raw = soup.get_text(separator='\n', strip=True)
    lines = []
    for line in raw.splitlines():
        norm = re.sub(r'\s+', ' ', line).strip()
        if norm:
            lines.append(norm)
    return '\n'.join(lines)


def default_link_extractor(page: ScrapedPage) -> List[str]:
    """
    Default link extractor:
    - Collects all <a href> links using page.soup
    - Resolves to absolute URLs relative to page.url
    - Keeps only http/https schemes
    """
    links: List[str] = []
    for a in page.soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href:
            continue
        abs_url = urljoin(page.url, href)
        if urlparse(abs_url).scheme in ("http", "https"):
            links.append(abs_url)
    # de-dup, keep order
    dedup: List[str] = list(dict.fromkeys(links))
    return dedup


async def scrape_website(
    url: str,
    data_handler: Callable[[ScrapedPage], bool],
    stop_handler: Optional[Callable[[str, int, Set[str]], bool]] = None,
    depth: int = 3,
    visited: Optional[Set[str]] = None,
    delay: int = 1000,
    since: Optional[datetime] = None,
    url_regex: Optional[str] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    link_extractor: Optional[Callable[[ScrapedPage], List[str]]] = None,
    *,
    # Optional (non-breaking) additions:
    use_playwright: bool = False,
    playwright_options: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Asynchronously scrape HTML data from a given URL and recursively scrape pages up to a specified depth.

    - Non-breaking: new parameters are optional with defaults.
    - Flow/loop/async structure is unchanged; Playwright path is an optional branch.
    """

    # Initialize a thread-safe set for visited URLs
    if visited is None or not hasattr(visited, "add"):
        visited = ThreadSafeSet()

    # Normalize 'since' to timezone-aware UTC to safely compare with HTTP dates
    since_utc: Optional[datetime] = None
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        since_utc = since.astimezone(timezone.utc)

    # Optional URL filter regex (compiled once)
    url_pattern = re.compile(url_regex) if url_regex else None

    # Create one shared session per crawl for performance (reuse connections)
    timeout = aiohttp.ClientTimeout(total=30)  # adjust as needed
    headers = {"User-Agent": user_agent}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:

        async def _scrape(current_url: str, current_depth: int):
            # Stop check (pass a plain set to stop_handler when possible)
            if stop_handler:
                try:
                    visited_for_stop: Set[str] = visited.set if hasattr(visited, "set") else visited  # type: ignore
                except Exception:
                    visited_for_stop = set()
                if stop_handler(current_url, current_depth, visited_for_stop):
                    print("Scraping was forcefully stopped.")
                    return

            if current_url in visited:
                return
            visited.add(current_url)

            # Depth guard: still process current page at depth >= 0; recurse only if > 0
            can_recurse = current_depth > 0

            page: Optional[ScrapedPage] = None

            if use_playwright:
                # Lazy import; safe when Playwright is not installed and flag is False
                pw_opts = playwright_options or {}
                wait_until = pw_opts.get("wait_until", "networkidle")
                timeout_ms = int(pw_opts.get("timeout_ms", 30000))
                headless = bool(pw_opts.get("headless", True))
                wait_for_selector = pw_opts.get("wait_for_selector", None)

                try:
                    from playwright_adapter import crawl_url_with_playwright
                    page = await crawl_url_with_playwright(
                        current_url,
                        user_agent=user_agent,
                        wait_until=wait_until,
                        timeout_ms=timeout_ms,
                        headless=headless,
                        extra_headers=None,
                        wait_for_selector=wait_for_selector,
                    )
                except ImportError:
                    page = None
                except RuntimeError:
                    page = None
                except Exception:
                    page = None

            if page is None:
                # aiohttp route (unchanged behavior)
                try:
                    async with session.get(current_url) as response:
                        response.raise_for_status()

                        if response.content_type not in ("text/html", "application/xhtml+xml"):
                            return

                        resp_headers: Dict[str, str] = dict(response.headers)
                        last_modified: Optional[datetime] = None
                        lm = resp_headers.get("Last-Modified") or resp_headers.get("last-modified")
                        if lm:
                            try:
                                last_modified = parsedate_to_datetime(lm)
                            except Exception:
                                last_modified = None

                        if since_utc and last_modified and last_modified.astimezone(timezone.utc) < since_utc:
                            return

                        html = await response.text()

                        soup = BeautifulSoup(html, "html.parser")  # no lxml
                        try:
                            title = (soup.title.string or "").strip() if soup.title else None
                        except Exception:
                            title = None
                        text = extract_page_text(soup)

                        page = ScrapedPage(
                            url=current_url,
                            status=response.status,
                            success=200 <= response.status < 400,
                            html=html,
                            text=text,
                            soup=soup,
                            headers=resp_headers,
                            last_modified=last_modified,
                            title=title,
                            links=[],
                        )
                except aiohttp.ClientResponseError:
                    return
                except aiohttp.ClientError:
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return
            else:
                # Playwright route: apply since filter if available
                if since_utc and page.last_modified and page.last_modified.astimezone(timezone.utc) < since_utc:
                    return

            # Handler
            try:
                should_continue = data_handler(page)
            except Exception:
                should_continue = True

            if not should_continue:
                return

            # Links
            try:
                links = link_extractor(page) if link_extractor else default_link_extractor(page)
            except Exception:
                links = []

            if url_pattern:
                links = [u for u in links if url_pattern.search(u)]

            # Recurse
            if can_recurse:
                for next_url in links:
                    if next_url in visited:
                        continue
                    if delay and delay > 0:
                        await asyncio.sleep(delay / 1000.0)
                    await _scrape(next_url, current_depth - 1)

        await _scrape(url, depth)