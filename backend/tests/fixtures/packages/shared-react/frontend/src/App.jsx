import React, { useEffect, useState } from 'react'
import Workspace from './components/Workspace.jsx'
import { createItem, listItems } from './api.js'

export default function App() {
  const [items, setItems] = useState([])
  const [title, setTitle] = useState('')
  const refresh = async () => setItems(await listItems())
  useEffect(() => { void refresh() }, [])
  const addItem = async event => {
    event.preventDefault()
    if (!title.trim()) return
    await createItem(title.trim())
    setTitle('')
    await refresh()
  }
  return <main><h1>React fixture</h1><Workspace items={items} title={title} onTitle={setTitle} onAdd={addItem} onRefresh={refresh} /></main>
}
