const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

for (const prefix of ['/', '/LibSchedPay/']) {
  test(`backend starts its worker under ${prefix}`, async () => {
    let workerAddress;
    const context = vm.createContext({
      URL, setTimeout, clearTimeout,
      document: {
        currentScript: {src: `https://example.test${prefix}static/browser_backend.js`},
        getElementById: () => null,
      },
      window: {addEventListener() {}},
      Worker: class {
        constructor(address) {workerAddress = String(address);}
        postMessage(message) {
          this.onmessage({data: {id: message.id, result: {ok: true, remote_mode: true}}});
        }
      },
    });
    vm.runInContext(fs.readFileSync('workbench/static/browser_backend.js', 'utf8'), context);
    const response = await context.window.workbenchBackend.request('/api/health');
    assert.equal(response.ok, true);
    assert.equal(workerAddress, `https://example.test${prefix}static/browser_worker.mjs`);
  });
}
