import ipaddress
import os
import re
from urllib.parse import urlsplit

SECRET_KEYS = re.compile(r'api.?key|password|credential|authorization|cookie|access.?token|secret', re.I)
SECRET_ENV_KEYS = re.compile(r'api.?key|password|credential|secret|(?:^|_)(?:key|token|auth)(?:_|$)', re.I)


def redact(value):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if SECRET_KEYS.search(k) and not isinstance(v, bool) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for name, secret in os.environ.items():
            if SECRET_ENV_KEYS.search(name) and len(secret) >= 6:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'Bearer\s+[^\s"<>]+', 'Bearer [REDACTED]', value, flags=re.I)
    return value


def enforce_scope(target):
    scope = target.testing_scope
    if scope.get('authorized') is not True:
        raise ValueError('Explicit authorization is required before execution.')
    endpoint = target.adapter.endpoint
    if not endpoint or endpoint not in scope.get('allowed_endpoints', []):
        raise ValueError('The exact endpoint must be listed in testing_scope.allowed_endpoints.')
    u = urlsplit(endpoint)
    host = u.hostname
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == 'localhost'
    if not local:
        allowed = [x.strip() for x in os.getenv('LAB_ALLOWED_ENDPOINTS', '').split(',') if x.strip()]
        if endpoint not in allowed:
            raise ValueError('Remote endpoint is not enabled in LAB_ALLOWED_ENDPOINTS.')
        if u.scheme != 'https':
            raise ValueError('Remote endpoints must use HTTPS.')
    if target.adapter.kind == 'campushelp' and not local:
        raise ValueError('The deliberately vulnerable CampusHelp adapter is restricted to loopback.')
    return endpoint
