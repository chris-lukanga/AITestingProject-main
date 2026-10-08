import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from services.security import redact


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents(kind TEXT, id TEXT, body TEXT, updated TEXT, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, body TEXT);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id,seq);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def put(self, kind, id, body):
        with self.lock, self.connect() as db:
            db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?)', (kind, id, json.dumps(redact(body)), now()))

    def get(self, kind, id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM documents WHERE kind=? AND id=?', (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM documents WHERE kind=? ORDER BY updated DESC', (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def event(self, run_id, body):
        with self.lock, self.connect() as db:
            cursor = db.execute('INSERT INTO events(run_id,body) VALUES(?,?)', (run_id, json.dumps(redact(body))))
            return cursor.lastrowid

    def events(self, run_id, after=0):
        with self.connect() as db:
            rows = db.execute('SELECT seq,body FROM events WHERE run_id=? AND seq>? ORDER BY seq', (run_id, after)).fetchall()
        return [dict(json.loads(body), seq=seq) for seq, body in rows]

    def recover(self):
        for run in self.list('run'):
            if run['status'] in ('running', 'paused', 'pausing', 'cancelling'):
                run.update(status='interrupted', stage='recovery', error='Server restarted. Completed evidence is retained; resume skips completed cases.')
                self.put('run', run['id'], run)

    def prune(self, days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        count = 0
        for run in self.list('run'):
            if run['created_at'] < cutoff and run['status'] in ('completed', 'cancelled', 'failed'):
                with self.lock, self.connect() as db:
                    db.execute('DELETE FROM documents WHERE kind=? AND id=?', ('run', run['id']))
                    db.execute('DELETE FROM events WHERE run_id=?', (run['id'],))
                count += 1
        return count
