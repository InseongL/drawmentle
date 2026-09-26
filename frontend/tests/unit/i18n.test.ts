import assert from 'node:assert/strict';
import test from 'node:test';
import { MESSAGES, categoryName } from '../../src/shared/i18n/messages.ts';
import { resolveCandidate } from '../../src/features/inference/devPrediction.ts';
import { errorKey } from '../../src/features/game/submissionFlow.ts';
import { ApiError } from '../../src/shared/api/client.ts';

function shape(value: unknown): unknown {
  if (typeof value === 'function') return `fn/${value.length}`;
  if (Array.isArray(value)) return `array/${value.length}`;
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, shape(v)]));
  }
  return typeof value;
}

test('English mirrors every Korean entry, including FAQ count and message parameters', () => {
  assert.deepEqual(shape(MESSAGES.en), shape(MESSAGES.ko));
  assert.notEqual(MESSAGES.en.lede, MESSAGES.ko.lede);
});

test('the title swaps main and small names between languages', () => {
  assert.deepEqual([MESSAGES.ko.brand, MESSAGES.ko.brandSub], ['드로맨틀', 'drawmentle']);
  assert.deepEqual([MESSAGES.en.brand, MESSAGES.en.brandSub], ['Drawmentle', '드로맨틀']);
  assert.equal(MESSAGES.ko.switchLang, 'en');
  assert.equal(MESSAGES.en.switchLang, 'ko');
});

test('English names come from the release, or read from the ID for older releases', () => {
  const withEn = { categoryId: 'the_mona_lisa', displayNameKo: '모나리자', displayNameEn: 'The Mona Lisa' };
  const idOnly = { categoryId: 'hot_air_balloon', displayNameKo: '열기구', displayNameEn: null };
  assert.equal(categoryName(withEn, 'en'), 'The Mona Lisa');
  assert.equal(categoryName(idOnly, 'en'), 'hot air balloon');
  assert.equal(categoryName(idOnly, 'ko'), '열기구');
  const candidates = [{ ...idOnly, candidateIndex: 1 }, { ...withEn, candidateIndex: 2 }];
  assert.equal(resolveCandidate(candidates, 'Hot Air Balloon')?.categoryId, 'hot_air_balloon');
  assert.equal(resolveCandidate(candidates, 'the mona lisa')?.categoryId, 'the_mona_lisa');
});

test('errors are shown by code, never with the server message', () => {
  assert.equal(errorKey(new ApiError(409, 'GAME_ALREADY_SOLVED', '서버 문구', false)), 'GAME_ALREADY_SOLVED');
  assert.equal(errorKey(new ApiError(0, 'NETWORK_ERROR', '', true, true)), 'NETWORK_ERROR');
  assert.equal(errorKey(new ApiError(502, 'HTTP_502', '', true)), 'SERVER_UNREACHABLE');
  assert.equal(errorKey(new ApiError(418, 'SOMETHING_NEW', '', false)), 'UNKNOWN');
  assert.equal(MESSAGES.en.date(2026, 9, 26), 'September 26, 2026');
  assert.equal(MESSAGES.ko.date(2026, 9, 26), '2026년 9월 26일');
});
