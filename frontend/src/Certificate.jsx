import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Award, CheckCircle2, LoaderCircle, XCircle } from 'lucide-react';
import { api } from './api';

export const formatDate = (value) => new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
export const verifyUrl = (code) => `${window.location.origin}/?verify=${encodeURIComponent(code)}`;

// The printable certificate. Inline styles keep it readable on paper regardless of the dark app theme.
export function CertificateSheet({ cert }) {
    const ink = '#1e293b', accent = '#4d7c0f';
    return <div style={{ background: '#fffdf7', color: ink, border: `6px double ${accent}`, padding: '36px 28px', textAlign: 'center', fontFamily: 'Georgia, "Times New Roman", serif', WebkitPrintColorAdjust: 'exact', printColorAdjust: 'exact' }}>
        <div style={{ letterSpacing: '0.3em', fontSize: 12, color: accent, fontWeight: 700 }}>CAPACITY CONNECT</div>
        <h2 style={{ fontSize: 34, margin: '10px 0 4px', fontWeight: 700 }}>Certificate of Completion</h2>
        <p style={{ margin: '18px 0 6px', fontSize: 14, color: '#475569' }}>This certifies that</p>
        <div style={{ fontSize: 30, fontStyle: 'italic', borderBottom: `1px solid ${accent}`, display: 'inline-block', padding: '0 24px 4px' }}>{cert.learner_name}</div>
        <p style={{ margin: '18px 0 6px', fontSize: 14, color: '#475569' }}>has successfully completed the course</p>
        <div style={{ fontSize: 24, fontWeight: 700 }}>{cert.course_title}</div>
        <p style={{ margin: '14px 0 0', fontSize: 14, color: '#475569' }}>
            with an average score of <b style={{ color: ink }}>{cert.average_score}%</b> across {cert.quizzes_completed} {cert.quizzes_completed === 1 ? 'quiz' : 'quizzes'}
        </p>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginTop: 30, fontSize: 13, textAlign: 'left' }}>
            <div><div style={{ color: '#64748b' }}>Issued</div><b>{formatDate(cert.issued_at)}</b></div>
            <div style={{ textAlign: 'right' }}><div style={{ color: '#64748b' }}>Instructor</div><b>{cert.trainer_name}</b></div>
        </div>
        <div style={{ marginTop: 24, paddingTop: 12, borderTop: '1px dashed #cbd5e1', fontSize: 11, color: '#64748b', fontFamily: 'ui-monospace, Menlo, monospace', wordBreak: 'break-all' }}>
            Certificate ID {cert.code}<br />Verify at {verifyUrl(cert.code)}
        </div>
    </div>;
}

// A second, screen-hidden copy rendered straight into <body> so printing shows only the certificate.
export function PrintableCertificate({ cert }) {
    return createPortal(<div className="print-only"><CertificateSheet cert={cert} /></div>, document.body);
}

export function CertificateCard({ cert, onOpen }) {
    return <div className="glass card-hover rounded-2xl p-5">
        <div className="flex items-start gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-lime-300/15 text-lime-300"><Award size={22} /></div>
            <div className="min-w-0">
                <h3 className="font-bold text-white">{cert.course_title}</h3>
                <p className="mt-1 text-sm text-slate-400">Issued {formatDate(cert.issued_at)} · average {cert.average_score}%</p>
                <p className="mt-1 truncate font-mono text-xs text-slate-500">{cert.code}</p>
            </div>
        </div>
        <button className="btn btn-primary mt-4 w-full" onClick={() => onOpen(cert)}>View / print certificate</button>
    </div>;
}

// Public page, opened from /?verify=CODE. No login needed.
export function VerifyCertificate({ code }) {
    const [state, setState] = useState({ loading: true, data: null, error: '' });
    useEffect(() => {
        let alive = true;
        api(`/certificates/verify/${encodeURIComponent(code)}/`)
            .then(data => alive && setState({ loading: false, data, error: '' }))
            .catch(err => alive && setState({ loading: false, data: null, error: err.message || 'Could not verify this certificate.' }));
        return () => { alive = false; };
    }, [code]);
    const { loading, data, error } = state;
    return <div className="grid min-h-screen place-items-center p-4">
        <div className="glass w-full max-w-xl rounded-2xl p-6 sm:p-8">
            <div className="text-xs font-bold tracking-[0.25em] text-lime-300">CAPACITY CONNECT</div>
            <h1 className="mt-2 text-2xl font-black text-white">Certificate verification</h1>
            <p className="mt-1 break-all font-mono text-xs text-slate-500">{code}</p>
            <div className="mt-6">
                {loading && <div className="flex items-center gap-2 text-slate-300"><LoaderCircle className="animate-spin" size={18} /> Checking…</div>}
                {!loading && error && <div className="flex items-start gap-3 rounded-xl border border-rose-400/30 bg-rose-400/10 p-4 text-rose-100"><XCircle className="mt-0.5 shrink-0" size={20} /><span>{error}</span></div>}
                {!loading && data && !data.valid && <div className="flex items-start gap-3 rounded-xl border border-rose-400/30 bg-rose-400/10 p-4 text-rose-100"><XCircle className="mt-0.5 shrink-0" size={20} /><div><b>Not a valid certificate.</b><p className="mt-1 text-sm text-rose-200/80">This ID was not issued by CAPACITY CONNECT, or the course has not been completed.</p></div></div>}
                {!loading && data?.valid && <>
                    <div className="flex items-start gap-3 rounded-xl border border-lime-300/30 bg-lime-300/10 p-4 text-lime-100"><CheckCircle2 className="mt-0.5 shrink-0" size={20} /><b>This certificate is genuine.</b></div>
                    <dl className="mt-5 space-y-3 text-sm">
                        {[['Awarded to', data.learner_name], ['Course', data.course_title], ['Instructor', data.trainer_name], ['Average score', `${data.average_score}% across ${data.quizzes_completed} ${data.quizzes_completed === 1 ? 'quiz' : 'quizzes'}`], ['Issued', formatDate(data.issued_at)]].map(([k, v]) => <div key={k} className="flex justify-between gap-4 border-b border-slate-800 pb-2"><dt className="text-slate-400">{k}</dt><dd className="text-right font-semibold text-white">{v}</dd></div>)}
                    </dl>
                </>}
            </div>
            <a href="/" className="btn btn-secondary mt-6 w-full">Go to CAPACITY CONNECT</a>
        </div>
    </div>;
}
