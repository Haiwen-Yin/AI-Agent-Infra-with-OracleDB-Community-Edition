import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { statusLabels, statusLabel } from './statusLabels.ts';

const zh = (zh, en) => zh;
const en = (zh, en) => en;
test('graph capability values follow language without changing API codes', () => {
  for (const [code, chinese] of Object.entries({ENABLED:'已启用', CONTROLLED:'受控启用', DISABLED:'已禁用', UNAVAILABLE:'不可用'})) {
    assert.equal(statusLabel(code.toLowerCase(), zh), chinese);
    assert.equal(statusLabel(' ' + code + ' ', en), statusLabels[code][1]);
  }
  assert.equal(statusLabel('future-state', zh), 'future-state');
  assert.equal(statusLabel(null, zh), '-');
});
test('database constrained status and state values have Chinese display labels', () => {
  const dir = new URL('../../../adapters/pg/deploy/', import.meta.url);
  const values = new Set();
  for (const file of fs.readdirSync(dir).filter(name => name.endsWith('.sql'))) {
    const sql = fs.readFileSync(new URL(file, dir), 'utf8');
    for (const match of sql.matchAll(/\b(?:[a-z_]*status|[a-z_]*state)\s+IN\s*\(([^)]+)\)/gi))
      for (const token of match[1].matchAll(/'([A-Z_]+)'/g)) values.add(token[1]);
  }
  for (const value of values)
    assert.match(statusLabel(value, zh), /[\u3400-\u9fff]/, value);
});
