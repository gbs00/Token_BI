import test from 'node:test';
import assert from 'node:assert/strict';
import { visibleMetrics, tier, resetRemaining, lastSuccess, viewModel, updateModel } from '../desktop/model.mjs';

test('quota thresholds apply identically to every window, including 0 and 100', () => {
  assert.deepEqual([0,25,26,50,51,75,76,99,100].map(tier), ['critical','critical','low','low','medium','medium','high','high','high']);
});
test('single window stays single; absent/unknown metrics never become 0%', () => {
  const metrics = [{metric_type:'weekly', remaining_pct:99}, {metric_type:'session',remaining_pct:null}, {metric_type:'other',remaining_pct:50}];
  assert.deepEqual(visibleMetrics(metrics), [metrics[0]]);
  assert.equal(visibleMetrics([{metric_type:'session', remaining_pct:0}]).length, 1);
});
test('known official window duration is supported and values are bounded', () => {
  assert.equal(visibleMetrics([{window_seconds:18000,remaining_pct:101}])[0].remaining_pct, 100);
  assert.equal(visibleMetrics([{window_minutes:10080,remaining_pct:-1}])[0].remaining_pct, 0);
});
test('reset time uses backend deadline and same minute rounding as dashboard', () => {
  const now = Date.parse('2026-09-12T00:00:00Z');
  assert.equal(resetRemaining('2026-09-12T03:38:00Z',now), '3h 38m');
  assert.equal(resetRemaining('2026-09-15T09:00:00Z',now), '3d 9h');
  assert.equal(resetRemaining('2026-09-11T03:00:00Z',now), '即将重置');
  assert.equal(resetRemaining(null,now), null);
});
test('last success does not advance to last attempt time', () => {
  const now = Date.parse('2026-09-12T00:12:00Z');
  assert.equal(lastSuccess({last_success_at:'2026-09-12T00:00:00Z', last_attempt_at:new Date(now).toISOString()}, now), '12 分钟前更新');
});
test('paused access hides cached account and quota', () => {
  const model = viewModel({access_enabled:false,account:{masked_email:'old'},dashboard:{account:{status:'active'},metrics:[{metric_type:'weekly',remaining_pct:80}]}});
  assert.equal(model.account, null); assert.deepEqual(model.metrics, []); assert.equal(model.authenticated, false);
});
test('authoritative empty account cannot fall back to stale console identity', () => {
  assert.equal(viewModel({account:{masked_email:'old'},dashboard:{account:null}}).account, null);
});

test('every update phase maps to an explicit action and busy guard', () => {
  for (const [phase, action, disabled] of [
    ['idle','check',false], ['checking','check',true], ['latest','check',false],
    ['available','download',false], ['downloading','download',true],
    ['ready','install',false], ['installing','install',true],
    ['check_error','check',false], ['download_error','download',false], ['install_error','download',false],
  ]) {
    const model = updateModel({phase});
    assert.equal(model.action, action, phase);
    assert.equal(model.disabled, disabled, phase);
    assert.ok(model.label && model.title);
  }
});
test('pending update survives failed checks and indeterminate downloads', () => {
  const model = updateModel({phase:'check_error',available:true,error:'网络暂不可用'});
  assert.equal(model.pending, true);
  assert.equal(model.action, 'download');
  assert.equal(model.description, '网络暂不可用');
  assert.equal(updateModel({received:100}).percent, null);
  assert.equal(updateModel({received:25,total:100}).percent, 25);
  assert.equal(updateModel({received:200,total:100}).percent, 100);
  assert.equal(updateModel().pending, false);
});
