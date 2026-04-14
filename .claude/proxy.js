const http = require('http');
const port = process.env.PORT || 3100;

const server = http.createServer((req, res) => {
  const options = {
    hostname: 'localhost',
    port: 3000,
    path: req.url,
    method: req.method,
    headers: req.headers,
  };
  const proxy = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });
  proxy.on('error', (e) => {
    res.writeHead(502);
    res.end('Proxy error: ' + e.message);
  });
  req.pipe(proxy, { end: true });
});

server.listen(port, () => console.log(`Proxy listening on port ${port}`));
