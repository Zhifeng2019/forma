export const listItems = async () => (await Forma.api('/items')).items
export const createItem = title => Forma.api('/items', { method: 'POST', body: JSON.stringify({ title }) })
