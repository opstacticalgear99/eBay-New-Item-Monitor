"""Root-owned Unix socket service: control only the FieldWatch timer."""
import grp
import json
import os
import socketserver
import subprocess
from http.server import BaseHTTPRequestHandler

TIMER = 'fieldwatch-monitor.timer'
SCANNER = 'fieldwatch-monitor.service'
SOCKET = '/run/fieldwatch-schedule/control.sock'

def systemctl(*args):
    result = subprocess.run(['/usr/bin/systemctl', *args], capture_output=True,
        text=True, timeout=8, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if result.returncode:
        raise RuntimeError('Schedule service operation failed')
    return result.stdout.strip()

def state():
    values = {}
    for line in systemctl('show', TIMER, '--property=ActiveState,UnitFileState,NextElapseUSecRealtime').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
    enabled = values.get('UnitFileState')
    if enabled not in ('enabled', 'disabled'):
        raise RuntimeError('Unexpected timer configuration')
    return {'enabled': enabled == 'enabled', 'active': values.get('ActiveState') == 'active',
        'scanRunning': systemctl('show', SCANNER, '--property=ActiveState', '--value') in ('active', 'activating'),
        'nextRun': values.get('NextElapseUSecRealtime') or None, 'intervalMinutes': 15}

def change(body):
    if not isinstance(body, dict) or set(body) != {'enabled', 'expectedEnabled'} or any(type(body[k]) is not bool for k in body):
        return 400, {'error': 'Invalid schedule request'}
    before = state()
    if before['enabled'] != body['expectedEnabled']:
        return 409, {'error': 'Schedule changed; reload before retrying'}
    systemctl('enable' if body['enabled'] else 'disable', '--now', TIMER)
    after = state()
    if after['enabled'] != body['enabled'] or after['active'] != body['enabled']:
        return 503, {'error': 'Schedule did not reach the requested state; reload to verify'}
    return 200, after

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def reply(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path != '/schedule':
            return self.reply(404, {'error': 'Unknown operation'})
        try:
            self.reply(200, state())
        except Exception:
            self.reply(503, {'error': 'Cannot read schedule state'})
    def do_POST(self):
        if self.path != '/schedule':
            return self.reply(404, {'error': 'Unknown operation'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 256:
                return self.reply(400, {'error': 'Invalid request size'})
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                return self.reply(400, {'error': 'Invalid JSON'})
            self.reply(*change(body))
        except Exception:
            self.reply(503, {'error': 'Schedule operation failed; reload to verify'})

def main():
    if os.path.exists(SOCKET):
        os.unlink(SOCKET)
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam('fieldwatch').gr_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever()

if __name__ == '__main__':
    main()
