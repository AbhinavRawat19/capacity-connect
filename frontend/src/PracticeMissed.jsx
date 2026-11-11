import React, { useState } from 'react';
import { CheckCircle2, LoaderCircle, RotateCcw, X, XCircle } from 'lucide-react';
import { api } from './api';

// Quiz questions the learner got wrong that can be practised through the Question Bank.
// Each assessment question is linked to a bank entry (`question_bank_id`), which is what the
// server grades against. Questions without a link are skipped.
export function missedQuestions(assessment, attempt) {
    return (assessment?.questions || []).flatMap((q, i) => {
        const key = String(q.id || i + 1);
        const r = attempt?.question_results?.[key];
        const ok = (r && typeof r === 'object') ? !!r.correct : !!r;
        if (ok || !q.question_bank_id) return [];
        return [{ bankId: q.question_bank_id, text: q.text, options: q.options || [] }];
    });
}

export function PracticeMissed({ title, items, onClose, onSubmitted }) {
    const [current, setCurrent] = useState(items);
    const [answers, setAnswers] = useState({});
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const byId = Object.fromEntries((result?.results || []).map(r => [r.id, r]));
    const wrongNow = current.filter(q => result && byId[q.bankId] && !byId[q.bankId].correct);
    const ready = current.every(q => answers[q.bankId] !== undefined);

    async function submit() {
        setBusy(true); setError('');
        try {
            const res = await api('/question-submissions/grade-practice/', {
                method: 'POST',
                body: JSON.stringify({ answers: Object.fromEntries(current.map(q => [q.bankId, answers[q.bankId]])) }),
            });
            setResult(res);
            onSubmitted?.();
        } catch (err) {
            setError(err.message || 'Could not grade your answers.');
        } finally { setBusy(false); }
    }
    function retry() { setCurrent(wrongNow); setAnswers({}); setResult(null); setError(''); }

    return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
        <div className="glass max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl p-6">
            <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-lg font-bold text-white">{title}</h3>
                <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-800"><X size={18} /></button>
            </div>
            <p className="mb-5 text-sm text-slate-400">Answer again without the clock. Each question you get right for the first time earns 10 points; repeats don't add points.</p>
            <div className="space-y-4">
                {current.map((q, i) => {
                    const r = byId[q.bankId];
                    return <fieldset key={q.bankId} className="rounded-xl border border-slate-800 p-4">
                        <legend className="px-2 font-semibold text-white">{i + 1}. {q.text}</legend>
                        <div className="mt-2 space-y-2">
                            {q.options.map((op, j) => {
                                const chosen = Number(answers[q.bankId]) === j;
                                const isCorrect = r && Number(r.correct_answer) === j;
                                const cls = r
                                    ? (isCorrect ? 'border-lime-300/50 bg-lime-300/10 text-lime-100' : chosen ? 'border-rose-400/50 bg-rose-400/10 text-rose-100' : 'border-slate-800 text-slate-400')
                                    : (chosen ? 'border-sky-400/40 bg-sky-400/10 text-white' : 'border-slate-800 text-slate-300 hover:border-slate-600');
                                return <label key={j} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-3 text-sm ${cls}`}>
                                    <input type="radio" className="accent-lime-300" name={`practice-${q.bankId}`} disabled={!!result} checked={chosen} onChange={() => setAnswers(a => ({ ...a, [q.bankId]: j }))} />
                                    <span>{String.fromCharCode(65 + j)}. {op}</span>
                                </label>;
                            })}
                        </div>
                        {r && <div className="mt-3 rounded-lg bg-slate-900 p-3 text-sm">
                            <div className={`flex items-center gap-2 font-semibold ${r.correct ? 'text-lime-300' : 'text-rose-300'}`}>
                                {r.correct ? <CheckCircle2 size={16} /> : <XCircle size={16} />}{r.correct ? 'Correct' : 'Not quite'}{r.points_earned > 0 && <span className="badge badge-green ml-1">+{r.points_earned} pts</span>}
                            </div>
                            {r.explanation && <p className="mt-1 text-slate-400"><span className="font-semibold text-slate-300">Why: </span>{r.explanation}</p>}
                        </div>}
                    </fieldset>;
                })}
            </div>
            {error && <p role="alert" className="mt-4 rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</p>}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                {result ? <div className="rounded-xl border border-lime-300/20 bg-lime-300/5 px-4 py-3 text-lime-300"><strong>{result.correct}/{result.total} correct{result.points_earned > 0 ? ` · +${result.points_earned} points` : ''}</strong></div> : <span />}
                <div className="flex gap-2">
                    {result && wrongNow.length > 0 && <button className="btn btn-secondary" onClick={retry}><RotateCcw size={15} /> Retry {wrongNow.length} missed</button>}
                    {!result && <button className="btn btn-primary" disabled={!ready || busy} onClick={submit}>{busy ? <LoaderCircle className="animate-spin" size={16} /> : null} Check answers</button>}
                    {result && <button className="btn btn-primary" onClick={onClose}>Done</button>}
                </div>
            </div>
        </div>
    </div>;
}
