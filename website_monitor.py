"""Load saved website settings and run only explicitly supported adapters."""
import json
import logging
import os
from pathlib import Path
import requests
import ronin_monitor
import forward_monitor

CACHE_FILE=Path('website_settings_cache.json')
DEFAULTS=Path(__file__).with_name('website-defaults.json')
ADAPTER_URLS={'ronin':'https://www.ronintactics.com/','fog':'https://forwardobservations.com/'}


def validate(data):
    if not isinstance(data,dict) or not isinstance(data.get('sites'),list) or len(data['sites'])>12:
        raise ValueError('Invalid website settings')
    seen=set()
    for site in data['sites']:
        if not isinstance(site,dict) or not isinstance(site.get('id'),str) or site['id'] in seen:
            raise ValueError('Invalid/duplicate website identifier')
        seen.add(site['id'])
        if not isinstance(site.get('name'),str) or not site['name'].strip() or len(site['name'])>80:
            raise ValueError('Invalid website name')
        if any(type(site.get(key)) is not bool for key in ('enabled','new_products','restocks')):
            raise ValueError('Invalid website switches')
        if site['id'] in ADAPTER_URLS and site.get('url')!=ADAPTER_URLS[site['id']]:
            raise ValueError('Unsupported URL for known website adapter')
    return {'sites':data['sites']}


def load_settings():
    cached=validate(json.loads((CACHE_FILE if CACHE_FILE.exists() else DEFAULTS).read_text()))
    url=os.getenv('APP_API_URL','').strip().rstrip('/');token=os.getenv('APP_API_TOKEN','').strip()
    if not url or not token:return cached
    try:
        response=requests.get(url+'/api/monitor/websites',headers={'Authorization':'Bearer '+token},timeout=30)
        response.raise_for_status();settings=validate(response.json())
        tmp=CACHE_FILE.with_suffix('.tmp');tmp.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n');tmp.replace(CACHE_FILE)
        return settings
    except Exception:
        logging.warning('Cannot load website settings; using the last saved list (or defaults).')
        return cached


def main():
    settings=load_settings();configured={site['id']:site for site in settings['sites']}
    failed=[]
    for sid,adapter in [('fog',forward_monitor.main),('ronin',ronin_monitor.main)]:
        site=configured.get(sid,{'name':sid,'enabled':False,'new_products':False,'restocks':False})
        try:adapter(site)
        except Exception:
            logging.error('Website %s delivery/state update failed; other sources will continue.',sid);failed.append(sid)
    pending=[site['name'] for site in settings['sites'] if site['id'] not in ADAPTER_URLS]
    if pending:logging.info('Websites awaiting adapter (not crawled): %s',', '.join(pending))
    if failed:raise RuntimeError('Website monitor failed for: '+', '.join(failed))


if __name__=='__main__':main()
