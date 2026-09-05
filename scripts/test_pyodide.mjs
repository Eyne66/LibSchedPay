// Exercise the exact Python files and WebAssembly engine shipped to browsers.
import {loadPyodide} from '../dist/vendor/pyodide/pyodide.mjs';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const py = await loadPyodide({indexURL: path.join(root, 'dist/vendor/pyodide/')});
py.FS.mkdirTree('/app/src/book_workbench');
py.FS.mkdirTree('/app/tests');
py.FS.mkdirTree('/app/tests/fixtures');
py.FS.writeFile('/app/tests/fixtures/schedule_fairness.json', fs.readFileSync(path.join(root, 'tests/fixtures/schedule_fairness.json')));
for (const name of fs.readdirSync(path.join(root, 'dist/python/book_workbench'))) {
  if (name.endsWith('.py')) py.FS.writeFile(`/app/src/book_workbench/${name}`, fs.readFileSync(path.join(root, 'dist/python/book_workbench', name)));
}
for (const name of ['test_settlement.py', 'test_web_regressions.py', 'test_schedule_balance.py']) {
  py.FS.writeFile(`/app/tests/${name}`, fs.readFileSync(path.join(root, 'tests', name)));
}
const passed = py.runPython(`
import sys, unittest
sys.path.insert(0, '/app/src')
sys.path.insert(0, '/app/tests')
suite = unittest.defaultTestLoader.discover('/app/tests')
result = unittest.TextTestRunner(verbosity=1).run(suite)
result.wasSuccessful()
`);
if (!passed) throw new Error('Browser Python runtime regression failed');
console.log('Browser Python runtime: deterministic scheduling, imports, decimal settlement and XLSX round trips passed.');
