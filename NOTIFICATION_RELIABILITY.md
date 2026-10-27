# Notification reliability

## What was observed on 2026-10-27

The workflow specifies `*/5 * * * *`, but actual scheduled run start times were
23:07, 23:32, 23:59 and 00:29 UTC. Earlier gaps reached about 43 minutes.
GitHub schedules are best effort and can be delayed or dropped:
https://docs.github.com/en/actions/how-tos/troubleshoot-workflows

The reported item 287682627119 (S&S Precision NavBoard FlipLite) is marked New
and sold on eBay. It was not in the monitor's stored IDs. We cannot establish
retroactively whether the live Browse search returned it, or whether it was
indexed and sold between scans. This is not proof of a condition-filter miss.
The monitor uses the US marketplace and only active listings returned by the
Browse API; it cannot recover an already-sold listing through current search.

## Fixes

- Per the user's follow-up, keyword searches include **every condition**. No
  condition filter is sent to eBay and no result is rejected for its condition.
  The first complete scan seeds newly included non-new listings silently so old
  stock is not suddenly announced. Later arrivals of any condition notify.
  Existing keyword/seller settings are unchanged. Pagination now covers up to
  the Browse API limit of 10,000 results per query (formerly 1,000), with a
  warning if a query exceeds that limit.
- eBay uses `ebay_outbox.json`, saved before baseline advancement and delivery.
  Gmail and App acknowledgments are separate. Failed App sync is retried on the
  next run without repeating successful Gmail. Failed Gmail does not block App.
- Successfully observed listings are retained even if another query fails.
- Receiver Push delivery has its own persistent `DATA_DIR/push-outbox.json`.
  Transient service failures retry every 60 seconds and after server restart;
  only failed recipients retry. Invalid subscriptions (404/410) are removed.
- Distinct notification batches have distinct tags, preventing a later batch
  from replacing an earlier one. Batch counts include all items, not just 20.
- FOG's quick scan runs before Ronin's full catalogue scan.

A successful Push HTTP request means acceptance by the Push service, not proof
that iOS displayed it. Device network, notification permission and Focus settings
can still affect presentation. SMTP delivery is at-least-once: a process crash
between acceptance and the local acknowledgment can still produce a duplicate.

## Scheduling improvement still needed

The user chose to retain GitHub scheduling for now; the cloud-worker migration
below is optional and has not been activated.

Reliable frequent checks need a continuously running process, not another cron
expression in GitHub Actions. Render background workers run continuously:
https://render.com/docs/background-workers

Recommended cutover, after the service cost and configuration are approved:

1. Provision a Python background worker with a persistent disk (one instance).
2. Configure existing eBay, Gmail and App credentials in the provider's secret
   environment UI. Never copy credentials to a Git file, log or chat.
3. Pause the GitHub monitor and wait for its last run/state commit to finish.
4. Bootstrap the disk with the latest main baseline files and eBay outbox,
   preserving IDs, settings, website inventory and pending delivery flags.
5. Run eBay on a 2-minute clock and websites on a separate 5-minute clock,
   without overlapping a source's own runs. Retain disk state across deploys.
6. Verify repeated scans and delivery, then keep GitHub manual runs disabled
   unless the worker is stopped. Two independent writers can duplicate Gmail.

This PR does not create or charge for a new cloud service, copy credentials, or
claim GitHub's actual interval is fixed. With 20 queries, a 2-minute eBay interval
uses at least 14,400 search calls/day before pagination; verify the developer
account's actual quota before activating it. A 5-minute interval uses at least
5,760 calls/day. Tune the interval and query set to the approved quota.
