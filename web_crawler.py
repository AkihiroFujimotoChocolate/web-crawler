from typing import Optional, Set, Callable, Dict, List
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
        """
        Add an item to the thread-safe set.

        Args:
            item: The item to add.

        Returns:
            None.
        """
        with self.lock:
            self.set.add(item)

    def __contains__(self, item):
        """
        Check if an item is in the thread-safe set.

        Args:
            item: The item to search for.

        Returns:
            True if the item is in the set, False otherwise.
        """
        with self.lock:
            return item in self.set

    def __len__(self):
        """
        Get the number of items in the thread-safe set.

        Returns:
            The number of items in the set.
        """
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
    for a in page.soup.find_all('a', href=True):
        abs_url = urljoin(page.url, a['href'])
        parsed = urlparse(abs_url)
        if parsed.scheme in ('http', 'https'):
            links.append(abs_url)
    return links


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
) -> None:
    """
    Asynchronously scrape HTML data from a given URL and recursively scrape pages up to a specified depth.

    Args:
        url: The URL of the website to scrape.
        data_handler: A callback function that takes:
            (page: ScrapedPage) -> bool
            and returns True to continue or False to stop recursion.
        stop_handler: An optional callback function that can be used to stop the scrape.
            The function takes the current URL, the current depth, and the set of visited URLs as arguments
            and should return True if the scrape should be stopped, False otherwise.
        depth: The depth of the recursive scrape (default is 3).
        visited: A set of URLs that have already been visited (default is None).
        delay: The delay between requests in milliseconds (default is 1000).
        since: An optional datetime used to filter pages older than this Last-Modified.
               Naive datetimes will be treated as UTC and normalized to UTC for comparison.
        url_regex: An optional regular expression pattern to restrict the URLs to scrape.
        user_agent: The User-Agent string to use for HTTP requests (default is a polite default).
        link_extractor: Optional callback to extract links from a page.
            Signature: (page: ScrapedPage) -> List[str]
            If omitted, the built-in default_link_extractor is used.

    Returns:
        None.
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

            try:
                async with session.get(current_url) as response:
                    # Raise if not 2xx
                    response.raise_for_status()

                    # Skip non-HTML responses early
                    if response.content_type not in ("text/html", "application/xhtml+xml"):
                        return

                    # Read HTML
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # Parse Last-Modified robustly (RFC 2822/5322) and normalize to UTC
                    last_modified_dt: Optional[datetime] = None
                    last_modified = response.headers.get("Last-Modified")
                    if last_modified:
                        try:
                            dt = parsedate_to_datetime(last_modified)
                            if dt is not None:
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                else:
                                    dt = dt.astimezone(timezone.utc)
                                last_modified_dt = dt
                        except Exception:
                            last_modified_dt = None

                        # Skip if page older than 'since'
                        if since_utc and last_modified_dt and last_modified_dt < since_utc:
                            return

                    # Extract text
                    page_text = extract_page_text(soup)

                    # Metadata
                    title = soup.title.string.strip() if soup.title and soup.title.string else None

                    # Success for aiohttp (no response.ok)
                    success = 200 <= response.status < 300

                    # Build a temporary page (links empty) for link_extractor
                    temp_page = ScrapedPage(
                        url=current_url,
                        status=response.status,
                        success=success,
                        html=html,
                        text=page_text,
                        soup=soup,
                        headers=dict(response.headers),
                        last_modified=last_modified_dt,
                        title=title,
                        links=[],
                    )

                    # Links via extractor (default if not provided)
                    effective_extractor = link_extractor or default_link_extractor
                    links: List[str] = effective_extractor(temp_page)

                    # Final payload with links populated
                    payload = ScrapedPage(
                        url=current_url,
                        status=response.status,
                        success=success,
                        html=html,
                        text=page_text,
                        soup=soup,
                        headers=dict(response.headers),
                        last_modified=last_modified_dt,
                        title=title,
                        links=links,
                    )

                    if not data_handler(payload):
                        return

                    # Recurse
                    if current_depth > 1:
                        origin_host = urlparse(current_url).netloc
                        for next_url in links:
                            # Regex restriction
                            if url_regex is not None and not re.match(url_regex, next_url):
                                continue
                            # Same-domain and not visited
                            if urlparse(next_url).netloc == origin_host and next_url not in visited:
                                await _scrape(next_url, current_depth - 1)

                    # Politeness delay
                    await asyncio.sleep(delay / 1000)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Log and continue
                print(f"An exception occurred while scraping {current_url}: {e}")

        await _scrape(url, depth)