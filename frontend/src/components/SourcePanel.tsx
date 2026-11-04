import { useEffect, useState } from 'react'
import { Download, FileCode2, Package } from 'lucide-react'
import { getToken } from '../api'
import { apiPath } from '../paths'
import type { Project } from '../types'

export function SourcePanel({ project }: { project: Project }) {
  const files = project.artifacts.filter(artifact => artifact.version === project.current_version && !artifact.path.endsWith('.md'))
  const [selected, setSelected] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (files.length && !files.some(file => file.path === selected)) setSelected(files[0].path)
  }, [project.current_version])
  const current = files.find(file => file.path === selected) || files[0]
  const download = async () => {
    setDownloading(true); setError('')
    try {
      const response = await fetch(apiPath(`/projects/${project.id}/package?version=${project.current_version}`), {
        headers: { Authorization: `Bearer ${getToken() || ''}` },
      })
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Package download failed.')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url; link.download = `forma-${project.id.slice(0, 8)}-v${project.current_version}.zip`
      document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setDownloading(false) }
  }
  return <div className="source-view"><header><div><span className="eyebrow">VERSIONED PROJECT SOURCE</span><h2>{project.source_format === 'multi-file' ? 'Application package' : 'Application source'}</h2><p>{project.source_format === 'multi-file' ? 'React source, production build, and backend modules in one versioned folder.' : 'A portable single-file application artifact.'}</p></div>{project.source_format === 'multi-file' && <button className="button secondary" onClick={download} disabled={downloading}><Download size={15} />{downloading ? 'Downloading…' : 'Download package'}</button>}</header>
    {error && <div className="form-error" role="alert">{error}</div>}
    {current ? <div className="source-layout"><nav>{files.map(file => <button key={file.path} className={current.path === file.path ? 'active' : ''} onClick={() => setSelected(file.path)}><FileCode2 size={14} /><span>{file.path}</span></button>)}</nav><section><header><Package size={14} /><span>{current.path}</span><small>v{current.version}</small></header><pre><code>{current.content}</code></pre></section></div> : <div className="empty-state"><Package size={28} /><h3>Source appears after the first build</h3><p>The generated project files will be available here.</p></div>}
  </div>
}
