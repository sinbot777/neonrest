"""Explicit private-config wiring and bounded recovery for the Sandbox pilot."""
import importlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
if __package__:
    from . import marketplace_purchase_sandbox as host,marketplace_addresses as addresses
    from . import marketplace_seller_shipping as shipping,marketplace_pilot_views as views
    from . import marketplace_quotes as quotes,marketplace_purchase_flow as flow
    from .marketplace_owner_test_binding import OwnerApprovedStripeTestAPI,approval
    from .marketplace_webhook_runtime import _json_file
    from .check_marketplace_sandbox import private_config
else:
    import marketplace_purchase_sandbox as host,marketplace_addresses as addresses
    import marketplace_seller_shipping as shipping,marketplace_pilot_views as views
    import marketplace_quotes as quotes,marketplace_purchase_flow as flow
    from marketplace_owner_test_binding import OwnerApprovedStripeTestAPI,approval
    from marketplace_webhook_runtime import _json_file
    from check_marketplace_sandbox import private_config


class SimulationTax:
    """QA-only arithmetic; never a real tax decision or live fallback."""
    def __init__(self,settings,clock=lambda:int(time.time())):
        if not isinstance(settings,dict) or settings.get('kind')!='simulation_only' or type(settings.get('basis_points')) is not int or not 0<=settings['basis_points']<=2500:raise ValueError('explicit simulation-only tax configuration required')
        self.bps=settings['basis_points'];self.clock=clock
    def quote_tax(self,context,context_hash):
        if context.get('environment')!='test':raise ValueError('tax simulation is test-only')
        base=context['subtotal_cents']+context['shipping']['amount_cents']
        return quotes.Assessment('tax','simulation-only','qa-bps-'+str(self.bps),context_hash,(base*self.bps+5000)//10000,self.clock()+300)


def settings(path):
    path=Path(path);cfg=_json_file(path)
    if cfg.get('environment')!='test' or cfg.get('worker_scheduled') is not True:raise ValueError('scheduled test pilot configuration required')
    root=path.parent.parent.resolve()
    for key in ('database_path','vault_key_path','stripe_config','stripe_approval_path','stripe_hook_config'):
        value=Path(cfg[key])
        if not value.is_absolute() or root not in value.resolve().parents:raise ValueError('private pilot scope required')
        host.shipping_host.private_file(value)
    if not isinstance(cfg.get('allowed_users'),list) or not cfg['allowed_users'] or any(type(x) is not int or x<=0 for x in cfg['allowed_users']):raise ValueError('explicit tester allowlist required')
    if not isinstance(cfg.get('sellers'),dict) or len(cfg['sellers'])!=1 or any(type(v) is not int or v not in cfg['allowed_users'] for v in cfg['sellers'].values()):raise ValueError('one approved test seller required')
    SimulationTax(cfg['tax'])
    return cfg


def database(cfg):
    path=host.shipping_host.private_file(cfg['database_path'])
    db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
    try:
        row=db.execute('SELECT purpose FROM marketplace_purchase_host_marker').fetchone()
        if not row or row[0]!=host.PURPOSE:raise ValueError('isolated purchase store required')
        return db
    except Exception:db.close();raise


def factory(cfg):
    secret=private_config(cfg['stripe_config'],'stripe');approved=approval(cfg['stripe_approval_path'])
    shop,owner=next(iter(cfg['sellers'].items()))
    vault=addresses.FernetVault([host.shipping_host.private_file(cfg['vault_key_path']).read_bytes().strip()])
    def services(db,policy):
        store=addresses.AddressStore(db,vault,policy)
        api=OwnerApprovedStripeTestAPI(approved['platform_ref'],secret['secret_key'],cfg['stripe_approval_path'],shop,owner)
        return views.PilotServices(db,policy,store,addresses.AddressResolver(store),api,None,SimulationTax(cfg['tax']),shipping_settings=shipping.SellerShipping(db,vault,policy))
    return services


def register(app,core,path):
    cfg=settings(path);make=factory(cfg)
    hook=_json_file(cfg['stripe_hook_config']);approved=approval(cfg['stripe_approval_path'])
    if hook.get('environment')!='test' or hook.get('platform_ref')!=approved['platform_ref']:raise ValueError('Marketplace test hook scope mismatch')
    bridge=host.register(app,core,cfg['database_path'],cfg['allowed_users'],cfg['sellers'],make,worker_ready=True)
    @app.context_processor
    def pilot_notice():return dict(pilot_simulation_notice='Restricted Sandbox test: example addresses, provisional packing and simulated tax. No live purchases or postage.')
    receiver=bridge['webhook']([hook['webhook_secret'].encode()])
    def receive(environ,start_response):
        statuses=[]
        def started(status,headers,exc_info=None):statuses.append(status);return start_response(status,headers,exc_info)
        result=receiver(environ,started)
        # Canonical receipt verification has already run. Fast settlement uses
        # only DB-local state; the scheduled worker handles deferred recovery.
        if statuses and statuses[0].startswith('200'):
            with app.app_context():
                db=database(cfg)
                try:
                    ctx=make(db,bridge['policy'])
                    rows=db.execute("SELECT id FROM marketplace_payment_events WHERE outcome='observed_test' AND platform_ref=? ORDER BY id DESC LIMIT 3",(approved['platform_ref'],)).fetchall()
                    for row in rows:
                        try:flow.settle_received_payment(db,row[0],ctx.location(),ctx.now(),ctx.policy)
                        except ValueError:pass
                except Exception:app.logger.warning('Test Marketplace settlement deferred to recovery')
                finally:db.close()
        return result
    bridge['receiver']=receive
    return bridge


def mount(existing,receiver):
    prefix='/sandbox/marketplace/pilot/provider-events'
    def app(environ,start_response):
        path=environ.get('PATH_INFO','')
        if path==prefix or path.startswith(prefix+'/'):
            child=dict(environ);child['SCRIPT_NAME']=environ.get('SCRIPT_NAME','')+prefix;child['PATH_INFO']=path[len(prefix):]
            return receiver(child,start_response)
        return existing(environ,start_response)
    return app


def worker(path):
    cfg=settings(path)
    live=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True);live.row_factory=sqlite3.Row
    db=database(cfg)
    try:
        core=SimpleNamespace(get_db=lambda:live)
        policy=host.LivePurchasePolicy(core,importlib.import_module('neonrest_sandbox.seller_studio'),importlib.import_module('neonrest_sandbox.marketplace_catalog'),cfg['allowed_users'],cfg['sellers'])
        result=host.recovery_tick(factory(cfg)(db,policy),limit=20)
        heartbeat=Path(path).parent/'worker-heartbeat.json';tmp=heartbeat.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(at=int(time.time()),result=result)));tmp.chmod(0o600);tmp.replace(heartbeat)
        return result
    finally:db.close();live.close()


if __name__=='__main__':
    import sys
    print(json.dumps(worker(sys.argv[1])))
