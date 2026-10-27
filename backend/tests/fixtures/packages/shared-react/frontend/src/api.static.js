const read = () => JSON.parse(localStorage.getItem('fixture-items') || '[]')
const write = items => localStorage.setItem('fixture-items', JSON.stringify(items))

export const listItems = async () => read()
export const createItem = async title => {
  const items = read()
  const item = { id: Date.now(), title }
  write([...items, item])
  return item
}
