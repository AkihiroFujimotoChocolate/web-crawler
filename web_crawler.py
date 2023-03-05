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

async def scrape_website(
    url: str, 
    data_handler: Callable[[str, str, int, bool, bool], bool], 
    stop_handler: Optional[Callable[[str, int, Set[str]], bool]] = None,
    depth: int = 3, 
    visited: Optional[Set[str]] = None, 
    delay: int = 1000, 
    since: Optional[datetime] = None, 
    url_regex: Optional[str] = None
) -> None: 
    """
    Asynchronously scrape HTML data from a given URL and recursively scrape pages up to a specified depth.

    Args:
        url: The URL of the website to scrape.
        data_handler: A callback function that takes the page text, URL, HTTP status code, a boolean indicating success, and a boolean indicating whether the page was successfully scraped, and processes the scrape data.
        stop_handler: An optional callback function that can be used to stop the scrape.
            The function takes the current URL, the current depth, and the set of visited URLs as arguments and should return True if the scrape should be stopped, False otherwise.
        depth: The depth of the recursive scrape (default is 3).
        visited: A set of URLs that have already been visited (default is None).
        delay: The delay between requests in milliseconds (default is 1000).
        since: An optional datetime object specifying the last modified date of the page to scrape.
        url_regex: An optional regular expression pattern to restrict the URLs to scrape.

    Returns:
        None.
    """

    # Check if the force stop file exists
    if stop_handler and stop_handler(url, depth, visited):
        print("Scraping was forcefully stopped.")
        return

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
