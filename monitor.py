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
    from html import escape
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

    # 纯文本版本：兼容不支持 HTML 的邮件客户端
    text_lines = [f"本次发现 {len(items)} 件新品：", ""]

    # HTML 版本：商品标题可以直接点击
    html_rows = []

    for i, item in enumerate(items, 1):
        title = str(item.get("title", "未知商品"))
        url = str(item.get("url", "") or item.get("itemWebUrl", ""))
        price = str(item.get("price", "价格未知"))
        brand = str(item.get("brand", "未知品牌"))

        text_lines.extend([
            f"{i}. [{brand}] {title}",
            f"价格：{price}",
            f"链接：{url if url else '暂无商品链接'}",
            "",
        ])

        safe_title = escape(title)
        safe_brand = escape(brand)
        safe_price = escape(price)

        # 仅允许 http/https 链接，避免生成不安全的超链接
        safe_url = ""
        if url.startswith(("https://", "http://")):
            safe_url = escape(url, quote=True)

        if safe_url:
            title_html = (
                f'<a href="{safe_url}">{safe_title}</a>'
            )
            link_html = (
                f'<a href="{safe_url}">点击打开 eBay 商品页面</a>'
            )
        else:
            title_html = safe_title
            link_html = "暂无商品链接"

        html_rows.append(f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #ddd;">
            {i}
          </td>
          <td style="padding:10px;border-bottom:1px solid #ddd;">
            <strong>{safe_brand}</strong><br>
            {title_html}<br>
            <span style="color:#555;">价格：{safe_price}</span><br>
            {link_html}
          </td>
        </tr>
        """)

    msg.set_content("\n".join(text_lines))

    html_body = f"""
    <!doctype html>
    <html>
    <body style="font-family:Arial,sans-serif;line-height:1.5;">
      <h2>eBay 新品监控</h2>
      <p>本次发现 <strong>{len(items)}</strong> 件新品。</p>
      <table style="border-collapse:collapse;width:100%;">
        <thead>
          <tr>
            <th style="text-align:left;padding:10px;">序号</th>
            <th style="text-align:left;padding:10px;">商品信息</th>
          </tr>
        </thead>
        <tbody>
          {''.join(html_rows)}
        </tbody>
      </table>
    </body>
    </html>
    """

    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP_SSL(
            "smtp.gmail.com", 465, timeout=30
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
