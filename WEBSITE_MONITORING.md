# Editable website monitoring

Open `/settings.html`, enter the existing `APP_API_TOKEN`, and choose **读取设置**. The new **网站监控** section is independent of the eBay keyword/seller form. It supports adding/removing sites, editing display names and HTTPS home URLs, enabling/disabling sites, and separate new-product/restock switches. Choose **保存网站设置** to persist changes for the next check.

Supported now:
- Ronin Tactics: public sitemap plus per-variant inventory in product HTML. Existing `ronin_state.json` and event IDs are preserved.
- Forward Observations Group: public paginated `/products.json`, stable product/variant IDs, and exact boolean `available` values. State is stored independently in `forward_state.json`.

Both sources are enabled by default. Missing website settings migrate to these defaults; existing eBay settings are not rewritten. Other HTTPS home URLs can be saved for future integration but display **待适配，尚未运行** and are never fetched by the runner. Merely adding an arbitrary URL does not enable monitoring for an unsupported shop. Currently supported URLs accept www/non-www aliases and normalize to the adapter's fixed origin. Credentials, non-HTTPS URLs, IP addresses, paths and query parameters are rejected. Duplicate sites are rejected.

Settings are stored atomically as `DATA_DIR/website-settings.json` with the existing administration key and revision conflict protection. The API is `/api/monitor/websites` (GET/POST). No token is stored in this file, browser storage or source code. A malformed saved file refuses overwrites.

The existing scheduled workflow now runs `website_monitor.py`, which retrieves website settings and caches the last accepted list in `website_settings_cache.json`. During a receiver outage it uses this cache, or the two defaults before its first successful read. The save step commits both site states and the cache, independently of eBay's `seen_items.json`. One site's failure does not stop the other site from running. Actual GitHub schedule execution may be delayed.

New sources establish a first baseline without historical alerts. Unknown/missing stock does not create restock events. Notification switches advance inventory/known IDs without sending the disabled type. Disabling/removing a source retains its inventory/history, stops pending deliveries for that source, and records that it is paused. Re-enabling establishes a fresh current baseline rather than replaying changes during the pause. A currently running check may finish with the settings snapshot it already loaded; changes are read on the next run.

Checks: `python -m unittest discover -s tests -v` and `node --test tests/*.test.js`. These cover settings validation/auth/persistence/conflicts, eBay data isolation, source dispatch and cache fallback, unsupported sources not being fetched, new/restock filtering, pause/resume, FOG variants, and the existing Ronin/Gmail/receiver regressions. Live read-only FOG validation returned one product, six colors (three purchasable, three unavailable), with zero first-baseline alerts. UI testing used isolated local data and a synthetic key.
