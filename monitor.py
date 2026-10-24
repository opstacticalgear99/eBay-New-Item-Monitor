import os
import json
import time
import smtplib
import requests
from email.message import EmailMessage
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path("seen_items.json")
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
MARKETPLACE = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
BRANDS = [
    ("SureFire", "SureFire"),
    ("S&S Precision", '"S&S Precision"'),
    ("Vans DEFCON", '"Vans DEFCON"'),
    ("Mystery Ranch", '"Mystery Ranch"'),
]

def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def get_token():
    response = requests.post(
        TOKEN_URL,
        auth=(required("EBAY_CLIENT_ID"), required("EBAY_CLIENT_SECRET")),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]

def search_brand(token, query):
   all_items = []
   limit = 200
   offset = 0
   max_items = 1000

   while offset < max_items:
       response = requests.get(
           SEARCH_URL,
           headers={
               "Authorization": f"Bearer {token}",
               "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
           },
           params={
               "q": query,
               "filter": "conditionIds:{1000}",
               "limit": str(limit),
               "offset": str(offset),
               "sort": "newlyListed",
           },
           timeout=30,
       )
       response.raise_for_status()
       data = response.json()
       items = data.get("itemSummaries", [])

       all_items.extend(items)
       print(
           f"Query={query!r}, offset={offset}, "
           f"received={len(items)}, total={data.get('total', 'unknown')}"
       )

       if len(items) < limit:
           break

       offset += len(items)
       time.sleep(0.25)

   # 按商品 ID 去重
   unique_items = {}
   for item in all_items:
       item_id = item.get("itemId")
       if item_id:
           unique_items[item_id] = item

   return list(unique_items.values())

def load_state():
    if not STATE_PATH.exists():
        return {"initialized": False, "seen_ids": []}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(state.get("seen_ids"), list):
            return state
    except (OSError, json.JSONDecodeError):
        pass
    return {"initialized": False, "seen_ids": []}

def send_email(items):
    sender = required("GMAIL_ADDRESS")
    app_password = required("GMAIL_APP_PASSWORD").replace(" ", "")
    recipient = required("ALERT_TO")
    msg = EmailMessage()
    msg["Subject"] = f"eBay 全新商品提醒：发现 {len(items)} 件新品"
    msg["From"] = sender
    msg["To"] = recipient
    lines = [
        f"扫描时间（UTC）：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "以下是 eBay API 按 New 条件返回的商品。请打开页面复核商品描述、卖家和配件。",
        "",
    ]
    for item in items:
        price = item.get("price") or {}
        lines.extend([
            f"搜索品牌：{item.get('_brand', '')}",
            f"标题：{item.get('title', '(无标题)')}",
            f"价格：{price.get('value', '未知')} {price.get('currency', '')}",
            f"成色：{item.get('condition', 'New')}",
            f"刊登时间：{item.get('itemOriginDate', 'eBay 未提供')}",
            f"链接：{item.get('itemWebUrl', '')}",
            f"商品 ID：{item.get('itemId', '')}",
            "-" * 50,
        ])
    msg.set_content("\n".join(lines))
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, app_password)
        server.send_message(msg)

def main():
    token = get_token()
    state = load_state()
    seen = set(state.get("seen_ids", []))
    current = {}

    for brand, query in BRANDS:
        items = search_brand(token, query)
        print(f"Brand={brand}; query={query}; results={len(items)}")
        for item in items:
            item_id = item.get("itemId")
            if not item_id:
                continue
            # conditionIds:{1000} is the primary eBay-side New filter.
            condition = (item.get("condition") or "").strip().lower()
            if condition and condition != "new":
                continue
            item["_brand"] = brand
            current[item_id] = item
        time.sleep(0.25)

    current_ids = set(current)
    if not state.get("initialized", False):
        STATE_PATH.write_text(json.dumps({
            "initialized": True,
            "seen_ids": sorted(current_ids),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Baseline created for {len(current_ids)} listings. No email sent on first run.")
        return

    new_items = [item for item_id, item in current.items() if item_id not in seen]
    if new_items:
        send_email(new_items)

    # Persist state only after email succeeds, so failed email attempts can be retried.
    STATE_PATH.write_text(json.dumps({
        "initialized": True,
        "seen_ids": sorted(seen | current_ids),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scanned {len(current_ids)} listings; emailed {len(new_items)} new listings.")

if __name__ == "__main__":
    main()
