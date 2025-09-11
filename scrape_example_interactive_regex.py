from __future__ import annotations
import os
import sys
import json
import asyncio
from typing import Dict, Any, List

from web_crawler import scrape_website, ScrapedPage
from interactive_link_extractor import make_interactive_link_extractor

DEFAULT_START_URL = "https://www.recall.caa.go.jp/result/index.php?screenkbn=03"
DEFAULT_OUTPUT_FILE = "recall_interactive.jsonl"
DEFAULT_MAX_PAGES = 200


def build_recall_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "domains": ["www.recall.caa.go.jp"],
        "wait_until": "domcontentloaded",
        "dynamic_trigger": {"min_initial_links": 0, "force_patterns": []},
        "listbox": {
            "enabled": True,
            "trigger_text_regex": r"(表示件数|件ごと|60件)",
            "trigger_selectors": [],
            "select_selectors": [
                "select#dataDisplay",
                "select[name='viewCount']",
                "select"
            ],
            "desired_options": ["60", "45", "30", "15"],
            "prefer_value_match": True,
            "option_selectors": [],
            "wait_after_select": {
                "selector": None,
                "load_state": "networkidle",
                "timeout_ms": 25000,
                "debounce_ms": 1800
            },
            "skip_if_already_selected": True,
            "continue_on_failure": True
        },
        "scroll": {"enabled": False},
        "pagination": {
            "enabled": True,
            "next_selector_candidates": [
                "text=次 >>",
                "text=次＞＞",
                "text=次≫",
                "text=次»",
                "text=次 >",
                "text=次",
                "a:has-text('次')",
                "button:has-text('次')"
            ],
            "max_clicks": 50,
            "wait_after_click": {
                "selector": None,
                "load_state": "networkidle",
                "timeout_ms": 30000,
                "debounce_wait_ms": 1500
            },
            "stop_if_no_new_links": True,
            "regex_role_fallback": {
                "enabled": True,
                "roles": ["link", "button"],
                "name_pattern": r"(次(\s*>+)?|次≫|次»)"
            },
            "numeric_fallback": {
                "enabled": True,
                "active_selector": ".pagination .pn_active",
                "click_delay_ms": 80
            }
        },
        "link_normalization": {"strip_fragment": True, "unique": True},
        "playwright": {"headless": False, "timeout_ms": 60000},
        "debug": True
    }


def resolve_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def resolve_start_url() -> str:
    if os.environ.get("URL"):
        return os.environ["URL"]
    if len(sys.argv) > 1:
        return sys.argv[1]
    return DEFAULT_START_URL


def resolve_output_file() -> str:
    return resolve_env("OUTPUT", DEFAULT_OUTPUT_FILE)


def resolve_max_pages() -> int:
    val = os.environ.get("MAX_PAGES")
    if not val:
        return DEFAULT_MAX_PAGES
    try:
        return max(1, int(val))
    except ValueError:
        return DEFAULT_MAX_PAGES


class JsonlWriter:
    def __init__(self, path: str):
        self.path = path

    def write_page(self, page: ScrapedPage) -> bool:
        record = {
            "title": page.title,
            "page_content": page.text,
            "source": page.url,
            "status_code": getattr(page, "status", None),
            "is_success": getattr(page, "success", None),
            "last_modified": page.last_modified.isoformat() if getattr(page, "last_modified", None) else None,
            "links": page.links,
        }
        if hasattr(page, "extras") and isinstance(page.extras, dict):
            im = page.extras.get("interactive")
            if im:
                record["interactive_meta"] = {
                    "listbox": im.get("listbox"),
                    "pagination": {
                        k: v for k, v in (im.get("pagination") or {}).items()
                        if k in ("clicks", "total_new_links")
                    },
                    "base_link_count": im.get("base_link_count"),
                    "final_link_count": im.get("final_link_count"),
                    "errors": im.get("errors"),
                    "fatal_error": im.get("fatal_error")
                }
        with open(self.path, "a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")
        return True


def make_stop_handler(max_pages: int):
    def stop(url: str, depth: int, visited: List[str]) -> bool:
        return len(visited) >= max_pages
    return stop


async def run_recall_interactive():
    start_url = resolve_start_url()
    output_file = resolve_output_file()
    max_pages = resolve_max_pages()

    print(f"[INFO] Start URL: {start_url}")
    print(f"[INFO] Output JSONL: {output_file}")
    print(f"[INFO] Max pages: {max_pages}")

    config = build_recall_config()
    link_extractor = make_interactive_link_extractor(config)
    writer = JsonlWriter(output_file)

    def data_handler(page: ScrapedPage):
        if hasattr(page, "extras"):
            meta = page.extras.get("interactive") or {}
            print("[DBG] interactive snapshot:", {
                "listbox_status": (meta.get("listbox") or {}).get("status"),
                "pagination_clicks": (meta.get("pagination") or {}).get("clicks"),
                "counts": (meta.get("base_link_count"), meta.get("final_link_count")),
                "errors": meta.get("errors"),
                "fatal": meta.get("fatal_error")
            })
        writer.write_page(page)

    await scrape_website(
        url=start_url,
        data_handler=data_handler,
        stop_handler=make_stop_handler(max_pages),
        link_extractor=link_extractor,
        use_playwright=True  # internal Playwright usage by extractor
    )

    print("[INFO] Finished. JSONL written:", output_file)


if __name__ == "__main__":
    try:
        asyncio.run(run_recall_interactive())
    except KeyboardInterrupt:
        print("Interrupted by user.")