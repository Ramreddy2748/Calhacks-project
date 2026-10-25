"""Isolated anonymous sessions and bounded usage for the public simulation."""
import hashlib
import os
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse

from . import access

COOKIE = 'holdon_visitor'
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


def enabled():
    return os.getenv('HOLDON_PUBLIC_DEMO', '').lower() in {'1', 'true', 'yes'}


def origin():
    return (os.getenv('PUBLIC_APP_URL') or os.getenv('RENDER_EXTERNAL_URL', '')).rstrip('/')


def validate():
    if not enabled():
        return
    parsed = urlparse(origin())
    if (access.required() or len(os.getenv('HOLDON_ACCESS_KEY', '')) < 32
            or parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('Public demo requires a 32+ character signing key, HTTPS origin, and workspace auth disabled')


def visitor(token):
    return hashlib.sha256(token.encode()).hexdigest() if access.valid(token) else None


def creation_error(store, visitor_id):
    """Called synchronously before saving: one worker cannot oversubscribe limits."""
    from .store import now
    today = now()[:10]
    tasks = [task for task in store.all() if task.get('visitor_id')]
    daily = [task for task in tasks if task['created_at'].startswith(today)]
    if len(daily) >= int(os.getenv('PUBLIC_DEMO_DAILY_LIMIT', '20')):
        return 'Today’s public demo limit has been reached. Please try again tomorrow.'
    own = [task for task in tasks if task['visitor_id'] == visitor_id]
    if sum(task['created_at'].startswith(today) for task in own) >= 3:
        return 'You have used your three demo sessions for today.'
    active = [task for task in tasks if task['status'] not in TERMINAL]
    if any(task['visitor_id'] == visitor_id for task in active):
        return 'Finish or end your current simulation before starting another.'
    if len(active) >= 4:
        return 'The demo is busy. Please try again shortly.'
    return None


class PublicDemoGate:
    def __init__(self, app, store):
        self.app = app
        self.store = store

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not enabled() or not scope['path'].startswith('/api/'):
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = scope['path']

        async def reject(message, status=403):
            await JSONResponse({'detail': message}, status_code=status)(scope, receive, send)

        supplied_origin = request.headers.get('origin')
        if supplied_origin and supplied_origin.rstrip('/') != origin():
            return await reject('Unexpected request origin')
        if path == '/api/health':
            return await self.app(scope, receive, send)
        if path == '/api/demo/session' and request.method == 'GET':
            token = request.cookies.get(COOKIE, '')
            fresh = not visitor(token)
            if fresh:
                token = access.issue()
            response = JSONResponse({'public_demo': True})
            response.headers['Cache-Control'] = 'no-store'
            if fresh:
                response.set_cookie(COOKIE, token, max_age=access.LIFETIME, secure=True,
                                    httponly=True, samesite='strict', path='/')
            return await response(scope, receive, send)
        identity = visitor(request.cookies.get(COOKIE, ''))
        if not identity:
            return await reject('Refresh the page to start your demo session')
        scope.setdefault('state', {})['visitor_id'] = identity
        if path != '/api/tasks' and not path.startswith('/api/tasks/'):
            return await reject('This endpoint is unavailable in the public demo', 404)
        parts = path.strip('/').split('/')
        if len(parts) >= 3:
            task = self.store().get(parts[2])
            if not task or task.get('visitor_id') != identity:
                return await reject('Task not found', 404)
            if len(parts) >= 4 and parts[3] in {'sms', 'browser'}:
                return await reject('Voice calls and SMS are unavailable in the public demo')

        async def private_response(message):
            if message['type'] == 'http.response.start':
                message.setdefault('headers', []).append((b'cache-control', b'no-store'))
            await send(message)

        await self.app(scope, receive, private_response)
