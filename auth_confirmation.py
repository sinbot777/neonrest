"""Session-scoped confirmation, bound to the trusted client address."""
import hashlib
import hmac
import ipaddress
import math

WINDOW_SECONDS = 24 * 60 * 60


def binding(environ, secret):
    # Set by ClientAddress. Never read caller-supplied forwarding headers here.
    value = environ.get('neonrest.client_ip')
    if not isinstance(value, str) or len(value) > 64 or '%' in value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    key = secret.encode() if isinstance(secret, str) else secret
    if not isinstance(key, bytes) or not key:
        return None
    return hmac.new(key, b'neonrest-confirmation-ip-v1\0' + str(address).encode(), hashlib.sha256).hexdigest()


def network_matches(state, environ, secret):
    current = binding(environ, secret)
    previous = state.get('confirmation_ip')
    return bool(current and isinstance(previous, str) and hmac.compare_digest(current, previous))


def recent(value, now):
    return (type(value) in (int, float) and math.isfinite(value)
            and type(now) in (int, float) and math.isfinite(now)
            and 0 <= now - value < WINDOW_SECONDS)


def is_fresh(state, environ, secret, now, factor_required):
    return (network_matches(state, environ, secret)
            and recent(state.get('fresh_at'), now)
            and (not factor_required or recent(state.get('factor_at'), now)))


def confirm(state, environ, secret, now, factor=False):
    current = binding(environ, secret)
    if current is None or type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError('Verified client address required to confirm sign-in')
    state.update(fresh_at=int(now), confirmation_ip=current)
    if factor:
        state['factor_at'] = int(now)
