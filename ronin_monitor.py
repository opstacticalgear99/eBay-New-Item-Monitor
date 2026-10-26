"""Read-only Ronin catalogue/variant monitor, with a durable delivery outbox."""
import copy
import json
import logging
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from monitor import send_email, sync_app_notifications

ORIGIN = 'https://www.ronintactics.com'
STATE_FILE = Path(os.getenv('RONIN_STATE_FILE', 'ronin_state.json'))
TIMEOUT = 20
MAX_PRODUCTS = 250
MAX_SCAN_SECONDS = 360


def product_id(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'www.ronintactics.com':
        return None
    match = re.match(r'^/store/p(\d+)/[^/]+\.html$', parsed.path)
    return match.group(1) if match else None


def parse_catalog(xml):
    root = ET.fromstring(xml)
    if root.tag.rsplit('}', 1)[-1] != 'urlset':
        raise ValueError('Unexpected Ronin sitemap format')
    products = {}
    for el in root.iter():
        if el.tag.rsplit('}', 1)[-1] == 'loc' and el.text:
            url = el.text.strip()
            pid = product_id(url)
            if pid:
                products[pid] = url
    if not products or len(products) > MAX_PRODUCTS:
        raise ValueError('Ronin catalogue is empty or exceeds the scan safety limit')
    return products


def parse_product(page, url):
    pid = product_id(url)
    soup = BeautifulSoup(page, 'html.parser')
    title = soup.select_one('#wsite-com-product-title')
    data = soup.select_one('#wsite-com-product-view-variation-data')
    if not pid or not title or not title.get_text(strip=True) or not data:
        raise ValueError('Ronin product/variant data missing; keep previous stock state')
    skus = json.loads(data.get('value', ''))
    if not isinstance(skus, list) or not skus:
        raise ValueError('Ronin variants are missing or invalid')
    variants = {}
    for sku in skus:
        if not isinstance(sku, dict) or not sku.get('site_product_sku_id'):
            raise ValueError('Ronin variant identifier missing')
        # Null/missing inventory is unknown, never assume it is in or out of stock.
        quantity = sku.get('inventory')
        known = isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and math.isfinite(quantity)
        available = quantity > 0 if known and quantity >= 0 else None
        options = sku.get('options') or {}
        if not isinstance(options, dict):
            raise ValueError('Invalid Ronin variant options')
        option_text = ' / '.join(f'{key}: {value["choices"]}' for key, value in sorted(options.items()) if isinstance(value, dict) and value.get('choices'))
        price = sku.get('sale_price') if sku.get('sale_price') is not None else sku.get('price')
        price_text = f'US ${price:.2f}' if isinstance(price, (int, float)) and math.isfinite(price) else 'Price not shown'
        vid = str(sku['site_product_sku_id'])
        if vid in variants:
            raise ValueError('Duplicate Ronin variant identifier')
        variants[vid] = {'available': available, 'options': option_text or '默认规格', 'price': price_text}
    return {'title': title.get_text(' ', strip=True), 'url': url, 'variants': variants}


def load_state(path=None):
    path = STATE_FILE if path is None else Path(path)
    if not path.exists():
        return {'version': 1, 'initialized': False, 'known_ids': [], 'products': {}, 'sequence': 0, 'pending': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('version') != 1
            or type(data.get('initialized')) is not bool
            or not isinstance(data.get('known_ids'), list)
            or not isinstance(data.get('products'), dict)
            or not isinstance(data.get('pending'), list)
            or type(data.get('sequence')) is not int):
        raise ValueError('Invalid Ronin state: refusing to reset the baseline')
    return data


def save_state(state, path=None):
    path = STATE_FILE if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.replace(path)


def apply_snapshot(previous, catalog, snapshots, *, source_id="ronin", source_name="Ronin Tactics", new_products=True, restocks=True):
    state = copy.deepcopy(previous)
    first = not state['initialized']
    known = set(state['known_ids'])
    if first:
        # Include initially listed products even when one detail page fails to load.
        known.update(catalog)
    for pid, item in snapshots.items():
        if pid not in catalog:
            continue
        old = state['products'].get(pid)
        restocked = []
        for vid, variant in item['variants'].items():
            old_variant = (old or {}).get('variants', {}).get(vid)
            if old_variant and variant['available'] is None:
                variant = copy.deepcopy(variant)
                variant['available'] = old_variant['available']
                item = copy.deepcopy(item)
                item['variants'][vid] = variant
            elif old_variant and old_variant['available'] is False and variant['available'] is True:
                restocked.append(variant)
        kind = '新品' if not first and pid not in known else '补货' if not first and restocked else None
        if (kind == '新品' and not new_products) or (kind == '补货' and not restocks):
            kind = None
        if kind:
            state['sequence'] += 1
            changed = restocked if kind == '补货' else list(item['variants'].values())
            descriptions = [v['options'] for v in changed]
            event_id = f'{source_id}:{pid}:new' if kind == '新品' else f'{source_id}:{pid}:restock:{state["sequence"]}'
            event = {
                'itemId': event_id,
                'title': f'【{kind}】{item["title"]}',
                'itemWebUrl': item['url'],
                'price': changed[0]['price'],
                'condition': '规格：'+'；'.join(descriptions),
                '_monitor_source': source_id,
                '_monitor_label': source_name,
                '_monitor_labels': [source_name, kind],
            }
            state['pending'].append({'item': event, 'email_sent': False, 'app_sent': False})
        # Preserve unseen/temporarily removed variants and products. Missing != sold out.
        combined = copy.deepcopy((old or {}).get('variants', {}))
        combined.update(item['variants'])
        state['products'][pid] = {**item, 'variants': combined}
        known.add(pid)
    state['known_ids'] = sorted(known)
    state['initialized'] = True
    return state


def fetch_snapshot(session, cursor=None):
    def get(url):
        response = session.get(url, timeout=TIMEOUT, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f'HTTP {response.status_code}')
        if len(response.content) > 5_000_000:
            raise ValueError('Unexpectedly large Ronin response')
        return response.text
    # Only public sitemap and product pages; never /ajax/, carts, or checkout.
    catalog = parse_catalog(get(ORIGIN+'/sitemap.xml'))
    snapshots, errors = {}, []
    start = time.monotonic()
    entries = list(catalog.items())
    ids = [pid for pid, _ in entries]
    if cursor in ids:
        offset = ids.index(cursor)+1
        entries = entries[offset:]+entries[:offset]
    for pid, url in entries:
        if time.monotonic()-start > MAX_SCAN_SECONDS:
            errors.append('Ronin scan time budget reached; remaining product states preserved')
            break
        session.ronin_cursor = pid
        try:
            snapshots[pid] = parse_product(get(url), url)
        except Exception:
            errors.append(f'Ronin product {pid}: unavailable or unrecognized; previous state preserved')
        time.sleep(.35)
    return catalog, snapshots, errors


def deliver(state, errors, *, state_file=None, source_name="Ronin Tactics"):
    unsent = [entry for entry in state['pending'] if not entry['email_sent']]
    if unsent:
        send_email([entry['item'] for entry in unsent], errors, subject_prefix=source_name+' · 新品/补货')
        for entry in unsent:
            entry['email_sent'] = True
        save_state(state, state_file)
    app_pending = [entry for entry in state['pending'] if entry['email_sent'] and not entry['app_sent']]
    if app_pending and sync_app_notifications([entry['item'] for entry in app_pending]) is True:
        for entry in app_pending:
            entry['app_sent'] = True
    state['pending'] = [entry for entry in state['pending'] if not (entry['email_sent'] and entry['app_sent'])]
    save_state(state, state_file)


def prepare_site(state, settings):
    if not settings['enabled']:
        state['paused'] = True
        state['pending'] = []
        return False
    if state.pop('paused', False):
        # Re-enabling starts a fresh snapshot, not a backlog of changes while paused.
        state['initialized'] = False
    state['pending'] = [entry for entry in state['pending']
                        if (settings['new_products'] if '新品' in entry['item'].get('_monitor_labels', []) else settings['restocks'])]
    return True


def main(settings=None):
    state = load_state()
    settings = settings or {"name":"Ronin Tactics","enabled":True,"new_products":True,"restocks":True}
    if not prepare_site(state, settings):
        save_state(state)
        return
    errors = []
    try:
        with requests.Session() as session:
            session.headers.update({'User-Agent': 'FieldWatch/1.0 (personal product availability monitor)'})
            catalog, snapshots, errors = fetch_snapshot(session, state.get("cursor"))
            cursor = getattr(session, "ronin_cursor", None)
        state = apply_snapshot(state, catalog, snapshots, source_name=settings["name"], new_products=settings["new_products"], restocks=settings["restocks"])
        state["cursor"] = cursor
        # Persist the outbox before delivery so a failed SMTP run can retry safely.
        save_state(state)
        logging.info('Ronin scan: catalog=%s parsed=%s warnings=%s pending=%s', len(catalog), len(snapshots), len(errors), len(state['pending']))
    except Exception:
        logging.warning('Ronin catalogue unavailable; retaining the existing baseline and inventory states.')
    if settings["name"] == "Ronin Tactics":
        deliver(state, errors)
    else:
        deliver(state, errors, source_name=settings["name"])
    if errors:
        logging.warning('Ronin incomplete snapshot: %s', '; '.join(errors))
    logging.info('Ronin monitor completed; pending delivery=%s', len(state['pending']))


if __name__ == '__main__':
    main()
