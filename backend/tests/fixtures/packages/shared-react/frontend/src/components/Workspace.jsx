export default function Workspace({ items, title, onTitle, onAdd, onRefresh }) {
  return <section><form onSubmit={onAdd}><label>Item title<input value={title} onChange={event => onTitle(event.target.value)} required /></label><button>Add item</button></form><button onClick={onRefresh}>Refresh items</button><ul>{items.map(item => <li key={item.id}>{item.title}</li>)}</ul></section>
}
