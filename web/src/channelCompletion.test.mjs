import test from 'node:test';
import assert from 'node:assert/strict';
import { mentionQuery, commandQuery, rebaseMentions, selectedMentionIds, hasCommandPlaceholders } from './channelCompletion.ts';

test('mention completion follows caret and supports spaced names', () => {
  assert.deepEqual(mentionQuery('请 @Hermes Agent 看一下', 15), {start:2,end:15,query:'hermes agent'});
  assert.equal(mentionQuery('name@example.com', 16), null);
});
test('commands stop completing once arguments start', () => {
  assert.equal(commandQuery('/'), '');
  assert.equal(commandQuery('/plat'), '');
  assert.equal(commandQuery('/platform 健康'), '健康');
  assert.equal(commandQuery('/platform AGENT_DRAIN node1 '), null);
  assert.equal(commandQuery('/please'), null);
});
test('same-name mentions preserve only selected principal and reject revoked members', () => {
  const m = [{start:0,end:4,label:'@Sam',principalId:'sam-2'}];
  assert.deepEqual(selectedMentionIds('@Sam hi', m, new Set(['sam-1','sam-2'])), ['sam-2']);
  assert.deepEqual(selectedMentionIds('@Sam hi', m, new Set(['sam-1'])), []);
  assert.deepEqual(selectedMentionIds('@Samuel hi', m, new Set(['sam-2'])), []);
});
test('editing mention invalidates identity; editing elsewhere rebases it', () => {
  const m = [{start:3,end:7,label:'@Sam',principalId:'sam-2'}];
  assert.deepEqual(rebaseMentions('Hi @Sam !', 'Hello @Sam !', m), [{...m[0],start:6,end:10}]);
  assert.deepEqual(rebaseMentions('Hi @Sam !', 'Hi @Sarah !', m), []);
});
test('command placeholders are blocked but ordinary text stays valid', () => {
  assert.equal(hasCommandPlaceholders('/platform AGENT_DRAIN <source> <target> [reason]'), true);
  assert.equal(hasCommandPlaceholders('/platform HEALTH_READ'), false);
  assert.equal(hasCommandPlaceholders('Explain <source>'), false);
});
test('deleting one of identical names never transfers identity to its twin', () => {
  const m=[{start:0,end:4,label:'@Sam',principalId:'sam-1'},{start:5,end:9,label:'@Sam',principalId:'sam-2'}];
  assert.deepEqual(rebaseMentions('@Sam @Sam ', '@Sam ', m), []);
});
