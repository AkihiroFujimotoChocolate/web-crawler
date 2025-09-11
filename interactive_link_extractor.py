from __future__ import annotations
from typing import Callable, List, Dict, Any, Optional
from urllib.parse import urldefrag
import re
import time

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sync_playwright = None
    PlaywrightTimeoutError = Exception

from bs4 import BeautifulSoup


# ---------------- Baseline (静的) 抽出 ----------------

def default_link_extractor(scraped_page) -> List[str]:
    soup = BeautifulSoup(scraped_page.html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 相対→絶対解決が必要ならここで urljoin(scraped_page.url, href)
        out.append(href)
    # 順序保持重複排除
    return list(dict.fromkeys(out))


# ---------------- Factory ----------------

def make_interactive_link_extractor(user_cfg: Dict[str, Any]) -> Callable:
    """
    呼び出し側で設定する高機能 link_extractor を生成。
    - 既存の静的リンク収集 (baseline)
    - Playwright を内部で起動し:
        1. Listbox (件数指定) 正規表現トリガ → オプション選択
        2. Scroll
        3. Pagination (次へボタン探索 + 正規表現 fallback)
    - 追加リンクをマージして返す
    """
    cfg = _merge_with_defaults(user_cfg)

    def extractor(scraped_page) -> List[str]:
        base_links = default_link_extractor(scraped_page)

        if not cfg["enabled"]:
            return base_links

        # 対象ドメイン制限
        if cfg["domains"]:
            if not any(scraped_page.url.startswith(f"https://{d}") or
                       scraped_page.url.startswith(f"http://{d}") for d in cfg["domains"]):
                return base_links

        # 動的展開判定
        if not _should_trigger_dynamic(scraped_page, base_links, cfg):
            return base_links

        if sync_playwright is None:
            return base_links  # Playwright 利用不可フォールバック

        dynamic_links: List[str] = []
        meta: Dict[str, Any] = {
            "listbox": None,
            "scroll": None,
            "pagination": None,
            "errors": []
        }

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=cfg["playwright"]["headless"])
                context = browser.new_context(user_agent=cfg["playwright"]["user_agent"]) \
                    if cfg["playwright"]["user_agent"] else browser.new_context()
                page = context.new_page()
                page.set_default_timeout(cfg["playwright"]["timeout_ms"])
                page.goto(scraped_page.url, wait_until=cfg["wait_until"])

                # Listbox
                if cfg["listbox"]["enabled"]:
                    try:
                        meta["listbox"] = _apply_listbox(page, cfg["listbox"])
                    except Exception as e:
                        meta["errors"].append(f"listbox:{e}")

                # Scroll
                if cfg["scroll"]["enabled"]:
                    try:
                        meta["scroll"] = _apply_scroll(page, cfg["scroll"])
                    except Exception as e:
                        meta["errors"].append(f"scroll:{e}")

                # 初期リンク取得
                dynamic_links = _collect_links(page)

                # Pagination
                if cfg["pagination"]["enabled"]:
                    try:
                        pagination_result = _apply_pagination(page, cfg["pagination"], dynamic_links)
                        meta["pagination"] = pagination_result
                        dynamic_links = pagination_result["final_links"]
                    except Exception as e:
                        meta["errors"].append(f"pagination:{e}")

                # 最終スナップショット保険
                final_links_snapshot = _collect_links(page)
                dynamic_links.extend(final_links_snapshot)

                browser.close()
        except Exception as e:
            meta["errors"].append(f"playwright_root:{e}")

        merged = _normalize_and_merge(base_links, dynamic_links, cfg["link_normalization"])

        if hasattr(scraped_page, "extras") and isinstance(scraped_page.extras, dict):
            scraped_page.extras.setdefault("interactive", {})
            scraped_page.extras["interactive"].update(meta)
            scraped_page.extras["interactive"]["base_link_count"] = len(base_links)
            scraped_page.extras["interactive"]["final_link_count"] = len(merged)

        return merged

    return extractor


# ---------------- Config Merge ----------------

def _merge_with_defaults(user_cfg: Dict[str, Any]) -> Dict[str, Any]:
    default = {
        "enabled": True,
        "domains": [],
        "wait_until": "domcontentloaded",
        "dynamic_trigger": {
            "min_initial_links": 0,
            "force_patterns": [],
        },
        "listbox": {
            "enabled": False,
            "select_selectors": [],
            "trigger_selectors": [],   # 明示 CSS/テキストセレクタ
            "trigger_text_regex": None,  # 正規表現でトリガ候補探索 (例: r"件ごとに表示")
            "desired_options": [],
            "prefer_value_match": True,
            "option_selectors": [
                "ul[role='listbox'] [role='option']",
                "[role='menu'] [role='menuitem']",
                ".dropdown-menu li",
                ".menu li",
                "[role='option']"
            ],
            "wait_after_select": {
                "selector": None,
                "timeout_ms": 10000,
                "load_state": None,
                "debounce_ms": 200
            },
            "skip_if_already_selected": True,
            "continue_on_failure": True
        },
        "scroll": {
            "enabled": False,
            "step_px": 1200,
            "max_steps": 5,
            "delay_ms": 300,
            "stop_if_no_dom_change": True,
            "stability_passes": 2
        },
        "pagination": {
            "enabled": False,
            "next_selector_candidates": [
                "a[rel='next']",
                "text=次へ",
                "text=さらに表示",
                "text=More",
                "text=Load more",
                "a.next",
                ".pagination-next"
            ],
            "max_clicks": 5,
            "wait_after_click": {
                "selector": None,
                "timeout_ms": 12000,
                "load_state": "domcontentloaded",
                "debounce_wait_ms": 250
            },
            "stop_if_no_new_links": True,
            "regex_role_fallback": {   # ← 追加: 通常候補が無い時の正規表現 fallback
                "enabled": False,
                "roles": ["link", "button"],
                "name_pattern": r"(次へ|さらに表示)"  # 例
            }
        },
        "link_normalization": {
            "strip_fragment": True,
            "unique": True
        },
        "playwright": {
            "headless": True,
            "user_agent": None,
            "timeout_ms": 30000
        }
    }
    import copy
    cfg = copy.deepcopy(default)

    def deep_update(d, u):
        for k, v in u.items():
            if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                deep_update(d[k], v)
            else:
                d[k] = v
    deep_update(cfg, user_cfg)
    return cfg


# ---------------- Dynamic Trigger ----------------

def _should_trigger_dynamic(scraped_page, base_links: List[str], cfg: Dict[str, Any]) -> bool:
    dt = cfg["dynamic_trigger"]
    if dt["force_patterns"]:
        for pat in dt["force_patterns"]:
            if re.search(pat, scraped_page.url):
                return True
    if len(base_links) < dt["min_initial_links"]:
        return True
    # インタラクションが一つでも有効なら対象
    if (cfg["listbox"]["enabled"] or cfg["scroll"]["enabled"] or cfg["pagination"]["enabled"]):
        return True
    return False


# ---------------- Link Collect & Merge ----------------

def _collect_links(page) -> List[str]:
    try:
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        seen = {}
        for h in hrefs:
            if h not in seen:
                seen[h] = True
        return list(seen.keys())
    except Exception:
        return []


def _normalize_and_merge(base_links: List[str], add_links: List[str], norm_cfg: Dict[str, Any]) -> List[str]:
    merged = list(base_links) + list(add_links)
    cleaned = []
    seen = set()
    for link in merged:
        if norm_cfg.get("strip_fragment"):
            link = urldefrag(link)[0]
        if norm_cfg.get("unique"):
            if link in seen:
                continue
            seen.add(link)
        cleaned.append(link)
    return cleaned


# ---------------- Listbox Interaction ----------------

def _apply_listbox(page, cfg: Dict[str, Any]) -> Dict[str, Any]:
    desired = cfg.get("desired_options") or []
    if not desired:
        return {"status": "skipped", "reason": "no_desired_options"}

    # 1) Native <select>
    for sel in cfg.get("select_selectors", []):
        loc = page.locator(sel)
        if loc.count() == 0 or not loc.first.is_visible():
            continue
        current_val = None
        try:
            current_val = loc.input_value()
        except Exception:
            pass
        if cfg.get("skip_if_already_selected") and current_val and current_val in desired:
            return {"status": "already_selected", "value": current_val, "mode": "native-select"}

        for opt in desired:
            # value マッチ優先
            if cfg.get("prefer_value_match", True):
                try:
                    result = loc.select_option(value=opt)
                    if result and result[0] == opt:
                        _wait_after_select(page, cfg.get("wait_after_select", {}))
                        return {"status": "selected", "value": opt, "mode": "native-select"}
                except Exception:
                    pass
            # テキスト fallback
            try:
                options = loc.locator("option")
                for i in range(options.count()):
                    o = options.nth(i)
                    text_norm = _normalize_option_text(o.inner_text())
                    if text_norm == _normalize_option_text(opt):
                        val_attr = o.get_attribute("value")
                        if val_attr:
                            page.evaluate(
                                "(el,val)=>{el.value=val;el.dispatchEvent(new Event('change',{bubbles:true}))}",
                                loc.element_handle(), val_attr
                            )
                            _wait_after_select(page, cfg.get("wait_after_select", {}))
                            return {"status": "selected_text_match", "value": opt, "mode": "native-select"}
            except Exception:
                pass

    # 2) Custom Dropdown
    # 2-1) 明示 trigger_selectors
    for trig_sel in cfg.get("trigger_selectors", []):
        if _try_dropdown_trigger(page, trig_sel, desired, cfg):
            return {"status": "selected", "mode": "custom-dropdown", "trigger": trig_sel}

    # 2-2) trigger_text_regex
    regex_pat = cfg.get("trigger_text_regex")
    if regex_pat:
        candidate = _find_element_by_regex_text(page, regex_pat)
        if candidate is not None:
            try:
                candidate.click()
                if _dropdown_select_option(page, cfg, desired):
                    return {"status": "selected", "mode": "custom-dropdown", "trigger": f"regex:{regex_pat}"}
            except Exception:
                pass

    return {"status": "not_found"}


def _try_dropdown_trigger(page, trig_sel: str, desired: List[str], cfg: Dict[str, Any]) -> bool:
    trig = page.locator(trig_sel)
    if trig.count() == 0 or not trig.first.is_visible():
        return False
    try:
        trig.first.click()
    except Exception:
        return False
    return _dropdown_select_option(page, cfg, desired)


def _dropdown_select_option(page, cfg: Dict[str, Any], desired: List[str]) -> bool:
    option_selectors = cfg.get("option_selectors") or []
    for opt_sel in option_selectors:
        candidates = page.locator(opt_sel)
        count = candidates.count()
        if count == 0:
            continue
        # Map
        idx_map = []
        for i in range(count):
            el = candidates.nth(i)
            try:
                if not el.is_visible():
                    continue
                raw = el.inner_text()
            except Exception:
                continue
            norm = _normalize_option_text(raw)
            idx_map.append((i, norm))
        for wanted in desired:
            wn = _normalize_option_text(wanted)
            match = next((i for (i, norm) in idx_map if norm == wn), None)
            if match is not None:
                try:
                    candidates.nth(match).click()
                    _wait_after_select(page, cfg.get("wait_after_select", {}))
                    return True
                except Exception:
                    continue
    return False


def _find_element_by_regex_text(page, pattern: str):
    # シンプル実装: a, button, [role=button]
    pat = re.compile(pattern)
    selectors = ["a", "button", "[role=button]"]
    for sel in selectors:
        loc = page.locator(sel)
        count = loc.count()
        for i in range(count):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                txt = (el.inner_text() or "").strip()
                aria = el.get_attribute("aria-label") or ""
                title = el.get_attribute("title") or ""
                comp = " ".join([txt, aria, title])
                if pat.search(comp):
                    return el
            except Exception:
                continue
    return None


def _normalize_option_text(text: str) -> str:
    if text is None:
        return ""
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(件表示|件/ページ|件|items?/page|items?|per page)$", "", t, flags=re.IGNORECASE)
    return t.strip()


def _wait_after_select(page, cfg: Dict[str, Any]):
    if not cfg:
        return
    sel = cfg.get("selector")
    load_state = cfg.get("load_state")
    timeout = cfg.get("timeout_ms") or 10000
    if sel:
        try:
            page.wait_for_selector(sel, timeout=timeout)
        except Exception:
            pass
    elif load_state:
        try:
            page.wait_for_load_state(load_state)
        except Exception:
            pass
    debounce = cfg.get("debounce_ms") or 0
    if debounce:
        time.sleep(debounce / 1000.0)


# ---------------- Scroll Interaction ----------------

def _apply_scroll(page, cfg: Dict[str, Any]) -> Dict[str, Any]:
    step = cfg["step_px"]
    max_steps = cfg["max_steps"]
    delay = cfg["delay_ms"] / 1000.0
    stop_if_stable = cfg.get("stop_if_no_dom_change", True)
    stability_passes = cfg.get("stability_passes", 2)

    prev_height = page.evaluate("() => document.body.scrollHeight")
    stable_count = 0
    performed = 0

    for _ in range(max_steps):
        page.evaluate(f"window.scrollBy(0,{step});")
        time.sleep(delay)
        new_height = page.evaluate("() => document.body.scrollHeight")
        performed += 1
        if new_height == prev_height:
            if stop_if_stable:
                stable_count += 1
                if stable_count >= stability_passes:
                    break
        else:
            stable_count = 0
        prev_height = new_height

    return {
        "performed_steps": performed,
        "final_height": prev_height,
        "stopped_for_stability": stable_count >= stability_passes
    }


# ---------------- Pagination Interaction ----------------

def _apply_pagination(page, cfg: Dict[str, Any], working_links: List[str]) -> Dict[str, Any]:
    candidates = cfg["next_selector_candidates"]
    max_clicks = cfg["max_clicks"]
    stop_if_no_new = cfg.get("stop_if_no_new_links", True)
    wait_cfg = cfg.get("wait_after_click", {})
    regex_fb = cfg.get("regex_role_fallback", {})
    clicks = 0
    total_new = 0

    def wait_after():
        sel = wait_cfg.get("selector")
        load_state = wait_cfg.get("load_state")
        timeout = wait_cfg.get("timeout_ms") or 12000
        debounce = wait_cfg.get("debounce_wait_ms") or 0
        if sel:
            try:
                page.wait_for_selector(sel, timeout=timeout)
            except Exception:
                pass
        elif load_state:
            try:
                page.wait_for_load_state(load_state)
            except Exception:
                pass
        if debounce:
            time.sleep(debounce / 1000.0)

    while clicks < max_clicks:
        before = set(working_links)
        next_btn = _find_next_button(page, candidates)

        if not next_btn and regex_fb.get("enabled"):
            next_btn = _regex_role_fallback(page, regex_fb)

        if not next_btn:
            break

        try:
            next_btn.click()
        except Exception:
            break

        wait_after()
        new_links = _collect_links(page)
        for l in new_links:
            if l not in working_links:
                working_links.append(l)
        delta = len(set(working_links) - before)
        total_new += delta
        clicks += 1
        if stop_if_no_new and delta == 0:
            break

    return {
        "clicks": clicks,
        "total_new_links": total_new,
        "final_links": list(working_links)
    }


def _find_next_button(page, candidates: List[str]):
    for sel in candidates:
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        first = loc.first
        try:
            if first.is_visible() and first.is_enabled():
                return first
        except Exception:
            continue
    return None


def _regex_role_fallback(page, cfg: Dict[str, Any]):
    pattern = cfg.get("name_pattern")
    if not pattern:
        return None
    pat = re.compile(pattern)
    roles = cfg.get("roles") or ["link", "button"]
    for r in roles:
        try:
            role_loc = page.get_by_role(r)
            count = role_loc.count()
            for i in range(count):
                el = role_loc.nth(i)
                try:
                    if not el.is_visible() or not el.is_enabled():
                        continue
                    name = (el.inner_text() or "").strip()
                    if pat.search(name):
                        return el
                except Exception:
                    continue
        except Exception:
            continue
    return None