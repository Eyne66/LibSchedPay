# Third-party browser runtime

LibSchedPay uses the unmodified **Pyodide 0.27.7** runtime to run its existing
Python modules in the browser. Business inputs do not go to the download host.

- Upstream source: https://github.com/pyodide/pyodide/tree/0.27.7
- Distribution: https://cdn.jsdelivr.net/pyodide/v0.27.7/full/
- Pyodide license: Mozilla Public License 2.0, reproduced at
  `dist/vendor/pyodide/LICENSE` by the setup script.
- Python and the bundled standard library remain subject to their upstream
  licenses: https://docs.python.org/3.12/license.html

`pyodide-runtime.lock.json` records the exact version, download URLs, byte sizes
and SHA-256 checksums. The setup script verifies all downloaded files. Preserve
the runtime's license and this notice when distributing the generated site.

This notice describes third-party components. It does not select a license for
the LibSchedPay application source.
