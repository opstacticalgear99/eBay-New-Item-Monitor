# Server Schedule controls

The settings page adds a Schedule panel immediately below password unlock. The button requires the existing administrator credential, pauses or resumes the actual Server timer, and reads back the resulting state. Refresh is read-only. Wrong passwords, stale state, overlapping requests, an unavailable controller and malformed requests never display a successful change.

Pause disables and stops only `fieldwatch-monitor.timer`, keeping an already-running `fieldwatch-monitor.service` alive. Resume enables/starts the timer on its existing 15-minute schedule (minutes 02/17/32/47). The choice persists across reboot. Because the timer is persistent, resume can catch up one missed run. Keywords, sellers, deduplication, pending notifications and Gmail transport are preserved. Existing queued Web Push retries remain independent of the scan schedule.

`schedule-controller.py` runs as root in `fieldwatch-schedule.service`. It listens only on a group-restricted Unix socket. It accepts only fixed read/enable/disable actions for the one FieldWatch timer, never arbitrary commands or unit names. The Node receiver retains its existing user and `NoNewPrivileges`; it does not receive general sudo rights. Schedule writes use the same admin-password/legacy-token policy as settings writes. The controller does not receive any application secrets.

`install.sh` targets the existing DigitalOcean release, validates compatibility, backs up changed receiver files under `/opt/fieldwatch/schedule-backups`, installs the controller and patches the settings/status panels. The original timer state is preserved by installation. It restores receiver files if installation fails. It does not change monitor state, environment credentials, SSH or VPN configuration.

Validation: 5 controller tests, 5 API tests, 16 existing receiver regressions, and isolated browser checks for password locking, pause/resume, preserved keyword drafts, unknown state and mobile width. Local Gemma supplied one bounded Chinese label draft (4.98s, 75 output tokens); its JSON was parsed and validated and the final wording was reviewed to distinguish a schedule being enabled from a scan currently running.

Install as root with `bash install.sh` in this directory on the Server. Verify `/api/monitor/schedule`, `systemctl status fieldwatch-schedule.service`, and both ActiveState/UnitFileState of `fieldwatch-monitor.timer`. A successful source merge does not install the Server update by itself.
