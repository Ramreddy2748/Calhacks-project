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
    return os.getenv('HOLDON_REQUIRE_AUTH', '').lower() in {'1', 'true', 'yes'}


def validate():
    if required():
        origin = urlparse(os.getenv('PUBLIC_APP_URL', ''))
        if (len(os.getenv('HOLDON_ACCESS_KEY', '')) < 32 or origin.scheme != 'https' or not origin.netloc
                or origin.path not in {'', '/'} or origin.username or origin.password or origin.query or origin.fragment):
            raise ValueError('Hosted mode requires a 32+ character HOLDON_ACCESS_KEY and HTTPS PUBLIC_APP_URL')


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
            origin = request.headers.get('origin')
            expected = os.getenv('PUBLIC_APP_URL', '').rstrip('/')
            if origin and origin.rstrip('/') != expected:
                return await JSONResponse({'detail': 'Unexpected request origin'}, status_code=403)(scope, receive, send)
            if path != '/api/login' and not valid(request.cookies.get(COOKIE, '')):
                return await JSONResponse({'detail': 'Sign in to this workspace'}, status_code=401)(scope, receive, send)
        await self.app(scope, receive, send)
