import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ArrowDownToLine, Building2, Check, ChevronDown, FileJson, FileSpreadsheet, Globe, LayoutGrid, MapPin, Phone, Search, Sparkles, Trash2, UploadCloud, Users, UsersRound, X } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
const LABELS = {
  resolved_90: 'Resolved · 90+',
  resolved_85_fallback: 'Resolved · fallback',
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

// ─── India tab result banner ───────────────────────────────────────────────
function IndiaResultBanner({ result, label }) {
  if (!result) return null
  const matchedCount = result.matched_count ?? result.matched?.length ?? 0
  const fuzzyCount = result.fuzzy_match_count ?? result.fuzzy_matches?.length ?? 0
  const alreadyFilledCount = result.already_filled_count ?? result.already_filled?.length ?? 0
  const rejectedPhoneCount = result.rejected_phone_count ?? result.rejected_phone?.length ?? 0
  const rejectedCountryCount = result.rejected_country_count ?? result.rejected_country?.length ?? 0
  const unmatchedCount = result.unmatched_count ?? result.unmatched?.length ?? 0
  const fuzzyList = result.fuzzy_matches ?? []
  const rejectedCountryList = result.rejected_country_details ?? result.rejected_country ?? []
  const totalRecords = result.total_records
  const skippedEmpty = result.skipped_empty_count

  return <div className="india-result">
    {totalRecords !== undefined && <div className="india-result-row india-result-total">
      <span>Records in file</span><strong>{totalRecords}</strong>
    </div>}
    {result.created_count !== undefined && <div className="india-result-row"><span>New companies</span><strong>{result.created_count}</strong></div>}
    {result.updated_count !== undefined && <div className="india-result-row"><span>Updated companies</span><strong>{result.updated_count}</strong></div>}
    {totalRecords !== undefined && <div className="india-result-row india-result-done"><span>Matched (phone saved)</span><strong>{matchedCount}</strong></div>}
    {fuzzyCount > 0 && <div className="india-result-row india-result-fuzzy"><span>Fuzzy matched (check these)</span><strong>{fuzzyCount}</strong></div>}
    {totalRecords !== undefined && <div className="india-result-row"><span>Already had phone</span><strong>{alreadyFilledCount}</strong></div>}
    {totalRecords !== undefined && <div className="india-result-row"><span>Invalid / no phone</span><strong>{rejectedPhoneCount}</strong></div>}
    {rejectedCountryCount > 0 && <div className="india-result-row"><span>Non-India results</span><strong>{rejectedCountryCount}</strong></div>}
    {totalRecords !== undefined && <div className="india-result-row india-result-left"><span>No company match — still left</span><strong>{unmatchedCount}</strong></div>}
    {skippedEmpty > 0 && <div className="india-result-row india-result-warning-row"><span>Skipped (no company name found)</span><strong>{skippedEmpty}</strong></div>}
    {fuzzyList.length > 0 && <div className="india-result-fuzzy-list">
      {fuzzyList.map((f, i) => <p key={i}><span className="fuzzy-scraped">{f.scraped_name}</span><span className="fuzzy-arrow">→</span><span className="fuzzy-matched">{f.matched_to}</span></p>)}
    </div>}
    {rejectedCountryList.length > 0 && <p className="india-result-warning">Non-India: {rejectedCountryList.map(r => r.company).join(', ')}</p>}
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
  const [domainBusy, setDomainBusy] = useState(false)
  const [domainResult, setDomainResult] = useState(null)
  const [supplierTypesBusy, setSupplierTypesBusy] = useState(false)
  const [supplierTypesResult, setSupplierTypesResult] = useState(null)
  const [activeTab, setActiveTab] = useState('pipeline')
  const [opportunityFile, setOpportunityFile] = useState(null)
  const [opportunityBusy, setOpportunityBusy] = useState(false)
  const [opportunityResult, setOpportunityResult] = useState(null)
  const [peopleFile, setPeopleFile] = useState(null)
  const [mergeBusy, setMergeBusy] = useState(false)

  // ── India tab state ──────────────────────────────────────────────────────
  const [indiaStats, setIndiaStats] = useState(null)
  const [indiaRefreshBusy, setIndiaRefreshBusy] = useState(false)
  const [indiaOppBusy, setIndiaOppBusy] = useState(false)
  const [indiaOppResult, setIndiaOppResult] = useState(null)
  const [indiaOppFile, setIndiaOppFile] = useState(null)
  const [indiaMartBusy, setIndiaMartBusy] = useState(false)
  const [indiaMartResult, setIndiaMartResult] = useState(false)
  const [serperBusy, setSerperBusy] = useState(false)
  const [serperResult, setSerperResult] = useState(null)

  const inputRef = useRef(null)
  const domainInputRef = useRef(null)
  const supplierTypesInputRef = useRef(null)
  const opportunityInputRef = useRef(null)
  const peopleInputRef = useRef(null)
  const indiaOppInputRef = useRef(null)
  const indiaMartInputRef = useRef(null)
  const serperInputRef = useRef(null)

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

  const uploadDomains = async (selected) => {
    if (!selected) return
    setDomainBusy(true); setError(''); setDomainResult(null)
    const body = new FormData(); body.append('file', selected)
    try {
      const result = await api('/uploads/domains', { method: 'POST', body })
      setDomainResult(result)
      await refreshCompanies()
    } catch (err) { setError(err.message) }
    finally { setDomainBusy(false) }
  }

  const uploadSupplierTypes = async (selected) => {
    if (!selected) return
    setSupplierTypesBusy(true); setError(''); setSupplierTypesResult(null)
    const body = new FormData(); body.append('file', selected)
    try {
      const result = await api('/uploads/supplier-types', { method: 'POST', body })
      setSupplierTypesResult(result)
      await refreshCompanies()
    } catch (err) { setError(err.message) }
    finally { setSupplierTypesBusy(false) }
  }

  const uploadOpportunities = async (selected) => {
    if (!selected) return
    setOpportunityFile(selected); setOpportunityBusy(true); setError(''); setOpportunityResult(null)
    const body = new FormData(); body.append('file', selected)
    try {
      const result = await api('/uploads/opportunities', { method: 'POST', body })
      setOpportunityResult(result)
      await refreshCompanies()
    } catch (err) { setError(err.message); setOpportunityFile(null) }
    finally { setOpportunityBusy(false) }
  }

  const choosePeopleFile = (selected) => {
    if (!selected) return
    setPeopleFile(selected); setError('')
  }

  const downloadMerged = async () => {
    if (!peopleFile) return
    setMergeBusy(true); setError('')
    const body = new FormData(); body.append('file', peopleFile)
    try {
      const response = await fetch(`${API}/exports/merged.csv`, { method: 'POST', body })
      if (!response.ok) {
        let detail = 'Something went wrong'
        try { detail = (await response.json()).detail || detail } catch {}
        throw new Error(detail)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = 'merged-operational.csv'
      document.body.appendChild(link); link.click(); link.remove()
      URL.revokeObjectURL(url)
    } catch (err) { setError(err.message) }
    finally { setMergeBusy(false) }
  }

  // ── India handlers ───────────────────────────────────────────────────────
  const uploadIndiaOpportunities = async (selected) => {
    if (!selected) return
    setIndiaOppFile(selected); setIndiaOppBusy(true); setError(''); setIndiaOppResult(null)
    const body = new FormData(); body.append('file', selected)
    try {
      const result = await api('/india/uploads/opportunities', { method: 'POST', body })
      setIndiaOppResult(result)
      await refreshIndiaStats()
    } catch (err) { setError(err.message); setIndiaOppFile(null) }
    finally { setIndiaOppBusy(false) }
  }

  const uploadIndiaMart = async (selected) => {
    if (!selected) return
    setIndiaMartBusy(true); setError(''); setIndiaMartResult(null)
    const body = new FormData(); body.append('file', selected)
    try {
      const result = await api('/india/uploads/indiamart-phones', { method: 'POST', body })
      setIndiaMartResult(result)
      await refreshIndiaStats()
    } catch (err) { setError(err.message) }
    finally { setIndiaMartBusy(false) }
  }

  const uploadSerper = async (selected) => {
    if (!selected) return
    setSerperBusy(true); setError(''); setSerperResult(null)
    const body = new FormData(); body.append('file', selected)
    try {
      const result = await api('/india/uploads/serper-phones', { method: 'POST', body })
      setSerperResult(result)
      await refreshIndiaStats()
    } catch (err) { setError(err.message) }
    finally { setSerperBusy(false) }
  }

  const refreshIndiaStats = async () => {
    setIndiaRefreshBusy(true)
    try {
      const stats = await api('/india/stats')
      setIndiaStats(stats)
    } catch (err) { setError(err.message) }
    finally { setIndiaRefreshBusy(false) }
  }

  const downloadIndiaStillNeeded = async () => {
    try {
      const response = await fetch(`${API}/india/exports/still-needed-phones.csv?_=${Date.now()}`)
      if (!response.ok) throw new Error('Download failed')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = 'india-still-needed-phones.csv'
      document.body.appendChild(link); link.click(); link.remove()
      URL.revokeObjectURL(url)
    } catch (err) { setError(err.message) }
  }

  const downloadIndiaPipeline = async () => {
    try {
      const response = await fetch(`${API}/india/exports/india-pipeline.csv?_=${Date.now()}`)
      if (!response.ok) throw new Error('Download failed')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = 'india-pipeline.csv'
      document.body.appendChild(link); link.click(); link.remove()
      URL.revokeObjectURL(url)
    } catch (err) { setError(err.message) }
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

  const askWipeIndia = () => setConfirmAction({
    type: 'wipe-india',
    title: 'Reset India pipeline?',
    message: 'This permanently deletes all India companies and every phone number collected so far. You will need to re-upload the opportunity CSV and re-run the phone enrichment steps.',
    confirmLabel: 'Reset India pipeline',
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
      if (confirmAction.type === 'wipe-india') {
        await api('/india/wipe?confirm=DELETE', { method: 'DELETE' })
        setIndiaOppResult(null); setIndiaMartResult(null); setSerperResult(null)
        setIndiaStats({ total_companies: 0, indiamart_phones: 0, serper_phones: 0 })
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
      <div className="tab-bar">
        <button className={activeTab === 'pipeline' ? 'active' : ''} onClick={() => setActiveTab('pipeline')}><LayoutGrid size={15}/>Pipeline</button>
        <button className={activeTab === 'merge' ? 'active' : ''} onClick={() => setActiveTab('merge')}><UsersRound size={15}/>Merge & Export</button>
        <button className={activeTab === 'india' ? 'active' : ''} onClick={() => setActiveTab('india')}><MapPin size={15}/>India Pipeline</button>
      </div>
      <div className="header-actions"><div className="system"><i /> Local workspace · persistent</div><button className="reset-btn" onClick={askWipeAll}><Trash2 size={15}/>Reset workspace</button></div>
    </header>

    {activeTab === 'pipeline' && <main>
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
            <strong>{busy ? 'Reading file…' : 'Drop your JSON here'}</strong><p>or click to browse · shape is validated before processing</p>
          </div> : <div className="preview">
            <div className="file-row"><span><FileJson size={18}/></span><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB · Ready to process</small></div><button onClick={() => { setFile(null); setPreview(null) }}><X size={16}/></button></div>
            <div className="preview-stats"><div><strong>{preview.company_count}</strong><span>companies</span></div><div><strong>{preview.candidate_count}</strong><span>candidates</span></div><div><strong>{preview.roles.length}</strong><span>roles detected</span></div></div>
            <div className="roles">{preview.roles.slice(0, 4).map(role => <span key={role}>{role}</span>)}</div>
            <button className="primary" onClick={processFile} disabled={busy}>{busy ? 'Starting…' : 'Start signal extraction'} <Sparkles size={16}/></button>
          </div>}
        </div>

        <div className="card progress-card">
          <div className="card-heading"><span className="icon-box violet"><Sparkles size={20}/></span><div><h2>Extraction activity</h2><p>{job ? `Job #${job.id}` : 'Waiting for an upload'}</p></div>{job && <span className={`job-state ${job.status}`}>{job.status}</span>}</div>
          <div className="progress-center"><div className="progress-ring" style={{'--progress': `${progress * 3.6}deg`}}><div><strong>{progress}%</strong><span>complete</span></div></div><div className="activity-copy"><strong>{job?.processed_candidates || 0} <span>/ {job?.total_candidates || 0}</span></strong><p>candidate observations processed</p><div className="rpm"><span>Gemini RPM</span><b>{job?.rpm_usage || 0} / {job?.rpm_limit || 15}</b></div></div></div>
          <div className="mini-metrics"><div><span className="green-dot"/><strong>{job?.companies_resolved ?? resolved}</strong><small>Resolved</small></div><div><span className="amber-dot"/><strong>{retryableCount}</strong><small>Can rerun</small></div><div><span className="red-dot"/><strong>{job?.failed_candidates || 0}</strong><small>Failures</small></div></div>
          <button className="secondary" onClick={rerunPendingBatch} disabled={busy || !retryableCount}>{busy ? 'Starting rerun...' : `Rerun pending batch (${retryableCount})`}</button>
        </div>

        <div className="card upload-card">
          <div className="card-heading"><span className="icon-box amber"><Globe size={20}/></span><div><h2>Company domains</h2><p>{`{company_name, domain}`} JSON</p></div></div>
          <div className={`dropzone compact ${domainBusy ? 'busy' : ''}`} onClick={() => !domainBusy && domainInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadDomains(e.dataTransfer.files[0]) }}>
            <input ref={domainInputRef} type="file" accept=".json,application/json" hidden onChange={e => { uploadDomains(e.target.files[0]); e.target.value = '' }}/>
            <span className="upload-orbit"><Globe size={22}/></span>
            <strong>{domainBusy ? 'Matching companies…' : 'Drop domain JSON'}</strong><p>attaches a domain to each matching company</p>
          </div>
          {domainResult && <div className="domain-result">
            <div className="domain-result-row"><span>Matched</span><strong>{domainResult.matched_count}</strong></div>
            <div className="domain-result-row"><span>Unmatched</span><strong>{domainResult.unmatched_count}</strong></div>
            {domainResult.unmatched_company_names.length > 0 && <p className="domain-result-unmatched">No existing company for: {domainResult.unmatched_company_names.join(', ')}</p>}
          </div>}
        </div>

        <div className="card upload-card">
          <div className="card-heading"><span className="icon-box violet"><FileSpreadsheet size={20}/></span><div><h2>Supplier types</h2><p>Company Name + Supplier Type CSV</p></div></div>
          <div className={`dropzone compact ${supplierTypesBusy ? 'busy' : ''}`} onClick={() => !supplierTypesBusy && supplierTypesInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadSupplierTypes(e.dataTransfer.files[0]) }}>
            <input ref={supplierTypesInputRef} type="file" accept=".csv,text/csv" hidden onChange={e => { uploadSupplierTypes(e.target.files[0]); e.target.value = '' }}/>
            <span className="upload-orbit"><FileSpreadsheet size={22}/></span>
            <strong>{supplierTypesBusy ? 'Setting personas…' : 'Drop supplier-type CSV'}</strong><p>sets round 2's role for companies not yet scraped</p>
          </div>
          {supplierTypesResult && <div className="domain-result">
            <div className="domain-result-row"><span>Updated</span><strong>{supplierTypesResult.updated_count}</strong></div>
            <div className="domain-result-row"><span>Locked (already scraping)</span><strong>{supplierTypesResult.skipped_locked_count}</strong></div>
            <div className="domain-result-row"><span>Unmatched</span><strong>{supplierTypesResult.unmatched_count}</strong></div>
            {supplierTypesResult.unmatched_company_names.length > 0 && <p className="domain-result-unmatched">No existing company for: {supplierTypesResult.unmatched_company_names.join(', ')}</p>}
          </div>}
        </div>
      </section>

      <section className="export-grid">
        <a className="export-card amber" href={`${API}/exports/still-needed.csv`}><span><ArrowDownToLine/></span><div><strong>Still-Needed CSV</strong><p>{pending} companies need a next persona</p></div><b>Download</b></a>
        <a className="export-card teal" href={`${API}/exports/final.csv?forced=true`}><span><ArrowDownToLine/></span><div><strong>Final Decision Makers</strong><p>Winners, evidence, scores, and confidence</p></div><b>Download</b></a>
        <a className="export-card violet" href={`${API}/exports/audit.csv`}><span><ArrowDownToLine/></span><div><strong>Full Candidate Audit CSV</strong><p>Every candidate, every score, every Gemini signal - {totalCandidates} included</p></div><b>Download</b></a>
      </section>

      <section className="card table-card">
        <div className="table-title"><div><h2>Company pipeline</h2><p>Every company and its accumulated evidence</p></div><span>{companies.length} total</span></div>
        <div className="table-tools"><label><Search size={17}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search companies…"/></label><div className="select-wrap"><select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="all">All statuses</option>{Object.entries(LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><ChevronDown/></div><div className="select-wrap"><select value={sort} onChange={e => setSort(e.target.value)}><option value="name">Sort: Company</option><option value="rounds">Sort: Rounds</option><option value="status">Sort: Status</option></select><ChevronDown/></div></div>
        <div className="table-scroll"><table><thead><tr><th>Company</th><th>Domain</th><th>Industry</th><th>Status</th><th>Rounds</th><th>Selected decision makers</th><th>Next search</th><th>Actions</th></tr></thead><tbody>
          {visible.map(company => <tr key={company.id}><td><strong>{company.display_name}</strong><small>{company.roles_tried.join(' → ') || 'No roles yet'}</small></td><td>{company.domain ? <span className="next-role">{company.domain}</span> : <span className="muted">—</span>}</td><td><div className="select-wrap compact"><select value={company.industry} onChange={e => setIndustry(company.id, e.target.value)}>{industries.map(i => <option key={i}>{i}</option>)}</select><ChevronDown/></div></td><td><StatusBadge status={company.status}/></td><td><span className="round-pill">{company.rounds_completed}<i>/ 4</i></span></td><td>{company.winners.length ? <div className="winner-list">{company.winners.map(w => <div className="winner-row" key={w.id}><a href={w.url} target="_blank"><span>{w.name.charAt(0)}</span>{w.name}<b>{w.score}</b></a><button className="winner-delete" onClick={() => askDeleteCandidate(w)} title="Delete candidate"><Trash2 size={13}/></button></div>)}</div> : <span className="muted">Awaiting threshold</span>}</td><td>{company.status === 'needs_next_round' ? <span className="next-role">{company.next_role || 'No persona remaining'}</span> : <span className="muted">—</span>}</td><td><button className="row-delete" onClick={() => askDeleteCompany(company)} title="Delete company"><Trash2 size={15}/></button></td></tr>)}
          {!visible.length && <tr><td colSpan="8" className="empty">No companies match this view.</td></tr>}
        </tbody></table></div>
      </section>
    </main>}

    {activeTab === 'merge' && <main>
      <section className="hero">
        <div><p className="eyebrow">OPPORTUNITY + PEOPLE</p><h1>Bring in leads.<br/><em>Merge them into one workable list.</em></h1><p className="lede">Upload the boss's opportunity-scoring CSV to auto-create companies and set their search persona, then upload a people CSV to produce one final operational export.</p></div>
        <div className="hero-stats">
          <div><Building2/><strong>{opportunityResult ? opportunityResult.created_count + opportunityResult.updated_count : 0}</strong><span>Companies in last upload</span></div>
          <div><Sparkles/><strong>{industries.length}</strong><span>Persona sequences known</span></div>
        </div>
      </section>

      {error && <div className="error"><span>{error}</span><button onClick={() => setError('')}><X size={16}/></button></div>}

      <section className="merge-grid">
        <div className="card upload-card">
          <div className="card-heading"><span className="icon-box violet"><FileSpreadsheet size={20}/></span><div><h2>Opportunity scoring CSV</h2><p>Company Name, Opportunity Score, Supplier Type, ...</p></div></div>
          <div className={`dropzone ${opportunityBusy ? 'busy' : ''}`} onClick={() => !opportunityBusy && opportunityInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadOpportunities(e.dataTransfer.files[0]) }}>
            <input ref={opportunityInputRef} type="file" accept=".csv,text/csv" hidden onChange={e => { uploadOpportunities(e.target.files[0]); e.target.value = '' }}/>
            <span className="upload-orbit"><FileSpreadsheet size={27}/></span>
            <strong>{opportunityBusy ? 'Creating companies…' : 'Drop opportunity CSV'}</strong><p>creates/updates companies · sets persona sequence from Supplier Type</p>
          </div>
          {opportunityResult && <div className="domain-result">
            <div className="domain-result-row"><span>New companies</span><strong>{opportunityResult.created_count}</strong></div>
            <div className="domain-result-row"><span>Updated companies</span><strong>{opportunityResult.updated_count}</strong></div>
          </div>}
        </div>

        <div className="card upload-card">
          <div className="card-heading"><span className="icon-box amber"><Users size={20}/></span><div><h2>People CSV</h2><p>first_name, last_name, company_name, company_url, email, linkedin_url</p></div></div>
          {!peopleFile ? <div className={`dropzone ${mergeBusy ? 'busy' : ''}`} onClick={() => !mergeBusy && peopleInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); choosePeopleFile(e.dataTransfer.files[0]) }}>
            <input ref={peopleInputRef} type="file" accept=".csv,text/csv" hidden onChange={e => choosePeopleFile(e.target.files[0])}/>
            <span className="upload-orbit"><Users size={27}/></span>
            <strong>Drop people CSV</strong><p>matched to companies by name · role &amp; LinkedIn URL come from your winners</p>
          </div> : <div className="preview">
            <div className="file-row"><span><FileSpreadsheet size={18}/></span><div><strong>{peopleFile.name}</strong><small>{(peopleFile.size / 1024).toFixed(1)} KB · Ready to merge</small></div><button onClick={() => setPeopleFile(null)}><X size={16}/></button></div>
            <div className="merge-summary">
              <div className="merge-summary-stats">
                <div><strong>{companies.length}</strong><span>companies known</span></div>
              </div>
            </div>
            <button className="primary" onClick={downloadMerged} disabled={mergeBusy} style={{marginTop: 16}}>{mergeBusy ? 'Merging…' : 'Merge & download CSV'} <ArrowDownToLine size={16}/></button>
          </div>}
        </div>
      </section>
    </main>}

    {activeTab === 'india' && <main>
      <section className="hero">
        <div>
          <p className="eyebrow india-eyebrow">INDIA PHONE PIPELINE</p>
          <h1>Source Indian leads.<br/><em>Verify every number.</em></h1>
          <p className="lede">Upload the India opportunity CSV, enrich with IndiaMart phone numbers, then fill gaps using Serper. Download the final pipeline CSV with verified +91 numbers.</p>
        </div>
        <div className="hero-stats">
          <div><MapPin/><strong>{indiaStats?.total_companies ?? 0}</strong><span>Companies loaded</span></div>
          <div><Phone/><strong>{indiaStats?.indiamart_phones ?? 0}</strong><span>IndiaMart phones</span></div>
          <div><Check/><strong>{indiaStats?.serper_phones ?? 0}</strong><span>Serper phones</span></div>
          <button className="india-refresh-btn" onClick={refreshIndiaStats} disabled={indiaRefreshBusy} title="Refresh counts from database">
            {indiaRefreshBusy ? '…' : '↻'} Refresh
          </button>
          <button className="reset-btn india-reset-btn" onClick={askWipeIndia}><Trash2 size={14}/>Reset India pipeline</button>
        </div>
      </section>

      {error && <div className="error"><span>{error}</span><button onClick={() => setError('')}><X size={16}/></button></div>}

      {/* Step indicators */}
      <div className="india-steps">
        <div className={`india-step ${indiaOppResult ? 'done' : 'active'}`}>
          <span>1</span><div><strong>Upload opportunity CSV</strong><p>India companies with scores</p></div>
        </div>
        <div className="india-step-arrow">→</div>
        <div className={`india-step ${indiaMartResult ? 'done' : indiaOppResult ? 'active' : ''}`}>
          <span>2</span><div><strong>IndiaMart phones</strong><p>Boss uploads IndiaMart JSON</p></div>
        </div>
        <div className="india-step-arrow">→</div>
        <div className={`india-step ${serperResult ? 'done' : indiaMartResult ? 'active' : ''}`}>
          <span>3</span><div><strong>Serper fill-in</strong><p>Fill gaps for missed companies</p></div>
        </div>
        <div className="india-step-arrow">→</div>
        <div className={`india-step ${serperResult ? 'active' : ''}`}>
          <span>4</span><div><strong>Export final CSV</strong><p>All companies + phone numbers</p></div>
        </div>
      </div>

      <section className="india-grid">

        {/* Step 1: Opportunity CSV */}
        <div className="card upload-card">
          <div className="card-heading">
            <span className="icon-box india-green"><FileSpreadsheet size={20}/></span>
            <div><h2>India opportunity CSV</h2><p>Company Name, Score, City, State, Supplier Type, Job Role, AI Insight</p></div>
          </div>
          <div className={`dropzone ${indiaOppBusy ? 'busy' : ''}`} onClick={() => !indiaOppBusy && indiaOppInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadIndiaOpportunities(e.dataTransfer.files[0]) }}>
            <input ref={indiaOppInputRef} type="file" accept=".csv,text/csv" hidden onChange={e => { uploadIndiaOpportunities(e.target.files[0]); e.target.value = '' }}/>
            <span className="upload-orbit india-orbit"><FileSpreadsheet size={27}/></span>
            <strong>{indiaOppBusy ? 'Loading companies…' : 'Drop India opportunity CSV'}</strong>
            <p>same format as the main opportunity CSV</p>
          </div>
          <IndiaResultBanner result={indiaOppResult} />
        </div>

        {/* Step 2: IndiaMart JSON */}
        <div className="card upload-card">
          <div className="card-heading">
            <span className="icon-box india-saffron"><FileJson size={20}/></span>
            <div><h2>IndiaMart phones</h2><p>JSON with company_name + phone_number</p></div>
          </div>
          <div className={`dropzone ${indiaMartBusy ? 'busy' : ''}`} onClick={() => !indiaMartBusy && indiaMartInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadIndiaMart(e.dataTransfer.files[0]) }}>
            <input ref={indiaMartInputRef} type="file" accept=".json,application/json" hidden onChange={e => { uploadIndiaMart(e.target.files[0]); e.target.value = '' }}/>
            <span className="upload-orbit india-saffron-orbit"><FileJson size={27}/></span>
            <strong>{indiaMartBusy ? 'Matching numbers…' : 'Drop IndiaMart JSON'}</strong>
            <p>accepts bare 10-digit or +91-prefixed numbers</p>
          </div>
          <IndiaResultBanner result={indiaMartResult} />
        </div>

      </section>

      {/* Step 2.5: Download still-needed list */}
      <div className="india-midstep">
        <div className="india-midstep-inner">
          <div className="india-midstep-text">
            <Phone size={16}/>
            <div>
              <strong>Download companies still needing a phone</strong>
              <p>Give this list to your boss to run Serper searches for the missing numbers.</p>
            </div>
          </div>
          <button className="india-download-btn" onClick={downloadIndiaStillNeeded}><ArrowDownToLine size={15}/>Download missing list</button>
        </div>
      </div>

      <section className="india-grid">

        {/* Step 3: Serper JSON */}
        <div className="card upload-card">
          <div className="card-heading">
            <span className="icon-box india-blue"><Search size={20}/></span>
            <div><h2>Serper phones</h2><p>JSON with query + phone + country</p></div>
          </div>
          <div className={`dropzone ${serperBusy ? 'busy' : ''}`} onClick={() => !serperBusy && serperInputRef.current.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadSerper(e.dataTransfer.files[0]) }}>
            <input ref={serperInputRef} type="file" accept=".json,application/json" hidden onChange={e => { uploadSerper(e.target.files[0]); e.target.value = '' }}/>
            <span className="upload-orbit india-blue-orbit"><Search size={27}/></span>
            <strong>{serperBusy ? 'Validating numbers…' : 'Drop Serper JSON'}</strong>
            <p>non-India results (US, UK, etc.) are automatically rejected</p>
          </div>
          <IndiaResultBanner result={serperResult} />
        </div>

        {/* Step 4: Final export */}
        <div className="card upload-card india-export-card">
          <div className="card-heading">
            <span className="icon-box india-green"><ArrowDownToLine size={20}/></span>
            <div><h2>Final India pipeline CSV</h2><p>All companies · verified +91 numbers · urgency scores</p></div>
          </div>
          <div className="india-export-body">
            <div className="india-export-cols">
              {['Company name', 'Score', 'Job title', 'Supplier type', 'City', 'State', 'Phone (+91)', 'Contact details', 'AI insight', 'Urgency'].map(col => (
                <span key={col} className="india-col-pill">{col}</span>
              ))}
            </div>
            <p className="india-export-note">Urgency is <strong>High</strong> when score ≥ 80. Phone is blank for companies with no verified number yet.</p>
            <button className="primary india-dl-btn" onClick={downloadIndiaPipeline}><ArrowDownToLine size={16}/>Download India pipeline CSV</button>
          </div>
        </div>

      </section>
    </main>}

    <ConfirmDialog action={confirmAction} busy={busy} onCancel={() => setConfirmAction(null)} onConfirm={runConfirmedDelete} />
    <footer>Signal Desk <span>·</span> Scores are deterministic. Gemini extracts evidence only.</footer>
  </div>
}

export default App
