import { useEffect, useState } from 'react'
import { Download, FileCode2, Package } from 'lucide-react'
import { getToken } from '../api'
import type { Project } from '../types'

export function SourcePanel({ project }: { project: Project }) {
  const files = project.artifacts.filter(artifact => artifact.version === project.current_version && !artifact.path.endsWith('.md'))
  const [selected, setSelected] = useState('')
  useEffect(() => {
    if (files.length && !files.some(file => file.path === selected)) setSelected(files[0].path)
  }, [project.current_version])
  const current = files.find(file => file.path === selected) || files[0]
  const download = `/api/projects/${project.id}/package?access_token=${encodeURIComponent(getToken() || '')}&version=${project.current_version}`
  return <div className="source-view"><header><div><span className="eyebrow">VERSIONED PROJECT SOURCE</span><h2>{project.source_format === 'multi-file' ? 'Application package' : 'Application source'}</h2><p>{project.source_format === 'multi-file' ? 'React source, production build, and backend modules in one versioned folder.' : 'A portable single-file application artifact.'}</p></div>{project.source_format === 'multi-file' && <a className="button secondary" href={download}><Download size={15} />Download package</a>}</header>
    {current ? <div className="source-layout"><nav>{files.map(file => <button key={file.path} className={current.path === file.path ? 'active' : ''} onClick={() => setSelected(file.path)}><FileCode2 size={14} /><span>{file.path}</span></button>)}</nav><section><header><Package size={14} /><span>{current.path}</span><small>v{current.version}</small></header><pre><code>{current.content}</code></pre></section></div> : <div className="empty-state"><Package size={28} /><h3>Source appears after the first build</h3><p>The generated project files will be available here.</p></div>}
  </div>
}
