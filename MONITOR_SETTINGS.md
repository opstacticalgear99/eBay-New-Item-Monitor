# Web monitor settings

Open `/settings.html`, or use the **监控设置** link in the listing header.
Enter the existing receiver `APP_API_TOKEN` privately in the password field and select **读取设置**. The value is sent only to the same origin in an Authorization header. It is held in page memory, never included in shipped JavaScript, localStorage, sessionStorage, cookies, or URLs. Reloading requires entering it again. Do not share the key or paste it into a chat.

Edit one brand query per line and one eBay seller username per line, then save. Quotes in queries are preserved. Existing display labels are preserved for unchanged queries. Saving replaces both lists, so remove a line to stop monitoring that entry. Limits are 1–50 brand queries (120 characters each) and 1–20 seller usernames. Empty lists and duplicate entries are rejected; concurrent edits return a conflict instead of overwriting a newer configuration.

The receiver stores the settings atomically in `DATA_DIR/monitor-settings.json`, separate from push subscriptions and listing history. A persistent Render disk is required, as with the existing receiver. Missing settings use the exact original 18 queries and two sellers. Malformed storage returns an error and is not silently replaced.

On the next scheduled run, `monitor.py` retrieves the settings using the existing `APP_API_URL` and `APP_API_TOKEN` secrets. No additional Actions secrets or workflow inputs are required. A currently running check can still finish using its earlier snapshot. Receiver outages use the last accepted configuration cached in the repository state; before the first accepted configuration, the original defaults remain active. No credentials are saved in that state.

Existing query and seller baselines migrate without replaying old inventory. New queries and sellers take one successful snapshot to establish their baseline, without notifying historical listings. Later arrivals trigger the usual Gmail-first, optional app notification path. Failed initial snapshots are retried without establishing a partial baseline. Old item IDs are retained even when removing a query or seller. Settings do not delete received listings or rewrite production state directly.

Validation: `python -m unittest discover -s tests -v` and `node --test tests/settings.test.js`. These tests use synthetic credentials and isolated temporary storage; they send no eBay, Gmail, or push requests.


## Website monitors

The independent 网站监控 section now manages Ronin Tactics and Forward Observations Group, plus entries awaiting future adapters. See WEBSITE_MONITORING.md for supported origins, switches, persistence and pause/resume semantics. Saving website settings never changes the eBay brand/seller form.
