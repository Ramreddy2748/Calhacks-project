"""Persistent task snapshots plus a replayable event log for the dashboard."""
import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        if not self.metadata('stream_id'):
            self.set_metadata('stream_id', str(uuid4()))

    def metadata(self, key, default=None):
        row = self.db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_metadata(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, str(value)))

    def outbox(self, after, limit=100):
        return [(r['seq'], r['task_id'], r['data']) for r in self.db.execute(
            'SELECT seq, task_id, data FROM events WHERE seq>? ORDER BY seq LIMIT ?', (after, limit))]

    def latest_sequence(self):
        return self.db.execute('SELECT COALESCE(MAX(seq), 0) FROM events').fetchone()[0]

    def save(self, task):
        task['updated_at'] = now()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO tasks VALUES (?, ?)',
                            (task['id'], json.dumps(task)))
            event = {'type': 'snapshot', 'task': task}
            self.db.execute('INSERT INTO events(task_id, data) VALUES (?, ?)',
                            (task['id'], json.dumps(event)))
        return task

    def get(self, task_id):
        row = self.db.execute('SELECT data FROM tasks WHERE id=?', (task_id,)).fetchone()
        return json.loads(row['data']) if row else None

    def all(self):
        return sorted([json.loads(r['data']) for r in self.db.execute('SELECT data FROM tasks')],
                      key=lambda t: t['created_at'], reverse=True)

    def events(self, task_id, after):
        return [(r['seq'], r['data']) for r in self.db.execute(
            'SELECT seq, data FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 100',
            (task_id, after))]
