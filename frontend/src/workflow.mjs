const ENDED = new Set(['completed', 'cancelled', 'failed', 'interrupted']);

// Display recorded progress, not an estimate of which process is executing.
export function workflowFor(task) {
  const ended = ENDED.has(task.status);
  const stopped = ended && task.status !== 'completed';
  const planned = Boolean(task.plan?.length);
  const conversationStarted = Boolean(task.transcript?.length || task.provider_call_id ||
    task.activity?.some(item => ['Caller', 'Negotiator'].includes(item.agent)));
  const approval = task.approval;
  const waiting = !ended && task.status === 'awaiting_approval' && approval?.status === 'pending';
  const decisionLabels = { approved: 'You approved', declined: 'You declined', expired: 'Approval expired' };
  const decision = decisionLabels[approval?.status];
  const conversationActive = !ended && ['calling', 'on_hold', 'in_progress'].includes(task.status);
  return [
    { name: 'Planner', state: planned ? 'done' : stopped ? 'stopped' : task.status === 'planning' ? 'current' : 'pending',
      detail: planned ? 'Plan ready' : ended ? 'No plan recorded' : task.status === 'planning' ? 'Preparing the plan' : 'Up next' },
    { name: 'Negotiator', state: waiting ? 'paused' : conversationActive ? 'current' : conversationStarted && ended ? 'done' : stopped ? 'stopped' : 'pending',
      detail: waiting ? 'Paused for your decision' : task.status === 'on_hold' ? 'Waiting on hold' : conversationActive ? (task.mode === 'demo' ? 'Simulated conversation' : task.mode === 'browser' ? 'Browser voice via Vapi' : task.phone_provider === 'elevenlabs' ? 'Phone call via ElevenLabs' : 'Conversation via Vapi') : conversationStarted && ended ? 'Conversation ended' : stopped ? 'Stopped' : task.status === 'awaiting_approval' && decision ? 'Decision received' : 'Up next' },
    { name: 'Guardrail', state: waiting ? 'waiting' : decision ? (approval.status === 'approved' ? 'done' : 'resolved') : stopped ? 'stopped' : 'pending',
      detail: waiting ? 'Needs your approval' : decision || (ended ? 'No approval recorded' : 'Checks commitments with you') },
    { name: 'Reporter', state: task.summary ? 'done' : stopped ? 'stopped' : 'pending',
      detail: task.summary ? 'Summary ready' : ended ? 'No summary recorded' : 'Summarizes the outcome' },
  ];
}
