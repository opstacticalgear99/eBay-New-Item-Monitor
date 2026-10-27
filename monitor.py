
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
OUTBOX_FILE = Path(os.getenv("EBAY_OUTBOX_FILE", "ebay_outbox.json"))

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
        **{key: old[key] for key in ("configured_brand_queries", "configured_sellers", "monitor_settings", "condition_policy_version") if key in old},
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


def is_new_condition(item):
    # eBay uses the same ID for names such as New, New with tags and Brand New.
    condition_id = str(item.get("conditionId", ""))
    if condition_id:
        return condition_id == "1000"
    return str(item.get("condition", "")).strip().casefold() in {
        "", "new", "brand new", "new with tags", "new in box",
        "new with box", "new with defects", "new without tags",
    }


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
            if not BRAND_INCLUDE_USED and not is_new_condition(item):
                continue

            item["_monitor_condition_expansion"] = bool(condition and condition != "new")
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


def fetch_brand_items(session, token, brands=None, initialized_queries=None):
    all_items = {}
    errors = []

    for label, query in (BRANDS if brands is None else brands):
        try:
            items = api_search_brand(session, token, label, query)
            for item in items:
                item_id = str(item["itemId"])
                item["_monitor_notify"] = initialized_queries is None or query in initialized_queries
                if item_id in all_items:
                    existing = all_items[item_id]
                    existing["_monitor_notify"] = existing.get("_monitor_notify", False) or item["_monitor_notify"]
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

# ============================================================
# eBay seller monitoring via Browse API
# ============================================================

def fetch_all_sellers(session, token, sellers=None, initialized_sellers=None):
    sellers = SELLERS if sellers is None else sellers
    if not sellers:
        return {}, []
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
        "Accept": "application/json",
    }

    sellers_filter = "|".join(sellers)
    all_items = {}
    errors = []
    offset = 0

    while offset < API_MAX_ITEMS_PER_QUERY:
        params = {
            # q is required by the Browse API search endpoint.
            # A broad query plus sellers filter searches the target sellers.
            "q": " ",
            "filter": f"sellers:{{{sellers_filter}}}",
            "limit": API_PAGE_SIZE,
            "offset": offset,
            "sort": "newlyListed",
        }

        try:
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
            total = int(data.get("total", 0) or 0)

            logging.info(
                "Seller API offset=%s page=%s total=%s",
                offset, len(page), total
            )

            for item in page:
                item_id = str(item.get("itemId", "")).strip()
                if not item_id:
                    continue

                seller_info = item.get("seller", {}) or {}
                seller_name = str(
                    seller_info.get("username", "")
                ).strip()

                # Only accept items belonging to the configured sellers.
                matched_seller = next(
                    (
                        seller for seller in sellers
                        if seller_name.casefold() == seller.casefold()
                    ),
                    None,
                )

                if not matched_seller:
                    logging.warning(
                        "Ignoring item %s: unexpected seller %r",
                        item_id, seller_name
                    )
                    continue

                item["_monitor_notify"] = initialized_sellers is None or matched_seller.casefold() in initialized_sellers
                item["_monitor_source"] = "seller"
                item["_monitor_label"] = matched_seller
                all_items[item_id] = item

            if not page or len(page) < API_PAGE_SIZE:
                break

            offset += API_PAGE_SIZE
            if offset >= total:
                break

        except Exception as exc:
            errors.append(f"Seller API offset {offset}: {exc}")
            logging.exception("Seller API search failed at offset %s", offset)
            break

    logging.info(
        "Seller API results=%s errors=%s",
        len(all_items), len(errors)
    )

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
    if (parsed.scheme == "https" and parsed.netloc == "www.ronintactics.com"
            and re.match(r"^/store/p\d+/[^/]+\.html$", parsed.path)):
        return url
    if (parsed.scheme == "https" and parsed.netloc == "forwardobservations.com"
            and re.match(r"^/products/[^/]+$", parsed.path)):
        return url
    if parsed.scheme == "https" and parsed.netloc.endswith("ebay.com"):
        return url

    return ""


def sync_app_notifications(items):
    """
    Optional best-effort sync to the companion iPhone PWA.
    Disabled unless APP_API_URL and APP_API_TOKEN are configured.
    Failures are logged but must never prevent the existing state save.
    """
    api_url = os.getenv("APP_API_URL", "").strip().rstrip("/")
    api_token = os.getenv("APP_API_TOKEN", "").strip()

    if not api_url or not api_token:
        logging.info("App push sync is not configured; skipping.")
        return

    payload_items = []
    for item in items:
        payload_items.append({
            "itemId": str(item.get("itemId", "")),
            "title": str(item.get("title") or "Untitled listing"),
            "price": price_to_text(item.get("price")),
            "url": item_link(item),
            "condition": str(item.get("condition") or "Not specified"),
            "source": str(item.get("_monitor_label") or item.get("_monitor_source") or "eBay"),
            "labels": item.get("_monitor_labels") or [item.get("_monitor_label", "eBay listing")],
        })

    # The receiver accepts at most 100 items in one request.
    all_synced = True
    for offset in range(0, len(payload_items), 100):
        try:
            response = requests.post(
                f"{api_url}/api/monitor/sync",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json={"items": payload_items[offset:offset + 100]},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            logging.info("App notification sync completed: %s", response.status_code)
        except Exception:
            all_synced = False
            logging.exception(
                "App notification sync failed; existing email/state workflow will continue."
            )

    return all_synced


def send_email(items, errors, subject_prefix="eBay Monitor"):
    smtp_user = required_env("GMAIL_ADDRESS")
    smtp_password = required_env("GMAIL_APP_PASSWORD")
    recipient = required_env("ALERT_TO")

    subject = f"{subject_prefix}: {len(items)} new listing(s)"

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

def validate_monitor_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid monitor settings")
    brands, sellers = data.get("brands"), data.get("sellers")
    if not isinstance(brands, list) or not 1 <= len(brands) <= 50:
        raise ValueError("Expected 1–50 brand queries")
    if not isinstance(sellers, list) or not 1 <= len(sellers) <= 20:
        raise ValueError("Expected 1–20 sellers")
    for entry in brands:
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(key), str) or not entry[key].strip()
            or len(entry[key]) > 120 or any(c in entry[key] for c in "\r\n")
            for key in ("label", "query")
        ):
            raise ValueError("Invalid brand query")
    for seller in sellers:
        if not isinstance(seller, str) or not re.fullmatch(r"[A-Za-z0-9_.*-]{1,64}", seller):
            raise ValueError("Invalid seller username")
    return {"brands": brands, "sellers": sellers}


def load_monitor_settings(state):
    defaults = {"brands": [{"label": label, "query": query} for label, query in BRANDS], "sellers": list(SELLERS)}
    cached = validate_monitor_settings(state.get("monitor_settings", defaults))
    api_url = os.getenv("APP_API_URL", "").strip().rstrip("/")
    api_token = os.getenv("APP_API_TOKEN", "").strip()
    if not api_url or not api_token:
        return cached
    try:
        response = requests.get(
            f"{api_url}/api/monitor/settings",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return validate_monitor_settings(response.json())
    except Exception:
        # A receiver outage must not reset filters or stop existing Gmail alerts.
        logging.warning("Cannot load web settings; using last saved settings (or original defaults).")
        return cached


def load_outbox():
    if not OUTBOX_FILE.exists():
        return []
    data = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
    if (not isinstance(data, list) or any(
        not isinstance(e, dict) or not isinstance(e.get("item"), dict)
        or not e["item"].get("itemId")
        or type(e.get("email_sent")) is not bool or type(e.get("app_sent")) is not bool
        for e in data
    )):
        raise ValueError("Invalid eBay outbox; refusing to discard pending alerts")
    return data


def save_outbox(entries):
    OUTBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTBOX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    tmp.replace(OUTBOX_FILE)


def deliver_outbox(entries, errors):
    email_error = None
    unsent = [e for e in entries if not e["email_sent"]]
    if unsent:
        try:
            send_email([e["item"] for e in unsent], errors)
            for entry in unsent:
                entry["email_sent"] = True
            save_outbox(entries)
        except Exception as exc:
            email_error = exc
            logging.error("Gmail delivery failed; queued for retry. App delivery will still run.")
    pending = [e for e in entries if not e["app_sent"]]
    if pending:
        result = sync_app_notifications([e["item"] for e in pending])
        # None means deliberately unconfigured. False means a retry is needed.
        if result is not False:
            for entry in pending:
                entry["app_sent"] = True
    entries[:] = [e for e in entries if not (e["email_sent"] and e["app_sent"])]
    save_outbox(entries)
    logging.info("eBay pending notification deliveries=%s", len(entries))
    if email_error:
        raise RuntimeError("Gmail delivery failed; pending alerts preserved") from email_error


def main():
    state = load_state()
    outbox = load_outbox()
    session = requests.Session()
    try:
        token = get_access_token()
    except Exception:
        if outbox:
            deliver_outbox(outbox, [])
        raise

    settings = load_monitor_settings(state)
    brands = [(entry["label"], entry["query"]) for entry in settings["brands"]]
    sellers = settings["sellers"]
    known_queries = set(state.get("configured_brand_queries", [q for _, q in BRANDS] if state["brand_initialized"] else []))
    known_sellers = set(state.get("configured_sellers", [s.casefold() for s in SELLERS] if state["seller_initialized"] else []))
    brand_items, brand_errors = fetch_brand_items(session, token, brands, known_queries)
    seller_items, seller_errors = fetch_all_sellers(session, token, sellers, known_sellers)

    errors = brand_errors + seller_errors

    old_brand_ids = set(state["brand_seen_ids"])
    old_seller_ids = set(state["seller_seen_ids"])

    current_brand_ids = set(brand_items.keys())
    current_seller_ids = set(seller_items.keys())

    # Only notify on new items after that source has a complete baseline.
    new_items = []

    if state["brand_initialized"]:
        for item_id in current_brand_ids - old_brand_ids:
            item = brand_items[item_id]
            expansion_baseline = state.get("condition_policy_version", 1) < 2 and item.get("_monitor_condition_expansion", False)
            if item.get("_monitor_notify", True) and not expansion_baseline:
                new_items.append(brand_items[item_id])

    if state["seller_initialized"]:
        for item_id in current_seller_ids - old_seller_ids:
            if seller_items[item_id].get("_monitor_notify", True):
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

    queued_ids = {str(e["item"]["itemId"]) for e in outbox}
    for item in new_items:
        if str(item["itemId"]) not in queued_ids:
            outbox.append({"item": item, "email_sent": False, "app_sent": False})
    # Persist before either channel is attempted. Each channel advances separately.
    save_outbox(outbox)
    # The durable outbox now owns retries, so recording observed IDs is safe
    # before delivery and prevents repeat Gmail alerts after a Push failure.
    if brand_ok:
        state["brand_seen_ids"] = sorted(old_brand_ids | current_brand_ids)
        state["brand_initialized"] = True
        state["condition_policy_version"] = 2
        state["configured_brand_queries"] = [q for _, q in brands]
    elif state["brand_initialized"]:
        # Preserve every known ID and record only successfully observed listings.
        state["brand_seen_ids"] = sorted(old_brand_ids | current_brand_ids)
        logging.warning("Brand snapshot incomplete; preserving old and successfully observed IDs.")

    if sellers_ok:
        state["seller_seen_ids"] = sorted(old_seller_ids | current_seller_ids)
        state["seller_initialized"] = True
        state["configured_sellers"] = [s.casefold() for s in sellers]
    elif state["seller_initialized"]:
        state["seller_seen_ids"] = sorted(old_seller_ids | current_seller_ids)
        logging.warning("Seller snapshot incomplete; preserving old and successfully observed IDs.")

    state["monitor_settings"] = settings
    save_state(state)
    if outbox:
        deliver_outbox(outbox, errors)

    if errors:
        logging.warning("Completed with %s monitoring warning(s).", len(errors))
    else:
        logging.info("Monitoring completed successfully.")


if __name__ == "__main__":
    main()

