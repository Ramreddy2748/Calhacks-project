import React from 'react';
import { Check, CheckCheck, FileText, Mic, Phone, Radio, RefreshCw, ShieldCheck, Sparkles, Workflow } from 'lucide-react';
import { workflowFor } from './workflow.mjs';

const ROLE_ICONS = { Planner: FileText, Negotiator: Mic, Guardrail: ShieldCheck, Reporter: CheckCheck };

export function AgentWorkflow({ task }) {
  const stages = workflowFor(task);
  const needsApproval = stages.some(stage => stage.state === 'waiting');
  return <section className="panel workflow-panel" aria-labelledby="workflow-title">
    <div className="workflow-heading"><div><h3 id="workflow-title"><Workflow size={17}/>Your team at work</h3><p>Call stages, updated from recorded activity.</p></div><span className={`workflow-caption ${needsApproval ? 'needs-decision' : ''}`}>{needsApproval ? 'Your decision comes next' : task.status === 'completed' ? 'Call finished' : ['failed', 'cancelled', 'interrupted'].includes(task.status) ? 'Session stopped' : 'One step at a time'}</span></div>
    <ol className="workflow-stages">{stages.map(stage => {
      const Icon = ROLE_ICONS[stage.name];
      return <li key={stage.name} className={`workflow-stage stage-${stage.state}`} aria-current={['current', 'waiting'].includes(stage.state) ? 'step' : undefined}>
        <span className="stage-icon">{stage.state === 'done' ? <Check size={18}/> : <Icon size={18}/>}</span>
        <div><strong>{stage.name}</strong><span>{stage.detail}</span></div>
      </li>;
    })}</ol>
  </section>;
}

export function ConnectionStatus({ health, connection, checkedAt, refreshing, refresh }) {
  const checking = connection === 'checking';
  const online = connection === 'online';
  const fetchReady = online && health?.fetch?.ready;
  const services = [
    { name: 'Backend', Icon: Radio, tone: checking ? 'neutral' : online ? 'good' : 'bad', label: checking ? 'Checking' : online ? 'Online' : 'Offline', detail: online ? 'Local API responding' : checking ? 'Contacting your workspace' : 'Unable to reach the local API' },
    { name: 'Fetch.ai', Icon: Workflow, tone: checking ? 'neutral' : fetchReady ? 'good' : 'warn', label: checking ? 'Checking' : !online ? 'Unknown' : fetchReady ? 'Running locally' : 'Unavailable', detail: fetchReady ? 'Five agents, one local team' : !online ? 'Backend needed to check' : 'Agent runtime is not ready' },
    { name: 'SpacetimeDB', Icon: Radio, tone: checking || !online || !health?.spacetime?.configured ? 'neutral' : health.spacetime.error ? 'warn' : health.spacetime.connected ? 'good' : 'neutral', label: checking ? 'Checking' : !online ? 'Unknown' : health?.spacetime?.error ? 'Sync error' : health?.spacetime?.connected ? (health.spacetime.pending_events ? 'Syncing' : 'Synced') : health?.spacetime?.configured ? 'Configured' : 'Not configured', detail: health?.spacetime?.configured ? `${health.spacetime.pending_events} events queued locally` : 'Optional persistent event mirror' },
    { name: 'Claude', Icon: Sparkles, tone: 'neutral', label: checking ? 'Checking' : !online ? 'Unknown' : health?.claude ? 'Configured' : 'Not configured', detail: !online ? 'Backend needed to check' : health?.claude ? 'Planning, simulated dialogue & summaries' : 'Optional for the scripted demo' },
    { name: 'Vapi', Icon: Phone, tone: 'neutral', label: checking ? 'Checking' : !online ? 'Unknown' : health?.browser || health?.live ? 'Configured' : 'Not configured', detail: !online ? 'Backend needed to check' : health?.browser ? 'Browser setup set · not verified' : health?.live ? 'Phone setup set · not verified' : 'Optional for the scripted demo' },
  ];
  return <section className="panel connections" aria-labelledby="connections-title">
    <div className="connections-heading"><h2 id="connections-title">Your connections</h2><div><span className="connection-checked">{checkedAt ? `Checked ${new Date(checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Checking status…'}</span><button className="connection-refresh" onClick={refresh} disabled={refreshing} aria-label="Refresh connection status"><RefreshCw size={13} className={refreshing ? 'spin' : ''}/><span>Refresh</span></button></div></div>
    <div className="connection-grid">{services.map(({ name, Icon, tone, label, detail }) => <div className="connection-service" key={name}><div className="connection-service-top"><span className="connection-name"><Icon size={14}/>{name}</span><span className={`connection-badge connection-${tone}`}><i/>{label}</span></div><p>{detail}</p></div>)}</div>
  </section>;
}
