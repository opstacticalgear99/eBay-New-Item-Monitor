#!/bin/bash
set -euo pipefail
test "$(id -u)" = 0
cd -- "$(dirname -- "$0")"
app=$(readlink -f /opt/fieldwatch/current)
test -f "$app/server.js"
test -f "$app/public/settings.js"
test -f "$app/public/monitor-status.js"
/opt/fieldwatch/node/bin/node --check schedule-api.js
/opt/fieldwatch/node/bin/node --check schedule-client.js
python3 - "$app" <<'PY'
import ast,pathlib,sys
ast.parse(pathlib.Path('schedule-controller.py').read_text())
p=pathlib.Path(sys.argv[1])
assert 'app.get("/api/health"' in (p/'server.js').read_text()
assert '<form id="settingsForm">' in (p/'public/settings.html').read_text()
assert '<script src="/settings.js' in (p/'public/settings.html').read_text()
assert 'const stale=' in (p/'public/monitor-status.js').read_text()
PY
backup=/opt/fieldwatch/schedule-backups/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup/public"
chmod 700 "$backup"
cp -p "$app/server.js" "$backup/"
cp -p "$app/public/settings.html" "$app/public/monitor-status.js" "$app/public/index.html" "$backup/public/"
systemctl show fieldwatch-monitor.timer -p ActiveState -p UnitFileState > "$backup/timer-state.txt"
rollback(){
 trap - ERR
 cp -p "$backup/server.js" "$app/server.js"
 cp -p "$backup/public/"* "$app/public/"
 systemctl disable --now fieldwatch-schedule.service || true
 systemctl restart fieldwatch.service
 echo "Installation failed; receiver restored. Backup: $backup"
 exit 1
}
trap rollback ERR
install -o root -g root -m 644 schedule-controller.py /etc/fieldwatch/schedule-controller.py
install -o root -g root -m 644 fieldwatch-schedule.service /etc/systemd/system/fieldwatch-schedule.service
install -o root -g root -m 644 schedule-api.js "$app/schedule-api.js"
install -o root -g root -m 644 schedule-client.js "$app/public/schedule-client.js"
python3 - "$app" <<'PY'
import pathlib,sys
app=pathlib.Path(sys.argv[1]);p=app/'server.js';s=p.read_text()
mount="require('./schedule-api')(app,{adminPassword:process.env.ADMIN_PASSWORD||'',token:TOKEN});\n"
if mount not in s:s=s.replace('app.get("/api/health"',mount+'app.get("/api/health"',1)
p.write_text(s)
panel='''<section id="schedulePanel" class="panel settings-section" aria-labelledby="scheduleHeading">
<h2 id="scheduleHeading">Schedule 定时监控</h2>
<p id="scheduleState" class="settings-message" role="status" aria-live="polite">正在读取定时任务状态…</p>
<p class="muted">先读取设置解锁启停按钮。暂停仅停止后续定时检查，正在进行的扫描会完成；暂停状态在 Server 重启后保留。</p>
<div class="settings-actions"><button id="scheduleToggle" type="button" class="primary" disabled>读取状态中…</button><button id="scheduleRefresh" type="button" class="quiet">刷新状态</button></div>
<p id="scheduleHelp" class="muted"></p>
</section>
'''
p=app/'public/settings.html';s=p.read_text()
if 'id="schedulePanel"' not in s:
 needle='<form id="settingsForm">'
 assert needle in s, 'Settings layout changed; review required'
 s=s.replace(needle,panel+needle,1)
if '/schedule-client.js?' not in s:s=s.replace('</body>','<script src="/schedule-client.js?v=schedule-1" defer></script>\n</body>',1)
p.write_text(s)
p=app/'public/monitor-status.js';s=p.read_text()
if 'const paused=' not in s:
 s=s.replace('const stale=', "const schedule=await fetch('/api/monitor/schedule',{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null);\n      const paused=schedule&&schedule.enabled===false&&!schedule.active;\n      const stale=",1)
 s=s.replace("heading.textContent=stale?", "heading.textContent=paused?'Schedule 已暂停 · 以下为上次扫描结果':stale?",1)
 s=s.replace("heading.style.color=stale||", "heading.style.color=!paused&&(stale||",1).replace(".includes(s.state)?'#f1787c'", ".includes(s.state))?'#f1787c'",1)
p.write_text(s)
for name in ['index.html','settings.html']:
 p=app/'public'/name;s=p.read_text().replace('/monitor-status.js?v=15min-1','/monitor-status.js?v=schedule-1');p.write_text(s)
PY
/opt/fieldwatch/node/bin/node --check "$app/server.js"
/opt/fieldwatch/node/bin/node --check "$app/public/monitor-status.js"
systemctl daemon-reload
systemctl enable --now fieldwatch-schedule.service
systemctl restart fieldwatch.service
for attempt in $(seq 1 20); do
 if curl -fsS --max-time 2 http://127.0.0.1:3100/api/monitor/schedule; then break; fi
 sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:3100/api/monitor/schedule
trap - ERR
echo "Schedule controls installed. Existing timer state preserved. Backup: $backup"
