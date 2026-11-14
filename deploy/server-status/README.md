# FieldWatch Server: 15 minute scans and operational status

This update targets the DigitalOcean deployment, not the disabled GitHub scanner.

The timer runs at minutes 02, 17, 32 and 47 of every hour. Website list refreshes remain every minute; refreshing the list does not start a scan. Existing eBay keywords, sellers, condition policy, deduplication, persisted outboxes, HTTPS email transport and web push subscriptions are preserved.

Both the feed and settings get a collapsible “扫描状态与 eBay 额度” panel. It shows the last start/completion, last completely successful scan, source warnings, pending eBay notifications and the official Browse search allocation/reset time. Quota failure is explicitly unknown; a retained previous reading is labeled stale. Reports older than 25 minutes are marked overdue. An online receiver is not presented as evidence of a successful scan.

`run_with_status.py` calls the existing monitor entry points. It counts actual Browse requests, stops further Browse network requests during a run after HTTP 429, and still runs the website monitors. Original durable state/delivery handling stays in the existing scripts. Exceptions and log text are never copied into the public status payload. The quota query is best effort, once per scan, using the existing in-memory OAuth token; no token is stored in status.

## Install

Run `sudo bash install.sh` from this directory in the server console. The installer checks source compatibility, backs up only affected code/configuration, stops the timer and lets any active scan finish, then adds the telemetry modules and panel to the existing release. It updates the timer, restarts the receiver and starts a scan. Configuration secrets and existing state files are not included in this source directory or overwritten.

If the installation fails after modification, the original receiver, runner and timer are restored. Extra unused status modules may remain. Backups live in `/opt/fieldwatch/status-backups/`. The installer does not alter SSH, firewall, VPN or GitHub workflow state.

## Verification

`systemctl list-timers fieldwatch-monitor.timer --no-pager`

`journalctl -u fieldwatch-monitor.service -n 60 --no-pager`

`curl -fsS http://127.0.0.1:3100/api/monitor/status`

Only a successful live install and Server reports establish that the new schedule is active. Local tests do not prove deployment. A 15 minute interval lowers call volume by two thirds but cannot guarantee staying below quota if the number of keywords or result pages grows. Existing exhausted quota remains exhausted until eBay's official reset time.

Local validation: 55 Python tests and 16 Node tests passed, including telemetry tests for HTTP 429, continued website scans, unknown/stale quota, public credential exclusion, authenticated persistence and existing monitor/outbox regressions. Installation requires console/root access and has not yet been executed on the live server.
