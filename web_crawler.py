from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional, Set, Pattern
from urllib.parse import urljoin, urlparse, urldefrag

import aiohttp
from bs4 import BeautifulSoup


# Callback signature: (page_text, url, http_status, ok) -> bool
DataHandler = Callable[[str, str, int, bool], bool]
StopHandler = Callable[[str, int, Set[str]], bool]


async def scrape_website(
    url: str,
    data_handler: DataHandler,
    stop_handler: Optional[StopHandler] = None,
    *,
    depth: int = 3,
    visited: Optional[Set[str]] = None,
    delay: int = 1000,  # milliseconds
    since: Optional[datetime] = None,
    url_regex: Optional[str] = None,
    user_agent: str = "web-crawler/1.0",
    max_concurrency: int = 8,
    request_timeout: float = 60.0,
) -> None:
    """
    Asynchronously scrape HTML from a starting URL and recursively follow links up to a given depth.
    Optimized for Python 3.13:
      - Uses asyncio.TaskGroup for structured concurrency (3.11+)
      - Semaphore-based concurrency control
      - Single shared aiohttp ClientSession and connection pool

    Args:
        url: Starting URL.
        data_handler: Callback that receives (page_text, url, http_status, ok) and returns True to continue recursion.
        stop_handler: Optional callback (current_url, current_depth, visited_set) -> bool. Return True to stop early.
        depth: Recursion depth (>=1). At depth==1, only the current page is fetched.
        visited: Optional set to track visited URLs across recursion.
        delay: Delay between requests in milliseconds (politeness).
        since: If provided, skip pages whose Last-Modified < since (UTC-aware or naive allowed).
        url_regex: Optional regex string to restrict which URLs are followed.
        user_agent: User-Agent header for outbound requests.
        max_concurrency: Maximum number of concurrent HTTP requests.
        request_timeout: Total per-request timeout in seconds.

    Returns:
        None
    """
    if depth < 1:
        return

    # Normalize "since" to timezone-aware UTC for safe comparison
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    start_origin = urlparse(url).netloc
    visited = visited if visited is not None else set()
    visited_lock = asyncio.Lock()
    sem = asyncio.Semaphore(max_concurrency)
    pattern: Optional[Pattern[str]] = re.compile(url_regex) if url_regex else None

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en,*;q=0.5",
    }
    timeout = aiohttp.ClientTimeout(total=request_timeout)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:

        async def fetch(current_url: str, current_depth: int) -> None:
            # Check early stop
            if stop_handler and stop_handler(current_url, current_depth, visited):
                return

            # Normalize URL (drop fragments) and deduplicate with a lock
            current_url = urldefrag(current_url)[0]
            async with visited_lock:
                if current_url in visited:
                    return
                visited.add(current_url)

            try:
                # Respect concurrency limits
                async with sem:
                    async with session.get(current_url) as resp:
                        status = resp.status
                        ok = 200 <= status < 300

                        # Handle non-HTML responses gracefully
                        content_type = resp.headers.get("Content-Type", "").lower()
                        if not ("text/html" in content_type or "application/xhtml" in content_type):
                            # Still call data_handler but with empty text for non-HTML content
                            data_handler("", current_url, status, ok)
                            return

                        # Check Last-Modified header if "since" is provided
                        if since is not None and ok:
                            last_modified_str = resp.headers.get("Last-Modified")
                            if last_modified_str:
                                try:
                                    last_modified = parsedate_to_datetime(last_modified_str)
                                    # Ensure timezone-aware comparison
                                    if last_modified.tzinfo is None:
                                        last_modified = last_modified.replace(tzinfo=timezone.utc)
                                    if last_modified < since:
                                        # Page hasn't been modified since cutoff; skip
                                        return
                                except (ValueError, TypeError):
                                    # If parsing fails, continue anyway
                                    pass

                        # Read and parse HTML content
                        try:
                            html = await resp.text()
                        except Exception:
                            # If we can't decode the response, pass empty text
                            html = ""

                        if html:
                            try:
                                soup = BeautifulSoup(html, "lxml")
                                page_text = soup.get_text().strip()
                            except Exception:
                                # Fallback to html.parser if lxml fails
                                try:
                                    soup = BeautifulSoup(html, "html.parser")
                                    page_text = soup.get_text().strip()
                                except Exception:
                                    page_text = ""
                        else:
                            page_text = ""
                            soup = None

                        # Call data handler
                        continue_crawling = data_handler(page_text, current_url, status, ok)
                        if not continue_crawling or current_depth <= 1:
                            return

                        # Extract links for next depth level if we have parsed HTML
                        if soup and ok:
                            next_urls = []
                            for link in soup.find_all('a', href=True):
                                href = link.get("href")
                                if href:
                                    # Convert relative URL to absolute
                                    next_url = urljoin(current_url, href)
                                    # Apply URL regex filter if provided
                                    if pattern and not pattern.match(next_url):
                                        continue
                                    # Same-origin check
                                    if urlparse(next_url).netloc == start_origin:
                                        next_urls.append(next_url)

                            # Use TaskGroup for structured concurrency (Python 3.11+)
                            if next_urls:
                                try:
                                    async with asyncio.TaskGroup() as tg:
                                        for next_url in next_urls:
                                            tg.create_task(fetch(next_url, current_depth - 1))
                                except* Exception:
                                    # TaskGroup automatically handles individual task exceptions
                                    pass

                # Add politeness delay
                if delay > 0:
                    await asyncio.sleep(delay / 1000.0)

            except Exception as e:
                # Log error and call data_handler with error info
                try:
                    # Extract status from aiohttp exceptions if available
                    status = getattr(e, 'status', 0)
                    if hasattr(e, 'response') and e.response:
                        status = e.response.status
                    data_handler("", current_url, status, False)
                except Exception:
                    # If data_handler also fails, just continue
                    pass

        # Start the crawling process
        await fetch(url, depth)
