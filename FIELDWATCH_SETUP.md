# FieldWatch iPhone companion — test branch

This is an iPhone-friendly Progressive Web App (PWA), not a native App Store app. The existing Gmail alert path is intended to remain unchanged. The monitor sync is best-effort.

## Deploy receiver

1. Deploy this branch as a Node web service with HTTPS and a persistent disk. The included Render blueprint mounts persistent storage at /var/data. Do not use ephemeral storage if subscriptions and listing history must survive restarts.
2. Set APP_API_TOKEN to a long random secret. The Render blueprint can generate it. Copy its exact value to the GitHub Actions repository secret APP_API_TOKEN.
3. After npm install, generate VAPID keys locally with: node -e "const w=require('web-push'); console.log(JSON.stringify(w.generateVAPIDKeys(),null,2))". Add the output values as service environment variables VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY. Set VAPID_SUBJECT to a real contact email. Never commit the private key or API token.
4. After deployment, open https://YOUR-HOST/api/health. Expect ok:true and pushConfigured:true.
5. Set GitHub Actions repository secrets APP_API_URL to the deployed base URL without a trailing slash, and APP_API_TOKEN to the same token configured on the service. The existing workflow passes these secrets to monitor.py.

## Enable on iPhone

1. Open the HTTPS URL in Safari on iOS/iPadOS 16.4 or later.
2. Share → Add to Home Screen. Launch FieldWatch from the new Home Screen icon.
3. Tap Enable Push Notifications and allow notifications. The page should confirm that the device is registered.

## End-to-end test before merge

1. Confirm /api/health returns ok:true and pushConfigured:true.
2. From a trusted terminal, send a synthetic item using the same APP_API_TOKEN configured on the service. This does not call eBay or send Gmail:

   curl -i -X POST "https://YOUR-HOST/api/monitor/sync" \\
     -H "Authorization: Bearer $APP_API_TOKEN" \\
     -H "Content-Type: application/json" \\
     -d '{"items":[{"itemId":"fieldwatch-test-001","title":"FieldWatch push test — remove after verification","price":"US $1.00 (TEST)","url":"https://www.ebay.com/itm/123456789012","condition":"Test item","source":"Manual integration test","labels":["TEST"]}]}'

   Expect HTTP 200 and JSON with added:1. After subscribing an iPhone, pushSent should be at least 1. Refresh the page to see the test item and confirm the iPhone notification arrives. A second test needs a different itemId because IDs are de-duplicated.
3. Verify an incorrect token returns HTTP 401.
4. Only after the synthetic test succeeds, run the GitHub Actions workflow manually. Verify its logs show a successful app sync and separately verify the original Gmail alert. Do not reset seen_items.json on main.
5. The synthetic listing is retained in the feed; it is clearly labelled TEST. There is no admin delete endpoint yet. Avoid deleting the data file while running because that also clears push subscriptions.

## Behavior and limitations

- The endpoint accepts HTTPS eBay item URLs, processes at most 100 items per request, and de-duplicates by item ID.
- Notifications are best-effort. Expired subscriptions are removed automatically; OS settings, Focus modes, browser push services, and network issues can prevent delivery.
- Keyword/seller filtering currently affects only the displayed list. It does not modify the existing eBay search configuration.
- Do not merge to main until deployment, iPhone subscription, synthetic push, GitHub Actions sync, and Gmail regression checks all pass.
