"""Single-workspace access gate for a same-origin HTTPS deployment."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse

COOKIE = 'holdon_session'
LIFETIME = 12 * 60 * 60


def required():
    # Explicit public mode uses its own signed visitor-session gate.
    public = os.getenv('HOLDON_PUBLIC_DEMO', '').lower() in {'1', 'true', 'yes'}
    return not public and os.getenv('HOLDON_REQUIRE_AUTH', '').lower() in {'1', 'true', 'yes'}


def origin():
    return (os.getenv('PUBLIC_APP_URL') or os.getenv('RENDER_EXTERNAL_URL', '')).rstrip('/')


def validate():
    if required():
        parsed = urlparse(origin())
        if (len(os.getenv('HOLDON_ACCESS_KEY', '')) < 32 or parsed.scheme != 'https' or not parsed.netloc
                or parsed.path not in {'', '/'} or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Private workspace mode requires a 32+ character HOLDON_ACCESS_KEY and HTTPS PUBLIC_APP_URL '
                             '(or RENDER_EXTERNAL_URL). For the public simulation, set HOLDON_PUBLIC_DEMO=1 '
                             'and a 32+ character HOLDON_ACCESS_KEY in your hosting environment.')


def signature(payload):
    return hmac.new(os.getenv('HOLDON_ACCESS_KEY', '').encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue():
    payload = f'{int(time.time())}.{secrets.token_hex(16)}'
    return f'{payload}.{signature(payload)}'


def valid(token):
    try:
        timestamp, nonce, signed = token.split('.')
        age = time.time() - int(timestamp)
        return (bool(os.getenv('HOLDON_ACCESS_KEY')) and 0 <= age < LIFETIME and len(nonce) == 32
                and hmac.compare_digest(signature(f'{timestamp}.{nonce}'), signed))
    except (ValueError, AttributeError, TypeError):
        return False


class AccessGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and required() and scope['path'].startswith('/api/'):
            request = Request(scope)
            path = scope['path']
            if path.startswith('/api/webhooks/') or path in {'/api/health', '/api/demo/session'}:
                return await self.app(scope, receive, send)
            supplied_origin = request.headers.get('origin')
            expected = origin()
            if supplied_origin and supplied_origin.rstrip('/') != expected:
                return await JSONResponse({'detail': 'Unexpected request origin'}, status_code=403)(scope, receive, send)
            if path != '/api/login' and not valid(request.cookies.get(COOKIE, '')):
                return await JSONResponse({'detail': 'Sign in to this workspace'}, status_code=401)(scope, receive, send)
        await self.app(scope, receive, send)
