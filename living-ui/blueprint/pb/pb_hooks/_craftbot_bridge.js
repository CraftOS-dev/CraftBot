/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM MODULE — managed by tooling, never edited by agents (spec P1).
 * CraftBot host bridge helpers. Require inside route handlers:
 *
 *   const bridge = require(`${__hooks}/_craftbot_bridge.js`);
 *   const text = bridge.callLLM('Summarize: ...', 'You are terse.');
 *   const res = bridge.callAction('send_gmail', { to, subject, body });
 *   const raw = bridge.callIntegration('slack', 'POST', '/chat.postMessage', { ... });
 *
 * PREFER callAction: it runs CraftBot's own tested implementation with
 * semantic params — no provider-API knowledge needed. callIntegration is the
 * raw fallback for endpoints no action covers (you must use the provider's
 * real paths/payloads there). All no-op gracefully outside CraftBot.
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

function callAction(actionName, params, options) {
  try {
    const bridge = $os.getenv('CRAFTBOT_BRIDGE_URL');
    const token = $os.getenv('CRAFTBOT_BRIDGE_TOKEN');
    if (!bridge || !token) {
      return { status: 503, error: 'CraftBot integration bridge is unavailable' };
    }
    const res = $http.send({
      url: bridge + '/api/integrations/action',
      method: 'POST',
      body: JSON.stringify({
        action: actionName,
        params: params || {},
        confirm_irreversible: !!(options && options.confirmIrreversible),
        // dryRun: validate everything (grant, params, confirmation) WITHOUT
        // executing — build-time verification of paths that must never fire
        // for real (emails, posts, deletes).
        dry_run: !!(options && options.dryRun),
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
  callAction: callAction,
  callIntegration: callIntegration,
};
