import os
import json
import time
import smtplib
import ssl
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

def send_mail(items):
    import os
    import smtplib
    from email.message import EmailMessage

    if not items:
        print("没有新品需要通知，跳过邮件发送。")
        return

    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    alert_to = os.environ["ALERT_TO"]

    msg = EmailMessage()
    msg["Subject"] = f"eBay 新品监控：发现 {len(items)} 件新品"
    msg["From"] = gmail_address
    msg["To"] = alert_to

    lines = [
        f"本次 eBay 扫描发现 {len(items)} 件新品：",
        "",
    ]

    for i, item in enumerate(items, 1):
        title = item.get("title", "未知商品")
        url = item.get("url", "")
        price = item.get("price", "价格未知")
        brand = item.get("brand", "未知品牌")

        lines.extend([
            f"{i}. [{brand}] {title}",
            f"价格：{price}",
            f"链接：{url}",
            "",
        ])

    msg.set_content("\n".join(lines))

    try:
        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
            timeout=30
        ) as server:
            server.login(gmail_address, gmail_app_password)
            server.send_message(msg)

        print(f"邮件发送成功：{alert_to}")

    except Exception as e:
        print(f"Gmail 邮件发送失败：{type(e).__name__}: {e}")
        raise

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
        send_mail(new_items)

    # Persist state only after email succeeds, so failed email attempts can be retried.
    STATE_PATH.write_text(json.dumps({
        "initialized": True,
        "seen_ids": sorted(seen | current_ids),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scanned {len(current_ids)} listings; emailed {len(new_items)} new listings.")

if __name__ == "__main__":
    main()
