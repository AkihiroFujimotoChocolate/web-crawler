from typing import Optional, Set, Callable
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from datetime import datetime
import re
import threading

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

"""
This program recursively crawls web pages starting from a specified URL up to a given depth limit.
It extracts the textual content of the pages that match a specified regular expression, and passes the data to a user-specified callback function.

While crawling, the program only visits URLs that match the specified regular expression and belong to the same domain.
It keeps track of visited URLs using a thread-safe set to avoid visiting the same URL twice.
If the page was last modified before the specified time limit, it skips crawling that page.
The program also introduces a delay between successive crawls.

The program takes the following arguments:

    - url: The URL to start the crawl from.
    - data_handler: A user-defined callback function to process the textual data extracted from the page.
    - stop_handler: A user-defined callback function to force stop the crawl (optional).
    - depth: The depth limit of the crawl (default=3).
    - visited: A thread-safe set to store the URLs already visited (optional).
    - delay: The delay between successive crawls, in milliseconds (default=1000).
    - since: The time limit for the last page modification date (optional).
    - url_regex: A regular expression to filter the URLs to be crawled (optional).

Note: The program ignores any exceptions that occur while crawling and logs them.
A keyboard interrupt (Ctrl+C) is handled by closing the aiohttp session.
"""
async def scrape_website(
    url: str, 
    data_handler: Callable[[str, str, int, bool, bool], bool], 
    stop_handler: Optional[Callable[[], bool]] = None,
    depth: int = 3, 
    visited: Optional[Set[str]] = None, 
    delay: int = 1000, 
    since: Optional[datetime] = None, 
    url_regex: Optional[str] = None
) -> None:

    # Check if the force stop file exists
    if stop_handler and stop_handler():
        print("Scraping was forcefully stopped.")

    # Initialize a thread-safe set for visited URLs
    if visited is None:
        visited = ThreadSafeSet()
    visited.add(url)

    async with aiohttp.ClientSession() as session:
        try:
            # Get HTML from the URL
            async with session.get(url) as response:
                # Raise an exception if the response status code is not in the 2xx range
                response.raise_for_status()

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Check the last modified date of the page
                last_modified = response.headers.get("Last-Modified")
                if last_modified:
                    last_modified_date = datetime.strptime(last_modified, '%a, %d %b %Y %H:%M:%S %Z')
                    if since and last_modified_date < since:
                        return

                # Extract all text from the page
                page_text = soup.get_text().strip()

                # Call the callback function with the extracted data
                if not data_handler(page_text, url, response.status, response.ok):
                    return

                # Recursively scrape pages up to the specified depth
                if depth > 1:
                    for link in soup.find_all('a'):
                        next_url = link.get("href")
                        if next_url is not None:
                            # Convert the relative URL to an absolute URL
                            next_url = urljoin(url, next_url)
                            # Check if the URL matches the regular expression
                            if url_regex is not None and not re.match(url_regex, next_url):
                                continue
                            # Check if the URL is in the same domain and has not been visited yet
                            if urlparse(next_url).netloc == urlparse(url).netloc and next_url not in visited:
                                await scrape_website(next_url, data_handler, stop_handler, depth=depth-1, visited=visited, delay=delay, since=since, url_regex=url_regex)

                # Sleep for the specified number of milliseconds
                await asyncio.sleep(delay/1000)
        except KeyboardInterrupt:
            # Handle keyboard interrupt (Ctrl+C)
            await session.close()
            raise
        except Exception as e:
            # Log and ignore any exceptions that occur while scraping
            print(f"An exception occurred while scraping {url}: {e}")
