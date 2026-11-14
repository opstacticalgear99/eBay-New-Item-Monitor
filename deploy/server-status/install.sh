#!/bin/bash
# Run from the extracted deploy/server-status directory as root.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run as root in the server console.'; exit 1; }
cd -- "$(dirname -- "$0")"
app=$(readlink -f /opt/fieldwatch/current)
test -f "$app/monitor.py"
test -f "$app/server.js"
test -f /etc/fieldwatch/run-monitor.sh
test -x /opt/fieldwatch/venv/bin/python
test -x /opt/fieldwatch/node/bin/node
# Validate all source and patch compatibility before touching services.
/opt/fieldwatch/venv/bin/python - "$app" <<'PY'
import ast, pathlib, sys
app=pathlib.Path(sys.argv[1])
ast.parse(pathlib.Path('run_with_status.py').read_text())
s=(app/'server.js').read_text()
assert "app.get(\"/api/health\"" in s, 'Receiver layout changed; review required'
assert 'get_access_token' in (app/'monitor.py').read_text()
for name in ['index.html','settings.html']:
 assert '</main>' in (app/'public'/name).read_text()
PY
/opt/fieldwatch/node/bin/node --check monitor-status.js
/opt/fieldwatch/node/bin/node --check public/monitor-status.js
systemd-analyze calendar '*-*-* *:02/15:00 UTC' >/dev/null
backup=/opt/fieldwatch/status-backups/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup/public"
chmod 700 "$backup"
cp -p "$app/server.js" "$backup/"
cp -p "$app/public/index.html" "$app/public/settings.html" "$backup/public/"
cp -p /etc/fieldwatch/run-monitor.sh "$backup/run-monitor.sh"
cp -p /etc/systemd/system/fieldwatch-monitor.timer "$backup/fieldwatch-monitor.timer"
printf '%s\n' "$app" > "$backup/app-path.txt"
systemctl stop fieldwatch-monitor.timer
# Let an active scan finish, keeping its outbox and deduplication writes intact.
for attempt in $(seq 1 660); do
 state=$(systemctl show fieldwatch-monitor.service -p ActiveState --value)
 case "$state" in inactive|failed) break;; esac
 sleep 1
done
case "$state" in inactive|failed) :;; *) systemctl start fieldwatch-monitor.timer; echo 'Monitor still active; no code changed.'; exit 1;; esac
rollback(){
 trap - ERR
 cp -p "$backup/server.js" "$app/server.js"
 cp -p "$backup/public/index.html" "$backup/public/settings.html" "$app/public/"
 cp -p "$backup/run-monitor.sh" /etc/fieldwatch/run-monitor.sh
 cp -p "$backup/fieldwatch-monitor.timer" /etc/systemd/system/fieldwatch-monitor.timer
 systemctl daemon-reload
 systemctl restart fieldwatch.service
 systemctl start fieldwatch-monitor.timer
 echo "Update failed; previous code and schedule restored. Backup: $backup"
 exit 1
}
trap rollback ERR
install -m 644 run_with_status.py monitor-status.js "$app/"
install -m 644 public/monitor-status.js "$app/public/monitor-status.js"
/opt/fieldwatch/venv/bin/python - "$app" <<'PY'
import pathlib,sys
app=pathlib.Path(sys.argv[1]);p=app/'server.js';s=p.read_text()
mount="require('./monitor-status')(app,{dir:DIR,token:TOKEN});\n"
if mount not in s:
 s=s.replace('app.get("/api/health"',mount+'app.get("/api/health"',1)
p.write_text(s)
panel='''<section class="panel settings-section" aria-label="监控运行状态"><details><summary style="cursor:pointer;color:#d7bf8c">扫描状态与 eBay 额度</summary><div id="monitorDetails" role="status" aria-live="polite"></div></details></section>
<script src="/monitor-status.js?v=15min-1" defer></script>
'''
for name in ['index.html','settings.html']:
 p=app/'public'/name;s=p.read_text()
 if 'id="monitorDetails"' not in s:s=s.replace('</main>',panel+'</main>',1)
 p.write_text(s)
PY
cat > /etc/fieldwatch/run-monitor.sh <<'SH'
#!/bin/sh
exec /opt/fieldwatch/venv/bin/python /opt/fieldwatch/current/run_with_status.py
SH
chmod 755 /etc/fieldwatch/run-monitor.sh
install -m 644 fieldwatch-monitor.timer /etc/systemd/system/fieldwatch-monitor.timer
/opt/fieldwatch/node/bin/node --check "$app/server.js"
systemctl daemon-reload
systemctl restart fieldwatch.service
for attempt in $(seq 1 20); do
 if curl -fsS --max-time 2 http://127.0.0.1:3100/api/health >/dev/null; then break; fi
 sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:3100/api/health
curl -fsS --max-time 5 http://127.0.0.1:3100/api/monitor/status
systemctl enable --now fieldwatch-monitor.timer
# Publish immediately. Existing deduplication and HTTPS Gmail transport stay in place.
systemctl start --no-block fieldwatch-monitor.service
trap - ERR
systemctl list-timers fieldwatch-monitor.timer --no-pager
echo "Update installed. Source/config backup: $backup"
