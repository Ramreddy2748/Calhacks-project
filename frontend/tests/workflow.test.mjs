import test from 'node:test';
import assert from 'node:assert/strict';
import { workflowFor } from '../src/workflow.mjs';

const base = { mode: 'demo', plan: [], transcript: [], activity: [], approval: null, summary: null };
const stages = changes => Object.fromEntries(workflowFor({ ...base, ...changes }).map(stage => [stage.name, stage]));

test('planning does not imply the conversation or approval has started', () => {
  const result = stages({ status: 'planning' });
  assert.equal(result.Planner.state, 'current');
  assert.equal(result.Negotiator.state, 'pending');
  assert.equal(result.Guardrail.state, 'pending');
  assert.equal(result.Reporter.state, 'pending');
});

test('a pending approval pauses negotiation and highlights the user decision', () => {
  const result = stages({ status: 'awaiting_approval', plan: ['Plan'], approval: { status: 'pending' } });
  assert.equal(result.Planner.state, 'done');
  assert.equal(result.Negotiator.state, 'paused');
  assert.equal(result.Guardrail.state, 'waiting');
});

test('a declined call may complete without being shown as approved', () => {
  const result = stages({ status: 'completed', plan: ['Plan'], transcript: ['Conversation'], approval: { status: 'declined' }, summary: 'Ended without committing.' });
  assert.equal(result.Guardrail.state, 'resolved');
  assert.equal(result.Guardrail.detail, 'You declined');
  assert.equal(result.Reporter.state, 'done');
});

test('cancellation stops pending work even with a stale pending approval', () => {
  const result = stages({ status: 'cancelled', approval: { status: 'pending' } });
  assert.equal(result.Guardrail.state, 'stopped');
  assert.ok(Object.values(result).every(stage => !['current', 'waiting'].includes(stage.state)));
  assert.equal(result.Reporter.detail, 'No summary recorded');
});

test('live calls do not invent approvals and retain the Vapi voice handoff', () => {
  const live = stages({ status: 'in_progress', mode: 'live', provider_call_id: 'call-1' });
  assert.equal(live.Negotiator.detail, 'Conversation via Vapi');
  const ended = stages({ status: 'completed', provider_call_id: 'call-1' });
  assert.equal(ended.Guardrail.detail, 'No approval recorded');
  assert.equal(ended.Reporter.state, 'pending');
});

test('hold and expired approval remain distinguishable from an approved change', () => {
  assert.equal(stages({ status: 'on_hold' }).Negotiator.detail, 'Waiting on hold');
  assert.equal(stages({ status: 'completed', approval: { status: 'expired' } }).Guardrail.detail, 'Approval expired');
  assert.equal(stages({ status: 'completed', approval: { status: 'approved' } }).Guardrail.detail, 'You approved');
});
