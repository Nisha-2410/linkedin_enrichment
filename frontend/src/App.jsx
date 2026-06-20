import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ArrowDownToLine, Building2, Check, ChevronDown, FileJson, Search, Sparkles, Trash2, UploadCloud, Users, X } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
const LABELS = {
  resolved_90: 'Resolved Â· 90+',
  resolved_85_fallback: 'Resolved Â· fallback',
  needs_next_round: 'Needs next round',
  exhausted: 'Exhausted',
}

async function api(path, options) {
  const response = await fetch(`${API}${path}`, options)
  if (!response.ok) {
    let detail = 'Something went wrong'
    try { detail = (await response.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return response.json()
}

function StatusBadge({ status }) {
  return <span className={`badge ${status}`}><i />{LABELS[status] || status}</span>
}

function ConfirmDialog({ action, busy, onCancel, onConfirm }) {
  const [typed, setTyped] = useState('')

  useEffect(() => { setTyped('') }, [action])

  if (!action) return null

  const disabled = busy || (action.requireTyped && typed !== 'DELETE')

  return <div className="modal-overlay">
    <div className="modal-card">
      <span className="modal-icon"><AlertTriangle size={24}/></span>
      <h2>{action.title}</h2>
      <p>{action.message}</p>
      {action.requireTyped && <input className="modal-confirm-input" value={typed} onChange={e => setTyped(e.target.value)} placeholder="Type DELETE to confirm" autoFocus />}
      <div className="modal-actions">
        <button className="modal-cancel" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="modal-danger" onClick={onConfirm} disabled={disabled}>{busy ? 'Working...' : action.confirmLabel}</button>
      </div>
    </div>
  </div>
}

function App() {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [job, setJob] = useState(null)
  const [companies, setCompanies] = useState([])
  const [industries, setIndustries] = useState([])
  const [candidateCount, setCandidateCount] = useState(0)
  const [retryableCount, setRetryableCount] = useState(0)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sort, setSort] = useState('name')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmAction, setConfirmAction] = useState(null)
  const inputRef = useRef(null)

  const refreshCompanies = async () => {
    try {
      const data = await api('/companies')
      setCompanies(data.companies)
      setIndustries(data.industries)
      setCandidateCount(data.candidate_count || 0)
      setRetryableCount(data.retryable_observation_count || 0)
    } catch (err) { setError(err.message) }
  }

  useEffect(() => { refreshCompanies() }, [])
  useEffect(() => {
    if (!job?.id || ['completed', 'failed'].includes(job.status)) return
    const timer = setInterval(async () => {
      try {
        const next = await api(`/jobs/${job.id}/status`)
        setJob(next)
        await refreshCompanies()
      } catch (err) { setError(err.message) }
    }, 2000)
    return () => clearInterval(timer)
  }, [job?.id, job?.status])

  const chooseFile = async (selected) => {
    if (!selected) return
    setFile(selected); setPreview(null); setError(''); setBusy(true)
    const body = new FormData(); body.append('file', selected)
    try { setPreview(await api('/uploads/preview', { method: 'POST', body })) }
    catch (err) { setFile(null); setError(err.message) }
    finally { setBusy(false) }
  }

  const processFile = async () => {
    setBusy(true); setError('')
    const body = new FormData(); body.append('file', file)
    try {
      const started = await api('/uploads/process', { method: 'POST', body })
      const current = await api(`/jobs/${started.job_id}/status`)
      setJob(current); setFile(null); setPreview(null); await refreshCompanies()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const rerunPendingBatch = async () => {
    setBusy(true); setError('')
    try {
      const started = await api('/jobs/rerun-pending', { method: 'POST' })
      const current = await api(`/jobs/${started.job_id}/status`)
      setJob(current)
      await refreshCompanies()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const setIndustry = async (id, industry) => {
    try {
      await api(`/companies/${id}/industry`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ industry }),
      })
      await refreshCompanies()
    } catch (err) { setError(err.message) }
  }

  const askDeleteCompany = (company) => setConfirmAction({
    type: 'company',
    id: company.id,
    title: `Delete ${company.display_name}?`,
    message: 'This permanently removes the company, every candidate, and all observations tied to it.',
    confirmLabel: 'Delete company',
  })

  const askDeleteCandidate = (winner) => setConfirmAction({
    type: 'candidate',
    id: winner.id,
    title: `Delete ${winner.name}?`,
    message: 'This permanently removes this candidate and recalculates the company decision without them.',
    confirmLabel: 'Delete candidate',
  })

  const askWipeAll = () => setConfirmAction({
    type: 'wipe-all',
    title: 'Reset workspace?',
    message: 'This permanently removes every job, company, candidate, and observation from the local workspace.',
    confirmLabel: 'Reset workspace',
    requireTyped: true,
  })

  const runConfirmedDelete = async () => {
    if (!confirmAction) return
    setBusy(true); setError('')
    try {
      if (confirmAction.type === 'company') await api(`/companies/${confirmAction.id}`, { method: 'DELETE' })
      if (confirmAction.type === 'candidate') await api(`/candidates/${confirmAction.id}`, { method: 'DELETE' })
      if (confirmAction.type === 'wipe-all') {
        await api('/admin/wipe-all?confirm=DELETE', { method: 'DELETE' })
        setJob(null); setFile(null); setPreview(null)
      }
      await refreshCompanies()
      setConfirmAction(null)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const visible = useMemo(() => {
    const needle = query.toLowerCase()
    const rows = companies.filter(c => c.display_name.toLowerCase().includes(needle) && (statusFilter === 'all' || c.status === statusFilter))
    return [...rows].sort((a, b) => sort === 'rounds' ? b.rounds_completed - a.rounds_completed : sort === 'status' ? a.status.localeCompare(b.status) : a.display_name.localeCompare(b.display_name))
  }, [companies, query, statusFilter, sort])

  const pending = companies.filter(c => c.status === 'needs_next_round').length
  const resolved = companies.filter(c => c.status.startsWith('resolved')).length
  const totalCandidates = candidateCount || preview?.candidate_count || 0
  const progress = job?.total_candidates ? Math.round(job.processed_candidates / job.total_candidates * 100) : job?.status === 'completed' ? 100 : 0

  return <div className="app-shell">
    <header>
      <a className="brand" href="#"><span className="brand-mark"><Sparkles size={18} /></span><span>Signal Desk<small>Decision maker discovery</small></span></a>
      <div className="header-actions"><div className="system"><i /> Local workspace Â· persistent</div><button className="reset-btn" onClick={askWipeAll}><Trash2 size={15}/>Reset workspace</button></div>
    </header>

    <main>
      <section className="hero">
        <div><p className="eyebrow">LINKEDIN SIGNAL INTELLIGENCE</p><h1>Find the right people.<br/><em>Stop when the evidence is strong.</em></h1><p className="lede">Upload scraped results, extract signals with Gemini, and let deterministic scoring do the deciding.</p></div>
        <div className="hero-stats">
          <div><Building2/><strong>{companies.length}</strong><span>Companies tracked</span></div>
          <div><Check/><strong>{resolved}</strong><span>Resolved</span></div>
          <div><Users/><strong>{pending}</strong><span>Need another round</span></div>
        </div>
      </section>

      {error && <div className="error"><span>{error}</span><button onClick={() => setError('')}><X size={16}/></button></div>}

      <section className="workspace-grid">
        <div className="card upload-card">
          <div className="card-heading"><span className="icon-box"><UploadCloud size={20}/></span><div><h2>New scrape round</h2><p>LinkedIn search-result JSON</p></div></div>
          {!preview ? <div className={`dropzone ${busy ? 'busy' : ''}`} onClick={() => !busy && inputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); chooseFile(e.dataTransfer.files[0]) }}>
            <input ref={inputRef} type="file" accept=".json,application/json" hidden onChange={e => chooseFile(e.target.files[0])}/>
            <span className="upload-orbit"><FileJson size={27}/></span>
            <strong>{busy ? 'Reading fileâ€¦' : 'Drop your JSON here'}</strong><p>or click to browse Â· shape is validated before processing</p>
          </div> : <div className="preview">
            <div className="file-row"><span><FileJson size={18}/></span><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB Â· Ready to process</small></div><button onClick={() => { setFile(null); setPreview(null) }}><X size={16}/></button></div>
            <div className="preview-stats"><div><strong>{preview.company_count}</strong><span>companies</span></div><div><strong>{preview.candidate_count}</strong><span>candidates</span></div><div><strong>{preview.roles.length}</strong><span>roles detected</span></div></div>
            <div className="roles">{preview.roles.slice(0, 4).map(role => <span key={role}>{role}</span>)}</div>
            <button className="primary" onClick={processFile} disabled={busy}>{busy ? 'Startingâ€¦' : 'Start signal extraction'} <Sparkles size={16}/></button>
          </div>}
        </div>

        <div className="card progress-card">
          <div className="card-heading"><span className="icon-box violet"><Sparkles size={20}/></span><div><h2>Extraction activity</h2><p>{job ? `Job #${job.id}` : 'Waiting for an upload'}</p></div>{job && <span className={`job-state ${job.status}`}>{job.status}</span>}</div>
          <div className="progress-center"><div className="progress-ring" style={{'--progress': `${progress * 3.6}deg`}}><div><strong>{progress}%</strong><span>complete</span></div></div><div className="activity-copy"><strong>{job?.processed_candidates || 0} <span>/ {job?.total_candidates || 0}</span></strong><p>candidate observations processed</p><div className="rpm"><span>Gemini RPM</span><b>{job?.rpm_usage || 0} / {job?.rpm_limit || 15}</b></div></div></div>
          <div className="mini-metrics"><div><span className="green-dot"/><strong>{job?.companies_resolved ?? resolved}</strong><small>Resolved</small></div><div><span className="amber-dot"/><strong>{retryableCount}</strong><small>Can rerun</small></div><div><span className="red-dot"/><strong>{job?.failed_candidates || 0}</strong><small>Failures</small></div></div>
          <button className="secondary" onClick={rerunPendingBatch} disabled={busy || !retryableCount}>{busy ? 'Starting rerun...' : `Rerun pending batch (${retryableCount})`}</button>
        </div>
      </section>

      <section className="export-grid">
        <a className="export-card amber" href={`${API}/exports/still-needed.csv`}><span><ArrowDownToLine/></span><div><strong>Still-Needed CSV</strong><p>{pending} companies need a next persona</p></div><b>Download</b></a>
        <a className="export-card teal" href={`${API}/exports/final.csv?forced=true`}><span><ArrowDownToLine/></span><div><strong>Final Decision Makers</strong><p>Winners, evidence, scores, and confidence</p></div><b>Download</b></a>
        <a className="export-card violet" href={`${API}/exports/audit.csv`}><span><ArrowDownToLine/></span><div><strong>Full Candidate Audit CSV</strong><p>Every candidate, every score, every Gemini signal - {totalCandidates} included</p></div><b>Download</b></a>
      </section>

      <section className="card table-card">
        <div className="table-title"><div><h2>Company pipeline</h2><p>Every company and its accumulated evidence</p></div><span>{companies.length} total</span></div>
        <div className="table-tools"><label><Search size={17}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search companiesâ€¦"/></label><div className="select-wrap"><select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="all">All statuses</option>{Object.entries(LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><ChevronDown/></div><div className="select-wrap"><select value={sort} onChange={e => setSort(e.target.value)}><option value="name">Sort: Company</option><option value="rounds">Sort: Rounds</option><option value="status">Sort: Status</option></select><ChevronDown/></div></div>
        <div className="table-scroll"><table><thead><tr><th>Company</th><th>Industry</th><th>Status</th><th>Rounds</th><th>Selected decision makers</th><th>Next search</th><th>Actions</th></tr></thead><tbody>
          {visible.map(company => <tr key={company.id}><td><strong>{company.display_name}</strong><small>{company.roles_tried.join(' â†’ ') || 'No roles yet'}</small></td><td><div className="select-wrap compact"><select value={company.industry} onChange={e => setIndustry(company.id, e.target.value)}>{industries.map(i => <option key={i}>{i}</option>)}</select><ChevronDown/></div></td><td><StatusBadge status={company.status}/></td><td><span className="round-pill">{company.rounds_completed}<i>/ 4</i></span></td><td>{company.winners.length ? <div className="winner-list">{company.winners.map(w => <div className="winner-row" key={w.id}><a href={w.url} target="_blank"><span>{w.name.charAt(0)}</span>{w.name}<b>{w.score}</b></a><button className="winner-delete" onClick={() => askDeleteCandidate(w)} title="Delete candidate"><Trash2 size={13}/></button></div>)}</div> : <span className="muted">Awaiting threshold</span>}</td><td>{company.status === 'needs_next_round' ? <span className="next-role">{company.next_role || 'No persona remaining'}</span> : <span className="muted">â€”</span>}</td><td><button className="row-delete" onClick={() => askDeleteCompany(company)} title="Delete company"><Trash2 size={15}/></button></td></tr>)}
          {!visible.length && <tr><td colSpan="7" className="empty">No companies match this view.</td></tr>}
        </tbody></table></div>
      </section>
    </main>
    <ConfirmDialog action={confirmAction} busy={busy} onCancel={() => setConfirmAction(null)} onConfirm={runConfirmedDelete} />
    <footer>Signal Desk <span>Â·</span> Scores are deterministic. Gemini extracts evidence only.</footer>
  </div>
}

export default App
