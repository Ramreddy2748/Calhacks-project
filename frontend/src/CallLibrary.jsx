import React, { useState } from 'react';
import { ArrowRight, ChevronRight, LoaderCircle, Phone, PhoneCall, Search, X } from 'lucide-react';

const FINISHED = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const FILTERS = [ ['all', 'All calls'], ['active', 'In progress'], ['approval', 'Needs approval'], ['completed', 'Completed'] ];

export function CallLibrary({ tasks, loading, view, openCall, newCall, showHistory, Status }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const matchesFilter = (task, value) => value === 'all' || (value === 'active' ? !FINISHED.has(task.status) : value === 'approval' ? task.status === 'awaiting_approval' && task.approval?.status === 'pending' : task.status === value);
  const filtered = tasks.filter(task => matchesFilter(task, filter) && `${task.goal} ${task.phone || ''}`.toLowerCase().includes(query.trim().toLowerCase()));
  const visible = view === 'history' ? filtered : filtered.slice(0, 5);
  const reset = () => { setQuery(''); setFilter('all'); };

  return <section className="calls-section">
    <div className="section-heading"><h2>{view === 'history' ? 'All calls' : 'Your calls'}<span>{tasks.length}</span></h2>{view === 'overview' && <button onClick={showHistory}>View all calls <ArrowRight size={15}/></button>}</div>
    <div className="panel calls-panel">
      {tasks.length > 0 && <div className="library-toolbar">
        <div className="call-filters" role="group" aria-label="Filter calls by status">{FILTERS.map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}<span>{tasks.filter(task => matchesFilter(task, value)).length}</span></button>)}</div>
        <div className="call-search"><Search size={16} aria-hidden="true"/><input type="search" aria-label="Search calls by goal or phone number" placeholder="Search calls…" value={query} onChange={event => setQuery(event.target.value)}/>{query && <button aria-label="Clear search" onClick={() => setQuery('')}><X size={14}/></button>}</div>
      </div>}
      {loading ? <div className="empty-state"><LoaderCircle className="spin"/><h3>Getting things ready…</h3></div> : visible.length ? <>
        <div className="library-result" role="status">{filtered.length === tasks.length ? 'Your latest conversations' : `${filtered.length} matching ${filtered.length === 1 ? 'call' : 'calls'}`}</div>
        <div className="table-wrap"><table><thead><tr><th>CALL & GOAL</th><th>DATE</th><th>STATUS</th><th><span className="sr-only">Open call</span></th></tr></thead><tbody>{visible.map(task => <tr key={task.id} onClick={() => openCall(task.id)}><td><button className="call-row-button" onClick={() => openCall(task.id)}><span className="table-phone"><Phone size={17}/></span><span>{task.goal}<small>{task.mode === 'demo' ? 'Simulation · no number dialed' : task.mode === 'browser' ? 'Browser voice · role-play' : task.phone}</small></span></button></td><td className="date-cell">{new Date(task.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<small>{new Date(task.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></td><td><Status status={task.status}/></td><td><ChevronRight size={17}/></td></tr>)}</tbody></table></div>
        {visible.length < filtered.length && <button className="library-more" onClick={showHistory}>See all {filtered.length} matching calls <ArrowRight size={14}/></button>}
      </> : tasks.length ? <div className="empty-state"><Search size={25}/><h3>No calls match just yet.</h3><p>Try a different phrase or choose another status.</p><button onClick={reset}>Clear filters <ArrowRight size={15}/></button></div> : <div className="empty-state"><div className="empty-icon"><PhoneCall size={25}/><span>✦</span></div><h3>A quieter to-do list starts here.</h3><p>No calls yet. Give your assistant a task and let it take the first step.</p><button onClick={newCall}>Create your first call <ArrowRight size={15}/></button></div>}
    </div>
  </section>;
}
