/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM MODULE — managed by tooling, never edited by agents (spec P1).
 * CraftBot host bridge helpers. Require inside route handlers:
 *
 *   const bridge = require(`${__hooks}/_craftbot_bridge.js`);
 *   const text = bridge.callLLM('Summarize: ...', 'You are terse.');
 *   const res = bridge.callIntegration('slack', 'POST', '/chat.postMessage', { ... });
 *
 * Both no-op gracefully when the app runs outside CraftBot (env vars unset).
 */

function callLLM(prompt, systemMessage) {
  try {
    const bridge = $os.getenv('CRAFTBOT_BRIDGE_URL');
    const token = $os.getenv('CRAFTBOT_BRIDGE_TOKEN');
    if (!bridge || !token) return '';
    const res = $http.send({
      url: bridge + '/api/bridge/llm',
      method: 'POST',
      body: JSON.stringify({ prompt: prompt, system_message: systemMessage || '' }),
      headers: {
        'content-type': 'application/json',
        authorization: 'Bearer ' + token,
      },
      timeout: 120,
    });
    return (res.json && res.json.content) || '';
  } catch {
    return '';
  }
}

function callIntegration(integration, method, url, body, headers) {
  try {
    const bridge = $os.getenv('CRAFTBOT_BRIDGE_URL');
    const token = $os.getenv('CRAFTBOT_BRIDGE_TOKEN');
    if (!bridge || !token) {
      return { status: 503, error: 'CraftBot integration bridge is unavailable' };
    }
    const res = $http.send({
      url: bridge + '/api/integrations/proxy',
      method: 'POST',
      body: JSON.stringify({
        integration: integration,
        method: method,
        url: url,
        body: body || null,
        headers: headers || {},
      }),
      headers: {
        'content-type': 'application/json',
        authorization: 'Bearer ' + token,
      },
      timeout: 120,
    });
    const out = res.json || { error: 'Empty bridge response' };
    if (out.status === undefined) out.status = res.statusCode || 502;
    return out;
  } catch (err) {
    return { status: 502, error: String(err) };
  }
}

module.exports = {
  callLLM: callLLM,
  callIntegration: callIntegration,
};
