import React, { useEffect, useRef, useState } from 'react';
import { api } from './api';

const box = 'w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100';
const button = 'rounded-xl bg-lime-300 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50';
const ghost = 'rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-300 disabled:opacity-50';

// Asks the backend whether an AI provider is configured. Only a boolean is exposed; keys stay server-side.
function useAIConfigured() {
  const [configured, setConfigured] = useState(null);
  useEffect(() => {
    let live = true;
    api('/ai/status/').then(d => { if (live) setConfigured(Boolean(d.configured)); }).catch(() => { if (live) setConfigured(null); });
    return () => { live = false; };
  }, []);
  return configured;
}

function NotConfigured() {
  return <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-200">AI is not configured on this server yet. An administrator must set <code>AI_API_KEY</code> in the backend environment.</p>;
}

export function AIQuizStudio({ courses = [], lessons = [], onChanged }) {
  const configured = useAIConfigured();
  const [form, setForm] = useState({ course: '', title: 'AI-generated quiz', topic: '', difficulty: 'beginner', question_count: '5', lessons: [] });
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [result, setResult] = useState(null);
  useEffect(() => { if (!form.course && courses.length) setForm(x => ({ ...x, course: String(courses[0].id) })); }, [courses]);
  const courseLessons = lessons.filter(l => String(l.course) === String(form.course));
  const count = Number(form.question_count);
  const countValid = Number.isInteger(count) && count >= 1 && count <= 20;

  function toggleLesson(id) { setForm(x => ({ ...x, lessons: x.lessons.includes(id) ? x.lessons.filter(v => v !== id) : [...x.lessons, id] })); }
  async function generate(e) {
    e.preventDefault(); if (!countValid) { setError('Choose between 1 and 20 questions.'); return; }
    setBusy(true); setError(''); setNotice(''); setResult(null);
    try {
      const body = { course: Number(form.course), title: form.title, topic: form.topic, difficulty: form.difficulty, question_count: count, lessons: form.lessons };
      const data = await api('/ai/quizzes/generate/', { method: 'POST', body: JSON.stringify(body) });
      setResult(data.assessment); setNotice(data.message || 'Draft created.'); onChanged?.();
    } catch (err) { setError(err.message || 'Quiz generation failed.'); }
    finally { setBusy(false); }
  }
  async function publish() {
    if (!result?.id) return;
    setBusy(true); setError('');
    try { const updated = await api(`/assessments/${result.id}/`, { method: 'PATCH', body: JSON.stringify({ is_published: true }) }); setResult(updated); setNotice('Quiz published. Enrolled learners can now take it.'); onChanged?.(); }
    catch (err) { setError(err.message || 'Could not publish quiz.'); }
    finally { setBusy(false); }
  }
  async function discard() {
    if (!result?.id || !window.confirm('Discard this quiz? This cannot be undone.')) return;
    setBusy(true); setError('');
    try { await api(`/assessments/${result.id}/`, { method: 'DELETE' }); setResult(null); setNotice('Quiz discarded.'); onChanged?.(); }
    catch (err) { setError(err.message || 'Could not discard quiz.'); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5">
    <header><span className="text-xs font-bold uppercase tracking-widest text-lime-300">Part 3 · Assessment authoring</span><h2 className="mt-2 text-2xl font-black text-white">AI Quiz Studio</h2><p className="mt-1 text-sm text-slate-400">Generate a quiz from your course and lecture content. Answers stay on the server until a learner submits; review the draft before publishing.</p></header>
    {configured === false && <NotConfigured />}
    <form onSubmit={generate} className="glass grid gap-4 rounded-2xl p-5 md:grid-cols-2">
      <label className="text-sm text-slate-300">Course<select className={box + ' mt-1'} value={form.course} onChange={e => setForm({ ...form, course: e.target.value, lessons: [] })}>{courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
      <label className="text-sm text-slate-300">Quiz title<input className={box + ' mt-1'} value={form.title} maxLength={180} onChange={e => setForm({ ...form, title: e.target.value })} /></label>
      <label className="text-sm text-slate-300">Topic focus (optional)<input className={box + ' mt-1'} value={form.topic} maxLength={120} onChange={e => setForm({ ...form, topic: e.target.value })} placeholder="e.g. recursion" /></label>
      <label className="text-sm text-slate-300">Difficulty<select className={box + ' mt-1'} value={form.difficulty} onChange={e => setForm({ ...form, difficulty: e.target.value })}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
      <label className="text-sm text-slate-300">Number of questions (1–20)<input type="number" min="1" max="20" className={box + ' mt-1'} value={form.question_count} onChange={e => setForm({ ...form, question_count: e.target.value })} /></label>
      {courseLessons.length > 0 && <fieldset className="text-sm text-slate-300"><legend>Limit to lectures (optional)</legend><div className="mt-1 max-h-28 space-y-1 overflow-y-auto rounded-xl border border-slate-700 p-2">{courseLessons.map(l => <label key={l.id} className="flex items-center gap-2"><input type="checkbox" checked={form.lessons.includes(l.id)} onChange={() => toggleLesson(l.id)} />{l.title}</label>)}</div></fieldset>}
      <div className="flex items-end md:col-span-2"><button className={button} disabled={busy || !courses.length || !form.course || configured === false}>{busy ? 'Generating… this can take up to a minute' : 'Generate quiz draft'}</button>{!courses.length && <span className="ml-3 text-sm text-slate-400">Create a course first.</span>}</div>
      {error && <p role="alert" className="text-sm text-rose-400 md:col-span-2">{error}</p>}
      {notice && !error && <p className="text-sm text-lime-300 md:col-span-2">{notice}</p>}
    </form>
    {result && <section className="glass space-y-4 rounded-2xl p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-bold text-white">{result.title}</h3><p className={'text-xs ' + (result.is_published ? 'text-lime-300' : 'text-amber-300')}>{result.is_published ? 'Published' : 'Unpublished draft'} · {result.question_count} questions · only you can see the answer key</p></div>{!result.is_published && <div className="flex gap-2"><button className={ghost} disabled={busy} onClick={discard}>Discard</button><button className={button} disabled={busy} onClick={publish}>Publish reviewed quiz</button></div>}</div>{(result.questions || []).map((q, i) => <article key={q.id || i} className="rounded-xl border border-slate-700 p-4"><p className="font-semibold text-white">{i + 1}. {q.text}</p><ol className="mt-2 space-y-1 text-sm text-slate-300">{(q.options || []).map((o, j) => <li key={j} className={j === q.correct_answer ? 'text-lime-300' : ''}>{String.fromCharCode(65 + j)}. {o}{j === q.correct_answer ? ' ✓' : ''}</li>)}</ol>{q.explanation && <p className="mt-2 text-xs text-slate-400">{q.explanation}</p>}</article>)}</section>}
  </div>;
}

export function AILearningTutor({ courses = [] }) {
  const configured = useAIConfigured();
  const [threads, setThreads] = useState([]), [active, setActive] = useState(null), [messages, setMessages] = useState([]), [text, setText] = useState(''), [course, setCourse] = useState('');
  const [busy, setBusy] = useState(false), [loadingThreads, setLoadingThreads] = useState(true), [loadingMessages, setLoadingMessages] = useState(false), [error, setError] = useState('');
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [messages, busy]);
  async function refresh() { try { setThreads(await api('/ai/tutor/conversations/')); } catch (e) { setError(e.message); } finally { setLoadingThreads(false); } }
  useEffect(() => { refresh(); }, []);
  async function openThread(id) {
    setActive(id); setError(''); setMessages([]); setLoadingMessages(true);
    try { const d = await api(`/ai/tutor/conversations/${id}/`); setMessages(d.messages || []); } catch (e) { setError(e.message); } finally { setLoadingMessages(false); }
  }
  async function createThread() {
    setBusy(true); setError('');
    try { const d = await api('/ai/tutor/conversations/', { method: 'POST', body: JSON.stringify({ course: course ? Number(course) : null }) }); await refresh(); await openThread(d.id); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function send(e) {
    e.preventDefault(); const content = text.trim(); if (!content || !active || busy) return;
    const pending = { id: 'pending-' + Date.now(), role: 'user', content };
    setText(''); setBusy(true); setError(''); setMessages(m => [...m, pending]);
    try {
      const d = await api(`/ai/tutor/conversations/${active}/messages/`, { method: 'POST', body: JSON.stringify({ message: content }) });
      setMessages(m => [...m.filter(x => x.id !== pending.id), d.user_message, d.assistant_message]); await refresh();
    } catch (err) { setMessages(m => m.filter(x => x.id !== pending.id)); setError(err.message); setText(content); }
    finally { setBusy(false); }
  }
  async function removeThread() {
    if (!active || !window.confirm('Delete this conversation and its messages?')) return;
    try { await api(`/ai/tutor/conversations/${active}/`, { method: 'DELETE' }); setActive(null); setMessages([]); refresh(); } catch (e) { setError(e.message); }
  }
  const activeThread = threads.find(t => t.id === active);
  return <div className="space-y-4"><header><span className="text-xs font-bold uppercase tracking-widest text-lime-300">Part 4 · Personal learning support</span><h2 className="mt-2 text-2xl font-black text-white">AI Learning Assistant</h2><p className="mt-1 text-sm text-slate-400">Ask questions and get step-by-step explanations. With a course selected, the tutor uses that course's material and your own quiz and competency progress.</p></header>
    {configured === false && <NotConfigured />}
    <div className="grid min-h-[520px] gap-4 lg:grid-cols-[260px_1fr]"><aside className="glass space-y-3 rounded-2xl p-4"><select aria-label="Course context" className={box} value={course} onChange={e => setCourse(e.target.value)}><option value="">General tutor (no course)</option>{courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select><button className={button + ' w-full'} onClick={createThread} disabled={busy || configured === false}>New conversation</button><div className="space-y-2">{loadingThreads ? <p className="text-sm text-slate-500">Loading conversations…</p> : threads.length ? threads.map(t => <button key={t.id} onClick={() => openThread(t.id)} className={'w-full rounded-lg p-3 text-left text-sm ' + (active === t.id ? 'bg-slate-700 text-white' : 'text-slate-300 hover:bg-slate-800')}><span className="block truncate font-semibold">{t.title}</span><span className="text-xs text-slate-500">{t.course_title || 'General'}</span></button>) : <p className="text-sm text-slate-500">No conversations yet.</p>}</div></aside>
    <section className="glass flex min-h-[520px] flex-col rounded-2xl p-4">{activeThread && <div className="mb-3 border-b border-slate-800 pb-2 text-xs text-slate-400">Context: {activeThread.course_title || 'General knowledge only'}</div>}<div className="flex-1 space-y-3 overflow-y-auto">{loadingMessages ? <p className="text-sm text-slate-500">Loading messages…</p> : messages.length ? messages.map(m => <div key={m.id} className={'max-w-[90%] whitespace-pre-wrap rounded-2xl p-3 text-sm ' + (m.role === 'user' ? 'ml-auto bg-lime-300 text-slate-950' : 'bg-slate-800 text-slate-100')}>{m.content}</div>) : <div className="grid h-full place-items-center text-center text-sm text-slate-500">{active ? 'Ask your first question below.' : 'Start or select a conversation to begin.'}</div>}{busy && active && <div className="max-w-[90%] rounded-2xl bg-slate-800 p-3 text-sm text-slate-400">The tutor is thinking…</div>}<div ref={endRef} /></div>{error && <p role="alert" className="my-2 text-sm text-rose-400">{error}</p>}<form onSubmit={send} className="mt-3 flex gap-2"><input className={box} value={text} maxLength={6000} onChange={e => setText(e.target.value)} placeholder="Ask a question…" disabled={!active || busy} /><button className={button} disabled={!active || busy || !text.trim()}>Send</button>{active && <button type="button" onClick={removeThread} disabled={busy} className={ghost}>Delete</button>}</form></section></div>
  </div>;
}
