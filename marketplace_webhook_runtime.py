"""Explicit Sandbox-only webhook mount with private, separate storage.

No environment discovery, app import, startup migration, provider write, or paid
transition. Configuration and database provisioning are operator actions.
"""
import json
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

if __package__:
    from .check_marketplace_sandbox import private_config
    from . import marketplace_checkout as checkout, marketplace_payments as payments
    from .marketplace_provider_api import StripeTestAPI, PayPalSandboxAPI
    from .marketplace_webhooks import SandboxWebhookApplication, initialize_paypal_inbox
else:
    from check_marketplace_sandbox import private_config
    import marketplace_checkout as checkout, marketplace_payments as payments
    from marketplace_provider_api import StripeTestAPI, PayPalSandboxAPI
    from marketplace_webhooks import SandboxWebhookApplication, initialize_paypal_inbox

PREFIX = '/sandbox/marketplace/provider-events'


class RuntimeConfigurationError(ValueError):
    pass


def _json_file(path):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 16384:
            raise ValueError
        with os.fdopen(fd, 'rb') as handle:
            fd = None
            raw = handle.read(16385)
        if len(raw) > 16384:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=payments._json_pairs,
                           parse_constant=payments._invalid_constant)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, OSError, UnicodeError):
        raise RuntimeConfigurationError('private test configuration unavailable') from None
    finally:
        if fd is not None:
            os.close(fd)


def _settings(path):
    path = Path(path)
    cfg = _json_file(path)
    parent = path.parent.resolve()
    info = parent.stat()
    if cfg.get('environment') != 'test' or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise RuntimeConfigurationError('private test directory required')
    for key in ('database_path', 'stripe_api_config', 'stripe_hook_config', 'paypal_api_config'):
        value = cfg.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute() or Path(value).parent.resolve() != parent:
            raise RuntimeConfigurationError('configuration must use dedicated private paths')
    payments.ref(cfg.get('stripe_platform'))
    payments.ref(cfg.get('paypal_platform'))
    return cfg


def _database(path):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError
    except (ValueError, OSError):
        raise RuntimeConfigurationError('dedicated private database required') from None
    finally:
        if fd is not None:
            os.close(fd)
    db = sqlite3.connect('file:' + quote(str(path), safe='/') + '?mode=rw', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    # Marker prevents a configuration typo from attaching an existing app DB.
    try:
        marker = db.execute('SELECT purpose FROM marketplace_webhook_runtime_marker').fetchone()
        if not marker or marker[0] != 'isolated_test_webhooks_v1':
            raise ValueError
    except (sqlite3.Error, ValueError):
        db.close()
        raise RuntimeConfigurationError('dedicated test database marker required') from None
    return db


def initialize_database(settings_path):
    """Provision a new empty 0600 database; refuse every existing destination."""
    cfg = _settings(settings_path)
    fd = os.open(cfg['database_path'], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    db = sqlite3.connect(cfg['database_path'])
    try:
        checkout.initialize(db)
        payments.initialize(db)
        initialize_paypal_inbox(db)
        db.execute('CREATE TABLE marketplace_webhook_runtime_marker (purpose TEXT NOT NULL)')
        db.execute('INSERT INTO marketplace_webhook_runtime_marker VALUES (?)', ('isolated_test_webhooks_v1',))
        db.commit()
    finally:
        db.close()


def application(settings_path):
    cfg = _settings(settings_path)
    # Validate the database without migrating or silently creating one.
    _database(cfg['database_path']).close()
    stripe_cfg = private_config(cfg['stripe_api_config'], 'stripe')
    paypal_cfg = private_config(cfg['paypal_api_config'], 'paypal')
    hook_cfg = _json_file(cfg['stripe_hook_config'])
    if hook_cfg.get('environment') != 'test' or hook_cfg.get('platform_ref') != cfg['stripe_platform']:
        raise RuntimeConfigurationError('test webhook/platform binding required')
    secret = hook_cfg.get('webhook_secret')
    if not isinstance(secret, str) or not secret.startswith('whsec_') or not 16 <= len(secret) <= 512:
        raise RuntimeConfigurationError('separate Marketplace signing secret required')
    api = StripeTestAPI(cfg['stripe_platform'], stripe_cfg['secret_key'])
    stripe = payments.StripeTestWebhookAdapter(cfg['stripe_platform'], [secret.encode()], api.fetch_payment)
    paypal = PayPalSandboxAPI(paypal_cfg['client_id'], paypal_cfg['client_secret'],
                             paypal_cfg.get('webhook_id') or None) if paypal_cfg.get('webhook_id') else None
    return SandboxWebhookApplication('test', lambda: _database(cfg['database_path']),
                                     stripe, paypal, cfg['paypal_platform'])


def mount(existing_application, settings_path):
    """Keep all original routes; longest-prefix dispatch adds only this mount.

    Private configuration failures isolate the new mount with retryable 503s.
    They never make the original Production or Sandbox app unavailable.
    """
    try:
        receiver = application(settings_path)
    except Exception:
        def receiver(environ, start_response):
            return SandboxWebhookApplication._reply(start_response,
                '503 Service Unavailable', 'provider_unavailable')
    def dispatch(environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == PREFIX or path.startswith(PREFIX + '/'):
            child = dict(environ)
            child['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + PREFIX
            child['PATH_INFO'] = path[len(PREFIX):]
            return receiver(child, start_response)
        return existing_application(environ, start_response)
    return dispatch
