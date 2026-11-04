// Vite supplies '/' locally, or the --base path used for the production build.
export const studioPath = (path = '') => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`
export const apiPath = (path: string) => studioPath(`api/${path.replace(/^\/+/, '')}`)
