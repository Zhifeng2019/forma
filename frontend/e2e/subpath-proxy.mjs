// Test-only equivalent of Nginx's /forma/ prefix-stripping proxy.
import http from 'node:http'

const backendPort = Number(process.env.FORMA_TEST_BACKEND_PORT || 8129)
const proxyPort = Number(process.env.FORMA_TEST_PROXY_PORT || 8130)
http.createServer((request, response) => {
  if (request.url === '/forma') {
    response.writeHead(308, { Location: '/forma/' }).end()
    return
  }
  if (!request.url.startsWith('/forma/')) {
    response.writeHead(404).end('Reserved for another application')
    return
  }
  const upstream = http.request({
    hostname: '127.0.0.1', port: backendPort, method: request.method,
    path: request.url.slice('/forma'.length), headers: request.headers,
  }, incoming => {
    response.writeHead(incoming.statusCode, incoming.headers)
    incoming.pipe(response)
  })
  upstream.on('error', () => {
    if (!response.headersSent) response.writeHead(502)
    response.end()
  })
  response.on('close', () => upstream.destroy())
  request.pipe(upstream)
}).listen(proxyPort, '127.0.0.1')
