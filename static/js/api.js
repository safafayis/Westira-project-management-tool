/**
 * ABC — Central API Helper
 *
 * Provides consistent fetch logic for JSON API calls.
 * All requests use same-origin cookies for authentication.
 * Error handling: non-2xx responses throw { ok:false, error, status, data }.
 */
var API = (function () {
  'use strict';

  function buildHeaders(opts) {
    var h = { 'Content-Type': 'application/json' };
    if (opts && opts.headers) {
      Object.keys(opts.headers).forEach(function (k) { h[k] = opts.headers[k]; });
    }
    return h;
  }

  function parseResponse(response) {
    var contentType = response.headers.get('content-type') || '';
    if (contentType.indexOf('application/json') === -1) {
      if (response.ok) return { ok: true, status: response.status, data: null };
      return { ok: false, status: response.status, error: 'Unexpected response format.', data: null };
    }
    return response.json().then(function (data) {
      return { ok: response.ok, status: response.status, data: data };
    });
  }

  function handleAuthRedirect(result) {
    if (result.status === 401 && typeof window !== 'undefined') {
      var path = window.location.pathname;
      if (path !== '/login' && path !== '/register') {
        window.location.href = '/login';
      }
    }
    return result;
  }

  function request(method, url, body, opts) {
    opts = opts || {};
    var fetchOpts = {
      method: method,
      headers: buildHeaders(opts),
      credentials: 'same-origin',
    };
    if (body !== undefined && body !== null && method !== 'GET' && method !== 'HEAD') {
      fetchOpts.body = typeof body === 'string' ? body : JSON.stringify(body);
    }
    return fetch(url, fetchOpts)
      .then(parseResponse)
      .then(handleAuthRedirect);
  }

  return {
    get: function (url, opts) {
      return request('GET', url, null, opts);
    },
    post: function (url, data, opts) {
      return request('POST', url, data, opts);
    },
    put: function (url, data, opts) {
      return request('PUT', url, data, opts);
    },
    patch: function (url, data, opts) {
      return request('PATCH', url, data, opts);
    },
    del: function (url, data, opts) {
      return request('DELETE', url, data || null, opts);
    },
  };
})();

if (typeof window !== 'undefined') {
  window.API = API;
}
