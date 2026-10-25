import { schema, table, t, SenderError } from 'spacetimedb/server';

// No public tables: transcripts and reasoning are private to the DB owner.
const owner = table({ name: 'owner' }, { id: t.u8().primaryKey(), identity: t.identity() });
const taskSnapshot = table({ name: 'task_snapshot' }, {
  id: t.string().primaryKey(), streamId: t.string(), taskId: t.string(),
  sequence: t.u64(), data: t.string(),
});
const taskEvent = table({ name: 'task_event' }, {
  id: t.string().primaryKey(), streamId: t.string(), taskId: t.string(),
  sequence: t.u64(), data: t.string(),
});
const db = schema({ owner, taskSnapshot, taskEvent });
export default db;

export const init = db.init(ctx => {
  ctx.db.owner.insert({ id: 0, identity: ctx.sender });
});

export const sync_task = db.reducer({
  streamId: t.string(), sequence: t.u64(), taskId: t.string(), data: t.string(),
}, (ctx, { streamId, sequence, taskId, data }) => {
  const authority = ctx.db.owner.id.find(0);
  if (!authority || !authority.identity.isEqual(ctx.sender)) throw new SenderError('Owner access required');
  if (!streamId || !taskId || sequence < 1n) throw new SenderError('Invalid event identity');
  const parsed = JSON.parse(data);
  if (parsed?.type !== 'snapshot' || parsed?.task?.id !== taskId) throw new SenderError('Invalid task snapshot');
  const eventId = `${streamId}:${sequence}`;
  if (ctx.db.taskEvent.id.find(eventId)) return;
  ctx.db.taskEvent.insert({ id: eventId, streamId, taskId, sequence, data });
  const id = `${streamId}:${taskId}`;
  const current = ctx.db.taskSnapshot.id.find(id);
  if (!current) ctx.db.taskSnapshot.insert({ id, streamId, taskId, sequence, data });
  else if (sequence > current.sequence) ctx.db.taskSnapshot.id.update({ id, streamId, taskId, sequence, data });
});
