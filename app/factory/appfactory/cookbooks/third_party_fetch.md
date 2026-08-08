# Third-party public APIs (PROVEN pattern — module + require-inside-handler)
```js
// pb/pb_hooks/source.js  (module: its own scope IS visible internally)
const BASE = 'https://api.example-provider.com/v1';   // literal → recorded as egress
function fetchAll(app) {
  const res = $http.send({ url: BASE + '/endpoint?param=1', method: 'GET', timeout: 20 });
  if (res.statusCode !== 200) throw new Error('source returned HTTP ' + res.statusCode);
  const data = res.json;                               // ONLY correct accessor
  // store via app.save(...); return what you stored
}
module.exports = { fetchAll };

// pb/pb_hooks/ops.pb.js
routerAdd('POST', '/api/ops/refresh', (e) => {
  const src = require(`${__hooks}/source.js`);
  try { return e.json(200, { updated: src.fetchAll(e.app).length }); }
  catch (err) { console.error('refresh failed:', err); return e.json(502, { error: String(err) }); }
});
cronAdd('sync', '*/15 * * * *', () => {
  const src = require(`${__hooks}/source.js`);
  try { src.fetchAll($app); } catch (err) { console.error('sync failed:', err); }
});
```
RESEARCH the provider's real endpoint/params first (never from memory); an
unreachable source = clean error + honest empty state, NEVER generated data.
