# Independent settings password, refresh cadence and Mac Dark

## Set your own administration password

In **Render → fieldwatch-ebay-monitor → Environment**, add `ADMIN_PASSWORD` and
enter your own strong, unique password. Save/redeploy through Render. Enter that
password on `/settings.html` to read or edit settings. Never put the actual value
in source, GitHub comments or chat. `render.yaml` declares the variable name only;
this change does not create or select your password for you.

The password remains only in the current page's memory for Bearer requests; the
input clears after unlock. The browser may offer its normal password-manager
features. This app does not write the password into localStorage or sessionStorage.

- `ADMIN_PASSWORD` authorizes reading and changing eBay and website settings.
- `APP_API_TOKEN` still authorizes `/api/monitor/sync`, and retains read access to
  both settings endpoints so the existing Python workflows continue to work.
- When `ADMIN_PASSWORD` is set, `APP_API_TOKEN` cannot write settings (POST/PUT).
- Until the new variable is set, the existing `APP_API_TOKEN` remains the settings
  credential for backward compatibility. The new password does not replace it in
  GitHub Secrets and must not be added to the Python monitoring environment.
- A password alone can administer settings, but machine sync still separately
  requires `APP_API_TOKEN`.

No credential value is returned from configuration APIs. Existing settings files,
revision protection, keyword/seller lists and all inventory/seen IDs are retained.

## Two different refresh clocks

The server-side GitHub schedule is now `2-59/5 * * * *` (UTC): minute 02, 07, 12,
17, …, 57 of each hour. It keeps the supported five-minute requested interval,
avoids the exact hour boundary, and uses setup-python's pip cache to reduce setup
work. This is an attempt to reduce contention/startup cost, not a guarantee that
GitHub will launch a scan every five minutes. We have still observed roughly
30-minute actual start gaps before this change. No one-minute or three-minute
schedule, persistent worker, paid service or polling loop is added.

Separately, the **web product list** fetches the receiver every 60 seconds while
the page is visible, and when returning to the page. This makes already-received
items visible without pressing Refresh, but does not trigger a new eBay scan or
send duplicate notifications. Manual/automatic refreshes share an in-flight guard
and time out after 15 seconds. A temporary error keeps the existing feed and
retries later. Your local filter text remains unchanged.

Official schedule limitations:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Interface

The listing and settings pages share the Mac Dark palette, system/SF font stack,
neutral dark panels, blue actions, green status, subtle dividers and rounded
controls. The overall scale is 80%. Mobile layouts and visible
keyboard focus are supported. Updated stylesheet/script URLs avoid stale assets;
the PWA theme/background colors match the new background.

## Verification

Python regression tests continue to cover monitoring, outboxes, stock and baseline
preservation. Node checks cover independent password writes, read-only machine
access, legacy fallback, website settings, sync credential separation and page
refresh behavior (visibility, in-flight overlap and recovery without clearing the
feed). The live deployment is usable with the prior credential until the owner
sets `ADMIN_PASSWORD` in Render.

The compact homepage places the settings link alongside the main FieldWatch title, removes the duplicate brand bar and introductory banner, and reduces row/toolbar spacing so more products fit in the initial viewport.
