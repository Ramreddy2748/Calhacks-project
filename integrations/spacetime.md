# SpacetimeDB event mirror

The backend keeps its durable SQLite event log and asynchronously mirrors every
task snapshot to SpacetimeDB. Calls, approvals, and SSE continue during a remote
outage. A per-destination checkpoint survives restarts. Idempotent reducer keys
prevent duplicate inserts after an ambiguous network failure, and increasing
sequence numbers prevent an older event from overwriting a newer snapshot.

This is an **event mirror**, not a replacement for SQLite or a native browser
subscription. The dashboard still reads the authenticated API and its SSE stream.
Keep the SQLite volume: the mirror cannot currently restore private task state.

The module has three private tables (`owner`, `task_snapshot`, `task_event`).
Only the publishing identity may call `sync_task`. No transcript or reasoning
table is public. Internal browser session hashes and event bookkeeping are
removed from mirrored snapshots. Actual goal/context/transcript data is mirrored,
so choose a database and account you control.

## Build and publish

Use SpacetimeDB **2.13.0**, matching the pinned SDK, and Node 22.14+:

```sh
cd spacetimedb
npm ci
npm run check
spacetime build --module-path .
spacetime publish holdon --server YOUR_SERVER --module-path .
```

Publish a new database owned by the same identity whose token the backend will
use. Do not use delete-data or overwrite another database. For a local server,
`spacetime start` uses port 3000 by default. For cloud hosting, log into your own
SpacetimeDB account and use its documented server URL and available usage.

The CLI and Node can also build the artifact in Docker without global installs:

```sh
docker build --output type=local,dest=/tmp/holdon-module \
  -f spacetimedb/Dockerfile spacetimedb
```

Set these in `backend/.env`, then restart the backend:

```dotenv
SPACETIMEDB_URL=https://your-database-server
SPACETIMEDB_DATABASE=holdon
SPACETIMEDB_TOKEN=token-for-the-publishing-identity
```

HTTP is permitted only for localhost, `127.0.0.1`, or the Docker service name
`spacetime`. Tokens remain server-side. The connection panel reports configuration,
successful sync, queued events, or errors; it never treats configuration alone
as a verified connection. Existing event history is replayed on first connection.

`SELECT * FROM task_snapshot` and `SELECT * FROM task_event` let the owner inspect
the mirror with the SpacetimeDB SQL tools. HTTP reducers are sufficient for this
MVP; the SDK WebSocket transport is the next option for higher throughput.

References: [HTTP reducer API](https://spacetimedb.com/docs/http/database/),
[module tables and reducers](https://spacetimedb.com/docs/tutorials/chat-app/).
