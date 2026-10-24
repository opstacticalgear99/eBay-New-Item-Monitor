
import os
import re
import json
import html
import time
import base64
import logging
import smtplib
import requests

from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ============================================================
# Configuration
# ============================================================

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

MARKETPLACE = os.getenv("EBAY_MARKETPLACE", "EBAY_US")
STATE_FILE = Path(os.getenv("STATE_FILE", "seen_items.json"))

# Browse API returns at most 200 results per page.
API_PAGE_SIZE = 200
API_MAX_ITEMS_PER_QUERY = 1000

# Seller page scraping settings.
SELLER_PAGE_SIZE = 240
SELLER_MAX_PAGES = 20

REQUEST_TIMEOUT = 30

SELLERS = [
    "skemos-0",
    "11*thedude",
]

# Preserve the previous brand/search keywords.
# Seller usernames are monitored separately below.
BRANDS = [
    ("SureFire m340v", "SureFire m340v"),
    ("SureFire m952v", "SureFire m952v"),
    ("SureFire vampire", "SureFire vampire"),
    ("SureFire ds00", "SureFire ds00"),
    ("S&S Precision", '"S&S Precision"'),
    ("Mystery Ranch ASAP", '"Mystery Ranch ASAP"'),
    ("Mystery Ranch multicam", '"Mystery Ranch multicam"'),
    ("Mystery Ranch komodo", '"Mystery Ranch komodo"'),
    ("Juggernaut case mount", "Juggenaut case mount"),
    ("L3 Harris GPNVG", "L3 harris gpnvg"),
    ("Outdoor Research Firemark", "outdoor research firemark"),
    ("Ops-Core single band U94 PTT", "ops-core single band u94 ptt"),
    ("Ops-Core FTHS", "ops core fths"),
    ("LBT 6074A", "lbt 6074a"),
    ("L3 Harris battery pack multicam", "l3 harris battery pack multicam"),
    ("Kagwerks S20", "kagwerks s20"),
    ("Core Survival", "core survival"),
    ("Crye Precision NSW", "crye precision nsw contoured"),
]

# Set to true only if you also want brand searches to include used items.
BRAND_INCLUDE_USED = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ============================================================
# Environment / state
# ============================================================

def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_state():
    """
    Migrate the previous state format:
        {"initialized": true, "seen_ids": [...]}

    Old seen_ids are preserved for brand monitoring.
    Seller monitoring gets its own baseline, preventing an initial
    email containing every currently listed seller item.
    """
    if not STATE_FILE.exists():
        return {
            "brand_initialized": False,
            "brand_seen_ids": [],
            "seller_initialized": False,
            "seller_seen_ids": [],
        }

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot read {STATE_FILE}: {exc}. "
            "Fix the state file instead of silently resetting it."
        ) from exc

    brand_seen = old.get("brand_seen_ids")
    if brand_seen is None:
        brand_seen = old.get("seen_ids", [])

    brand_initialized = old.get("brand_initialized")
    if brand_initialized is None:
        brand_initialized = bool(old.get("initialized", False))

    return {
        "brand_initialized": bool(brand_initialized),
        "brand_seen_ids": list(set(map(str, brand_seen))),
        "seller_initialized": bool(old.get("seller_initialized", False)),
        "seller_seen_ids": list(
            set(map(str, old.get("seller_seen_ids", [])))
        ),
    }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    temp_file.replace(STATE_FILE)


# ============================================================
# eBay Browse API: brand searches
# ============================================================

def get_access_token():
    client_id = required_env("EBAY_CLIENT_ID")
    client_secret = required_env("EBAY_CLIENT_SECRET")

    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")

    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("eBay OAuth response did not contain access_token")

    return token


def api_search_brand(session, token, label, query):
    """
    Search new-condition items for one keyword.
    A failed keyword search raises an exception so the run can log it.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
        "Accept": "application/json",
    }

    if BRAND_INCLUDE_USED:
        filters = None
    else:
        filters = "conditionIds:{1000}"

    results = []
    offset = 0

    while offset < API_MAX_ITEMS_PER_QUERY:
        params = {
            "q": query,
            "limit": API_PAGE_SIZE,
            "offset": offset,
            "sort": "newlyListed",
        }

        if filters:
            params["filter"] = filters

        response = session.get(
            SEARCH_URL,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            time.sleep(3)
            response = session.get(
                SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

        response.raise_for_status()
        data = response.json()
        page = data.get("itemSummaries", [])

        for item in page:
            item_id = str(item.get("itemId", "")).strip()
            if not item_id:
                continue

            # Keep a second condition check for consistency with the
            # previous monitor's behavior.
            condition = str(item.get("condition", "")).strip().lower()
            if not BRAND_INCLUDE_USED and condition and condition != "new":
                continue

            item["_monitor_source"] = "brand"
            item["_monitor_label"] = label
            results.append(item)

        total = int(data.get("total", 0) or 0)
        logging.info(
            "Brand query=%r offset=%s page=%s total=%s",
            query, offset, len(page), total
        )

        if not page or len(page) < API_PAGE_SIZE:
            break

        offset += API_PAGE_SIZE

        if offset >= total:
            break

    return results


def fetch_brand_items(session, token):
    all_items = {}
    errors = []

    for label, query in BRANDS:
        try:
            items = api_search_brand(session, token, label, query)
            for item in items:
                item_id = str(item["itemId"])
                if item_id in all_items:
                    existing = all_items[item_id]
                    existing_labels = existing.setdefault("_monitor_labels", [])
                    if label not in existing_labels:
                        existing_labels.append(label)
                else:
                    item["_monitor_labels"] = [label]
                    all_items[item_id] = item

        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logging.exception("Brand search failed: %s", label)

    return all_items, errors


# ============================================================
# eBay seller pages: all currently listed seller items
# ============================================================

def item_id_from_url(url):
    if not url:
        return None

    # Common eBay URLs:
    # /itm/123456789012
    # /itm/Some-Title/123456789012
    match = re.search(r"/itm/(?:[^/?#]+/)?(\d{9,15})(?:[/?#]|$)", url)
    if match:
        return match.group(1)

    match = re.search(r"[?&]item=(\d{9,15})(?:&|$)", url)
    if match:
        return match.group(1)

    return None


def scrape_seller_page(session, seller, page_number):
    url = "https://www.ebay.com/sch/i.html"

    params = {
        "_ssn": seller,
        "_ipg": SELLER_PAGE_SIZE,
        "_pgn": page_number,
        "_sop": 10,  # newly listed
    }

    response = session.get(
        url,
        params=params,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Do not treat a CAPTCHA or changed page structure as an empty result.
    page_text = soup.get_text(" ", strip=True).lower()
    blocked_markers = [
        "verify you are human",
        "robot check",
        "captcha",
        "security measure",
    ]
    if any(marker in page_text for marker in blocked_markers):
        raise RuntimeError(
            f"eBay blocked or challenged seller page for {seller}"
        )

    cards = soup.select("li.s-item")
    if not cards:
        raise RuntimeError(
            f"No listing cards found for seller {seller}, page {page_number}. "
            "The page may have changed or access may be blocked."
        )

    items = []

    for card in cards:
        link = card.select_one("a.s-item__link")
        title_el = card.select_one(".s-item__title")
        price_el = card.select_one(".s-item__price")

        if not link:
            continue

        item_url = link.get("href", "").strip()
        item_id = item_id_from_url(item_url)

        if not item_id:
            continue

        title = title_el.get_text(" ", strip=True) if title_el else ""
        if not title or title.lower() in {
            "shop on ebay",
            "results matching fewer words",
        }:
            continue

        price = price_el.get_text(" ", strip=True) if price_el else "Price not shown"

        items.append({
            "itemId": item_id,
            "title": title,
            "itemWebUrl": item_url,
            "price": price,
            "condition": "",
            "seller": {"username": seller},
            "_monitor_source": "seller",
            "_monitor_label": seller,
        })

    return items, len(cards)


def fetch_seller_items(session, seller):
    all_items = {}
    page_number = 1

    while page_number <= SELLER_MAX_PAGES:
        items, card_count = scrape_seller_page(
            session, seller, page_number
        )

        logging.info(
            "Seller=%r page=%s parsed_items=%s cards=%s",
            seller, page_number, len(items), card_count
        )

        for item in items:
            all_items[item["itemId"]] = item

        # Fewer cards than the configured page size usually means the
        # final page. If eBay changes its page size, inspect the logs.
        if card_count < SELLER_PAGE_SIZE:
            break

        page_number += 1

    if page_number > SELLER_MAX_PAGES:
        logging.warning(
            "Seller %s reached SELLER_MAX_PAGES=%s; older pages may be omitted.",
            seller, SELLER_MAX_PAGES
        )

    return all_items


def fetch_all_sellers(session):
    all_items = {}
    errors = []

    for seller in SELLERS:
        try:
            items = fetch_seller_items(session, seller)
            logging.info("Seller %s: found %s current listings", seller, len(items))

            for item_id, item in items.items():
                all_items[item_id] = item

        except Exception as exc:
            errors.append(f"{seller}: {exc}")
            logging.exception("Seller scrape failed: %s", seller)

    return all_items, errors


# ============================================================
# Email
# ============================================================

def price_to_text(price):
    if isinstance(price, dict):
        value = price.get("value")
        currency = price.get("currency", "")
        if value is not None:
            return f"{value} {currency}".strip()

    if price is None:
        return "Price not shown"

    return str(price)


def item_link(item):
    url = item.get("itemWebUrl") or item.get("url") or ""
    if url.startswith("https://www.ebay.com/itm/") or url.startswith("https://ebay.com/itm/"):
        return url

    # Permit legitimate eBay item links on other regional domains.
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc.endswith("ebay.com"):
        return url

    return ""


def send_email(items, errors):
    smtp_user = required_env("GMAIL_USER")
    smtp_password = required_env("GMAIL_APP_PASSWORD")
    recipient = required_env("EMAIL_TO")

    subject = f"eBay Monitor: {len(items)} new listing(s)"

    html_rows = []
    text_rows = []

    for item in items:
        title = item.get("title") or "Untitled listing"
        url = item_link(item)
        price = price_to_text(item.get("price"))
        condition = item.get("condition") or "Not specified"

        labels = item.get("_monitor_labels")
        if not labels:
            labels = [item.get("_monitor_label", "eBay listing")]

        source = ", ".join(labels)

        if url:
            title_html = (
                f'<a href="{html.escape(url, quote=True)}">'
                f'{html.escape(title)}</a>'
            )
            text_title = f"{title}\n{url}"
        else:
            title_html = html.escape(title)
            text_title = title

        html_rows.append(
            "<li>"
            f"<strong>{title_html}</strong><br>"
            f"Price: {html.escape(price)}<br>"
            f"Condition: {html.escape(condition)}<br>"
            f"Matched: {html.escape(source)}"
            "</li>"
        )

        text_rows.append(
            f"- {text_title}\n"
            f"  Price: {price}\n"
            f"  Condition: {condition}\n"
            f"  Matched: {source}"
        )

    if errors:
        error_html = (
            "<h3>Monitoring warnings</h3><ul>"
            + "".join(f"<li>{html.escape(e)}</li>" for e in errors)
            + "</ul>"
        )
        error_text = "\n\nWarnings:\n" + "\n".join(f"- {e}" for e in errors)
    else:
        error_html = ""
        error_text = ""

    html_body = (
        "<html><body>"
        f"<h2>{len(items)} new eBay listing(s)</h2>"
        "<ol>" + "".join(html_rows) + "</ol>"
        + error_html
        + "</body></html>"
    )

    text_body = (
        f"{len(items)} new eBay listing(s)\n\n"
        + "\n\n".join(text_rows)
        + error_text
    )

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = recipient
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [recipient], message.as_string())

    logging.info("Email sent to %s", recipient)


# ============================================================
# Main
# ============================================================

def main():
    state = load_state()

    session = requests.Session()
    token = get_access_token()

    brand_items, brand_errors = fetch_brand_items(session, token)
    seller_items, seller_errors = fetch_all_sellers(session)

    errors = brand_errors + seller_errors

    old_brand_ids = set(state["brand_seen_ids"])
    old_seller_ids = set(state["seller_seen_ids"])

    current_brand_ids = set(brand_items.keys())
    current_seller_ids = set(seller_items.keys())

    # Only notify on new items after that source has a complete baseline.
    new_items = []

    if state["brand_initialized"]:
        for item_id in current_brand_ids - old_brand_ids:
            new_items.append(brand_items[item_id])

    if state["seller_initialized"]:
        for item_id in current_seller_ids - old_seller_ids:
            new_items.append(seller_items[item_id])

    # Merge duplicate listings returned by both monitoring methods.
    merged = {}
    for item in new_items:
        item_id = str(item.get("itemId", ""))
        if not item_id:
            continue

        if item_id not in merged:
            merged[item_id] = item
        else:
            existing = merged[item_id]
            labels = existing.setdefault("_monitor_labels", [])
            label = item.get("_monitor_label", "eBay listing")
            if label not in labels:
                labels.append(label)

    new_items = list(merged.values())

    logging.info(
        "Brand results=%s; seller results=%s; new listings=%s",
        len(brand_items), len(seller_items), len(new_items)
    )

    # If a source has errors on its first run, do not establish a partial
    # baseline for that source. Retry next run rather than silently missing
    # listings that were not successfully checked.
    brand_ok = not brand_errors
    sellers_ok = not seller_errors

    if new_items:
        send_email(new_items, errors)

    # Advance the baseline only after the email has been sent successfully,
    # or when there is no notification to send.
    if brand_ok:
        state["brand_seen_ids"] = sorted(old_brand_ids | current_brand_ids)
        state["brand_initialized"] = True
    elif state["brand_initialized"]:
        # Preserve known IDs but don't add an incomplete snapshot.
        logging.warning("Brand snapshot incomplete; preserving previous brand state.")

    if sellers_ok:
        state["seller_seen_ids"] = sorted(old_seller_ids | current_seller_ids)
        state["seller_initialized"] = True
    elif state["seller_initialized"]:
        logging.warning("Seller snapshot incomplete; preserving previous seller state.")

    save_state(state)

    if errors:
        logging.warning("Completed with %s monitoring warning(s).", len(errors))
    else:
        logging.info("Monitoring completed successfully.")


if __name__ == "__main__":
    main()
