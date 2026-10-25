"""Durable SQLite event outbox -> owner-only SpacetimeDB reducer.

Network delivery happens outside call handlers. Reducer event IDs make replay
safe if the remote commit succeeds but the local checkpoint is not persisted.
"""
import asyncio
import hashlib
import json
import os
from urllib.parse import quote, urlparse

import httpx

from .store import now


class SpacetimeMirror:
    def __init__(self, store, client=None):
        self.store = store
        self.url = os.getenv('SPACETIMEDB_URL', '').rstrip('/')
        self.database = os.getenv('SPACETIMEDB_DATABASE', '')
        self.token = os.getenv('SPACETIMEDB_TOKEN', '')
        self.configured = bool(self.url and self.database and self.token)
        parsed = urlparse(self.url)
        if self.configured and (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', 'spacetime'})):
            raise ValueError('SpacetimeDB requires HTTPS or a local HTTP server')
        destination = hashlib.sha256(f'{self.url}/{self.database}'.encode()).hexdigest()[:24]
        self.checkpoint_key = f'spacetime_cursor:{destination}'
        self.cursor = int(store.metadata(self.checkpoint_key, '0'))
        self.client = client
        self.last_synced_at = None
        self.error = None
        self.job = None

    def info(self):
        return {'configured': self.configured, 'connected': bool(self.last_synced_at) and not self.error,
                'pending_events': max(0, self.store.latest_sequence() - self.cursor) if self.configured else 0,
                'last_synced_at': self.last_synced_at, 'error': self.error,
                'mode': 'SQLite event mirror; dashboard uses SSE'}

    async def drain(self):
        if not self.configured:
            return 0
        sent = 0
        for seq, task_id, data in self.store.outbox(self.cursor):
            snapshot = json.loads(data)
            # Internal transport bookkeeping is not useful in a shared mirror.
            snapshot['task'].pop('browser_session_hash', None)
            snapshot['task'].pop('browser_events', None)
            snapshot['task'].pop('visitor_id', None)
            payload = [self.store.metadata('stream_id'), seq, task_id, json.dumps(snapshot)]
            response = await self.client.post(
                f'{self.url}/v1/database/{quote(self.database, safe="")}/call/sync_task',
                headers={'Authorization': f'Bearer {self.token}'}, json=payload)
            response.raise_for_status()
            self.store.set_metadata(self.checkpoint_key, seq)
            self.cursor = seq
            self.last_synced_at = now()
            self.error = None
            sent += 1
        return sent

    async def run(self):
        delay = 1
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            self.client = client
            while True:
                try:
                    count = await self.drain()
                    delay = 1
                    await asyncio.sleep(0 if count == 100 else 1)
                except (httpx.HTTPError, ValueError):
                    self.error = 'SpacetimeDB sync failed. Events remain queued locally; check the database, module, and owner token.'
                    await asyncio.sleep(delay)
                    delay = min(30, delay * 2)

    def start(self):
        if self.configured:
            self.job = asyncio.create_task(self.run())

    async def close(self):
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)
