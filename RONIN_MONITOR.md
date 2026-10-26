# Ronin Tactics: new products and restocks

The existing scheduled workflow now runs `ronin_monitor.py` after the eBay step. It uses the existing Gmail and app-sync secrets; no new credentials are required. It runs even if eBay's step fails, and the final state-save step runs on failures too. The GitHub Actions cron remains every five minutes, but actual schedule delivery can be delayed. A catalogue scan is capped at six minutes and the shared workflow remains serialized. If the scan is interrupted by the time budget, the next run resumes after the last attempted product so later products are not starved.

## Detection

- The public `/sitemap.xml` enumerates `/store/p<ID>/...html` product pages.
- Public product HTML includes `wsite-com-product-view-variation-data`, with a stable SKU identifier, options, prices and inventory counts.
- The first successful catalogue read seeds every listed product ID, including detail pages that temporarily failed. It sends no historical-inventory alerts.
- A new product ID after that baseline generates **新品**, even if currently unavailable.
- A known variant inventory count going from zero to positive generates **补货**. Size/color options are included. Sustained positive inventory sends no repeated alert. Another zero-to-positive cycle can generate another alert with a different event ID.
- New variants on an existing product establish their own baseline first. They are not claimed to be a restock without an observed zero state.
- Null, missing, negative or unrecognized inventory is unknown. Preserve the prior known state and never infer stock from generic hidden “Unavailable” text. Untracked inventory cannot produce reliable restock alerts until the site exposes a numeric state.
- Missing/removed products or variants are retained; disappearance is not treated as sold out. Product failures preserve previous state. Empty/invalid catalogues cannot reset baselines.

This reads only public sitemap/product pages, with a pause between requests. It does not call `/ajax/`, add items to a cart, log in, bypass challenges, or perform transactions.

## Delivery and persistence

`ronin_state.json` is separate from eBay's `seen_items.json`. Do not delete or manually reset it. A durable outbox is written before Gmail delivery. Successful email delivery is marked before optional app synchronization, so failed app requests retry without sending the email again. Receiver event IDs deduplicate repeated synchronization; restock cycles have distinct IDs. As with SMTP in general, a process crash between remote email acceptance and recording local success can still cause a duplicate email on retry.

The receiver permits Ronin product URLs in addition to its existing eBay URL behavior. The Web list labels events with Ronin Tactics and 新品/补货, links to Ronin, and retains existing eBay items and subscriptions. Only new events are synchronized, so the initial Ronin catalogue does not flood the Web feed.

The final workflow step commits both state files and retries non-fast-forward pushes after rebasing; it never force-pushes or replaces main's state. Credentials are supplied by existing Actions secrets and never stored in the state files.

## Verification

`python -m unittest discover -s tests -v`

`npm ci && node --test tests/*.test.js`

Tests cover initial and incomplete baselines, new products, individual variant stock changes, repeated restock cycles, unknown/removed states, corrupt-state refusal, durable delivery retries, Ronin URL validation, receiver restart/deduplication and existing eBay/Gmail regressions. All notification tests use synthetic data and credentials. Live read-only catalogue checks can be run independently without calling any email or push function.
