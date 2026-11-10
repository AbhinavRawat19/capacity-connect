import React from 'react';
import { Award, BookOpen, ClipboardCheck, DollarSign, LoaderCircle, TrendingUp, Users } from 'lucide-react';

const money = (value) => `$${Number(value || 0).toFixed(2)}`;

function Bar({ value, tone = 'lime' }) {
    const pct = Math.max(0, Math.min(100, Number(value) || 0));
    const color = tone === 'rose' ? 'bg-rose-400' : tone === 'amber' ? 'bg-amber-300' : 'bg-lime-300';
    return <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} /></div>;
}

const accuracyTone = (pct) => pct < 40 ? 'rose' : pct < 70 ? 'amber' : 'lime';

function HardQuestions({ items }) {
    if (!items?.length) return <p className="text-sm text-slate-500">No quiz answers yet. Once learners take your quizzes, the questions they struggle with most will show up here.</p>;
    return <div className="space-y-3">{items.map((q, i) => <div key={i}>
        <div className="flex items-start justify-between gap-3 text-sm"><span className="text-slate-200">{q.text}</span><span className="shrink-0 font-bold text-white">{q.accuracy}%</span></div>
        <div className="mt-1.5"><Bar value={q.accuracy} tone={accuracyTone(q.accuracy)} /></div>
        <div className="mt-1 text-xs text-slate-500">{q.course} · {q.assessment} · {q.correct}/{q.attempts} correct</div>
    </div>)}</div>;
}

export function AnalyticsView({ data, loading, error, isAdmin }) {
    if (loading && !data) return <div className="glass flex items-center gap-2 rounded-2xl p-6 text-slate-300"><LoaderCircle className="animate-spin" size={18} /> Loading analytics…</div>;
    if (error) return <div className="glass rounded-2xl p-6 text-rose-200">{error}</div>;
    if (!data) return null;
    const s = data.summary;
    const tiles = [
        [BookOpen, s.courses, isAdmin ? 'Courses on the platform' : 'Your courses'],
        [Users, s.learners, 'Enrolled learners'],
        [ClipboardCheck, s.quiz_attempts, 'Quiz attempts'],
        [TrendingUp, s.average_score == null ? '–' : `${s.average_score}%`, 'Average quiz score'],
        [Award, s.certificates, 'Certificates earned'],
        [DollarSign, money(isAdmin ? s.platform_fee : s.trainer_earnings), isAdmin ? 'Platform fees (net of refunds)' : 'Your earnings (net of refunds)'],
    ];
    return <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{tiles.map(([Icon, n, label]) => <div key={label} className="glass rounded-2xl p-5"><Icon size={18} className="text-lime-300" /><div className="mt-3 text-3xl font-black text-white">{n}</div><div className="mt-1 text-sm text-slate-400">{label}</div></div>)}</div>

        <section className="glass rounded-2xl p-5 sm:p-6">
            <h2 className="text-lg font-bold text-white">Questions learners struggle with</h2>
            <p className="mb-4 mt-1 text-sm text-slate-400">Lowest accuracy first. Use this to improve a lecture or rewrite an unclear question.</p>
            <HardQuestions items={data.hardest_questions} />
        </section>

        <section className="space-y-4">
            <h2 className="text-lg font-bold text-white">Course performance</h2>
            {data.courses.length === 0 && <div className="glass rounded-2xl p-6 text-sm text-slate-400">No courses yet. Create a course in the Teaching studio to see its analytics here.</div>}
            {data.courses.map(c => <div key={c.id} className="glass rounded-2xl p-5 sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div><h3 className="font-bold text-white">{c.title}</h3><p className="mt-1 text-xs text-slate-500">{isAdmin ? `${c.trainer_name} · ` : ''}{c.is_published ? 'Published' : 'Draft'} · {Number(c.price) > 0 ? `$${c.price}` : 'Free'}</p></div>
                    <div className="flex flex-wrap gap-2 text-xs"><span className="badge">{c.learners} learners</span><span className="badge">{c.quizzes} quizzes</span><span className="badge badge-green">{c.certificates} certified</span>{c.inactive_learners > 0 && <span className="badge badge-yellow">{c.inactive_learners} not started quizzes</span>}</div>
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                    <div><div className="mb-1.5 flex justify-between text-sm"><span className="text-slate-400">Completion rate</span><b className="text-white">{c.completion_rate}%</b></div><Bar value={c.completion_rate} /></div>
                    <div><div className="mb-1.5 flex justify-between text-sm"><span className="text-slate-400">Average quiz score</span><b className="text-white">{c.average_score == null ? '–' : `${c.average_score}%`}</b></div><Bar value={c.average_score || 0} tone={accuracyTone(c.average_score || 0)} /></div>
                </div>
                {Number(c.price) > 0 && <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
                    <div className="rounded-xl border border-slate-800 p-3"><div className="text-slate-400">Gross sales</div><div className="mt-1 text-lg font-bold text-white">{money(c.gross_revenue)}</div></div>
                    <div className="rounded-xl border border-slate-800 p-3"><div className="text-slate-400">Refunded</div><div className="mt-1 text-lg font-bold text-white">{money(c.refunded)}</div></div>
                    <div className="rounded-xl border border-slate-800 p-3"><div className="text-slate-400">{isAdmin ? 'Trainer share' : 'Your earnings'}</div><div className="mt-1 text-lg font-bold text-lime-200">{money(c.trainer_earnings)}</div></div>
                </div>}
                {c.hardest_questions?.length > 0 && <div className="mt-5"><div className="mb-2 text-sm font-semibold text-slate-300">Hardest questions in this course</div><HardQuestions items={c.hardest_questions} /></div>}
            </div>)}
        </section>
    </div>;
}
