import React from 'react';
import { Award, BookOpen, CheckCircle2, FileText, Flame, GraduationCap, Lock, MessageCircle, Sparkles, Star, Target, Trophy, Zap } from 'lucide-react';

const ICONS = {
    first_quiz: Star, quiz_regular: Target, perfect_score: Trophy, certified: GraduationCap, practice_10: Zap,
    streak_3: Flame, streak_7: Flame, assignment: FileText, community: MessageCircle, contributor: BookOpen, century: Sparkles,
};

const shortDay = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

export function AchievementsPanel({ data, loading }) {
    if (loading && !data) return <div className="glass rounded-2xl p-6 text-sm text-slate-400">Loading your achievements…</div>;
    if (!data) return null;
    const { streak } = data;
    const levelPct = Math.round((data.level_xp / data.xp_per_level) * 100);
    const streakText = streak.current > 0
        ? `${streak.current}-day streak${streak.active_today ? '' : ' — study today to keep it going'}`
        : 'No streak yet — take a quiz or practise a question today';
    return <section className="glass rounded-2xl p-5 sm:p-6" aria-label="Achievements">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="flex items-center gap-4">
                <div className="grid h-20 w-20 shrink-0 place-items-center rounded-full border-4 border-lime-300/30 bg-lime-300/10 text-center">
                    <div><div className="text-[10px] font-bold uppercase tracking-wider text-lime-300">Level</div><div className="text-3xl font-black leading-none text-white">{data.level}</div></div>
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2"><span className="font-bold text-white">{data.xp} XP</span><span className="text-xs text-slate-400">{data.xp_per_level - data.level_xp} XP to level {data.level + 1}</span></div>
                    <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-slate-800" role="progressbar" aria-valuenow={levelPct} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-lime-300" style={{ width: `${levelPct}%` }} /></div>
                    <p className="mt-2 text-xs text-slate-500">XP uses the same points as the leaderboard: quizzes, practice and approved questions.</p>
                </div>
            </div>
            <div>
                <div className="flex items-center gap-2 font-bold text-white"><Flame size={18} className={streak.current > 0 ? 'text-orange-400' : 'text-slate-600'} />{streakText}</div>
                <div className="mt-3 flex gap-1.5" aria-label="Activity in the last 14 days">{data.last_14_days.map(d => <div key={d.date} title={`${shortDay(d.date)}${d.active ? ' — studied' : ''}`} className={`h-7 flex-1 rounded-md ${d.active ? 'bg-lime-300' : 'bg-slate-800'}`} />)}</div>
                <p className="mt-2 text-xs text-slate-500">Longest streak: {streak.longest} {streak.longest === 1 ? 'day' : 'days'} · Last 14 days</p>
            </div>
        </div>

        <div className="mt-6 flex items-center justify-between"><h3 className="font-bold text-white">Badges</h3><span className="badge badge-green">{data.earned_count} / {data.badges.length} earned</span></div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.badges.map(b => {
                const Icon = ICONS[b.key] || Award;
                return <div key={b.key} className={`rounded-xl border p-4 ${b.earned ? 'border-lime-300/30 bg-lime-300/5' : 'border-slate-800 opacity-80'}`}>
                    <div className="flex items-start gap-3">
                        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${b.earned ? 'bg-lime-300/15 text-lime-300' : 'bg-slate-800 text-slate-500'}`}>{b.earned ? <Icon size={20} /> : <Lock size={18} />}</div>
                        <div className="min-w-0">
                            <div className="flex items-center gap-1.5 font-semibold text-white">{b.title}{b.earned && <CheckCircle2 size={14} className="text-lime-300" />}</div>
                            <p className="mt-0.5 text-xs text-slate-400">{b.description}</p>
                        </div>
                    </div>
                    {!b.earned && b.target > 1 && <div className="mt-3"><div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-slate-500" style={{ width: `${Math.round(b.current / b.target * 100)}%` }} /></div><div className="mt-1 text-right text-[11px] text-slate-500">{b.current} / {b.target}</div></div>}
                </div>;
            })}
        </div>
    </section>;
}
