"""Read-only Forward Observations product/variant availability adapter."""
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote
import requests
import ronin_monitor as shared

ORIGIN='https://forwardobservations.com'
STATE_FILE=Path('forward_state.json')


def parse_products(products):
    if not isinstance(products,list):
        raise ValueError('Unexpected Forward product catalogue')
    catalog,snapshots={},{}
    for product in products:
        if not isinstance(product,dict) or not isinstance(product.get('id'),int) or not product.get('title') or not isinstance(product.get('handle'),str):
            raise ValueError('Forward product identifier/title missing')
        pid=str(product['id']);handle=product['handle']
        if not handle or '/' in handle or len(handle)>300 or pid in catalog:
            raise ValueError('Invalid/duplicate Forward product handle')
        url=ORIGIN+'/products/'+quote(handle,safe='-')
        variants={}
        if not isinstance(product.get('variants'),list) or not product['variants']:
            raise ValueError('Forward variant data missing')
        for variant in product['variants']:
            if not isinstance(variant,dict) or not isinstance(variant.get('id'),int):
                raise ValueError('Forward variant identifier missing')
            vid=str(variant['id'])
            if vid in variants:raise ValueError('Duplicate Forward variant')
            available=variant.get('available')
            available=available if type(available) is bool else None
            try:
                amount=Decimal(str(variant.get('price')))
                price=f'US ${amount:.2f}' if amount.is_finite() and amount>=0 else 'Price not shown'
            except (InvalidOperation,ValueError):price='Price not shown'
            variants[vid]={'available':available,'options':str(variant.get('title') or '默认规格'),'price':price}
        catalog[pid]=url
        snapshots[pid]={'title':str(product['title']),'url':url,'variants':variants}
    return catalog,snapshots


def fetch_snapshot(session):
    catalog,snapshots={},{}
    for page in range(1,6):
        response=session.get(ORIGIN+'/products.json',params={'limit':250,'page':page},timeout=20,allow_redirects=False)
        if response.status_code!=200 or len(response.content)>5_000_000:
            raise ValueError('Forward catalogue unavailable')
        raw=response.json().get('products')
        current,items=parse_products(raw)
        if set(catalog)&set(current):raise ValueError('Repeated Forward page; refusing incomplete catalogue')
        catalog.update(current);snapshots.update(items)
        if len(raw)<250:return catalog,snapshots,[]
    raise ValueError('Forward catalogue exceeds scan limit')


def main(settings):
    state=shared.load_state(STATE_FILE)
    if not shared.prepare_site(state,settings):
        shared.save_state(state,STATE_FILE);return
    errors=[]
    try:
        with requests.Session() as session:
            session.headers['User-Agent']='FieldWatch/1.0 (personal product availability monitor)'
            catalog,snapshots,errors=fetch_snapshot(session)
        state=shared.apply_snapshot(state,catalog,snapshots,source_id='fog',source_name=settings['name'],new_products=settings['new_products'],restocks=settings['restocks'])
        shared.save_state(state,STATE_FILE)
        logging.info('Forward scan: catalog=%s parsed=%s pending=%s',len(catalog),len(snapshots),len(state['pending']))
    except Exception:
        logging.warning('Forward catalogue unavailable; previous baseline and stock states retained.')
    shared.deliver(state,errors,state_file=STATE_FILE,source_name=settings['name'])
    logging.info('Forward monitor completed; pending delivery=%s',len(state['pending']))
