import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { VerifyCertificate } from './Certificate.jsx'
import './index.css'
// A shared certificate link looks like /?verify=CC-1-2-ABCDEF123456 and works without signing in.
const verifyCode = new URLSearchParams(window.location.search).get('verify')
createRoot(document.getElementById('root')).render(<React.StrictMode>{verifyCode ? <VerifyCertificate code={verifyCode} /> : <App />}</React.StrictMode>)
