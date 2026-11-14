"""Run the existing monitors and publish safe operational telemetry."""
import importlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

STATUS_FILE = Path('monitor-status.json')
INTERVAL_MINUTES = 15

def now():
    return datetime.now(timezone.utc).isoformat()

def load():
    try:
        return json.loads(STATUS_FILE.read_text())
    except FileNotFoundError:
        return {}

def publish(status):
    temp = STATUS_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(status))
    temp.replace(STATUS_FILE)
    url = os.getenv('APP_API_URL', '').rstrip('/')
    token = os.getenv('APP_API_TOKEN', '')
    if url and token:
        try:
            response = requests.post(url+'/api/monitor/status', json=status,
                headers={'Authorization': 'Bearer '+token}, timeout=15)
            response.raise_for_status()
        except Exception:
            logging.warning('Monitor status delivery failed; local status retained.')

class Observation(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.warnings = 0
        self.errors = 0
    def emit(self, record):
        self.warnings += 1
        self.errors += int(record.levelno >= logging.ERROR)

def quota_from_response(data):
    rates = []
    for api in data.get('rateLimits', []):
        if str(api.get('apiName', '')).lower() != 'browse':
            continue
        for resource in api.get('resources', []):
            # Do not show the unrelated bulk-getItems allocation as search quota.
            if resource.get('name') != 'buy.browse':
                continue
            for rate in resource.get('rates', []):
                if all(type(rate.get(k)) is int and rate[k] >= 0 for k in ('limit', 'remaining', 'timeWindow')):
                    rates.append({k: rate[k] for k in ('limit', 'remaining', 'timeWindow')} |
                                 {'reset': rate.get('reset')})
    return rates

def collect_quota(token, previous):
    try:
        response = requests.get('https://api.ebay.com/developer/analytics/v1_beta/rate_limit/',
            params={'api_context': 'buy', 'api_name': 'browse'},
            headers={'Authorization': 'Bearer '+token}, timeout=15)
        response.raise_for_status()
        rates = quota_from_response(response.json())
        if not rates:
            raise ValueError('Missing Browse quota')
        return {'state': 'available', 'checkedAt': now(), 'rates': rates}
    except Exception:
        return {'state': 'unavailable', 'checkedAt': now(),
                'lastKnown': previous.get('rates', previous.get('lastKnown', [])),
                'lastKnownAt': previous.get('checkedAt') if previous.get('state') == 'available' else previous.get('lastKnownAt')}

def pending_count():
    try:
        entries = json.loads(Path(os.getenv('EBAY_OUTBOX_FILE', 'ebay_outbox.json')).read_text())
        return len(entries)
    except FileNotFoundError:
        return 0
    except Exception:
        return None

def run_source(callback):
    observer = Observation()
    logging.getLogger().addHandler(observer)
    result = {'state': 'ok', 'startedAt': now()}
    try:
        callback()
        if observer.warnings:
            result['state'] = 'partial'
    except Exception:
        result['state'] = 'failed'
        # Source logs remain in the journal. Never send exception bodies or credentials to the UI.
        logging.error('Monitor source failed; inspect its server journal.')
    finally:
        logging.getLogger().removeHandler(observer)
    result.update(finishedAt=now(), warnings=observer.warnings, errors=observer.errors)
    return result

def main():
    monitor = importlib.import_module('monitor')
    websites = importlib.import_module('website_monitor')
    status = load()
    status.update(intervalMinutes=INTERVAL_MINUTES, startedAt=now(), state='running')
    publish(status)
    calls = 0
    blocked = False
    original_send = requests.Session.send
    original_token = monitor.get_access_token
    tokens = []
    def tracked_token():
        token = original_token()
        tokens.append(token)
        return token
    def tracked_send(session, request, **kwargs):
        nonlocal calls, blocked
        parsed = urlparse(request.url)
        browse = parsed.hostname == 'api.ebay.com' and parsed.path.startswith('/buy/browse/')
        if browse and blocked:
            raise requests.HTTPError('eBay rate limit reached; remaining searches deferred')
        if browse:
            calls += 1
        response = original_send(session, request, **kwargs)
        if browse and response.status_code == 429:
            blocked = True
        return response
    monitor.get_access_token = tracked_token
    requests.Session.send = tracked_send
    try:
        ebay = run_source(monitor.main)
    finally:
        requests.Session.send = original_send
        monitor.get_access_token = original_token
    if blocked:
        ebay['state'] = 'rate_limited'
    ebay.update(requests=calls, pendingDeliveries=pending_count())
    status['ebay'] = ebay
    # Analytics is best effort; an unavailable quota must not block scans or notifications.
    status['quota'] = collect_quota(tokens[-1], status.get('quota', {})) if tokens else {
        'state': 'unavailable', 'checkedAt': now()}
    status['websites'] = {'state': 'running', 'startedAt': now()}
    publish(status)
    status['websites'] = run_source(websites.main)
    status['finishedAt'] = now()
    status['state'] = 'ok' if all(status[s]['state'] == 'ok' for s in ('ebay', 'websites')) else 'partial'
    if status['state'] == 'ok':
        status['lastSuccessAt'] = status['finishedAt']
    publish(status)
    return 0 if status['state'] == 'ok' else 1

if __name__ == '__main__':
    raise SystemExit(main())
