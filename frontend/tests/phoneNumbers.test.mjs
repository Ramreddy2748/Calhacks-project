import test from 'node:test';
import assert from 'node:assert/strict';
import { phoneNumbersIn } from '../src/phoneNumbers.mjs';

test('extracts formatted international destinations from call instructions', () => {
  assert.deepEqual(phoneNumbersIn('Call H&M at +1 (415) 555-1234. Ask for a refund.'), ['+14155551234']);
  assert.deepEqual(phoneNumbersIn('Their number is +44 20 7946 0958'), ['+442079460958']);
});

test('keeps distinct choices and deduplicates repeated destinations', () => {
  assert.deepEqual(phoneNumbersIn('Try +14155551234 or +44 20 7946 0958. Again: +1 (415) 555-1234.'), ['+14155551234', '+442079460958']);
});

test('does not guess countries or interpret ordinary account information as phones', () => {
  assert.deepEqual(phoneNumbersIn('415-555-1234; order 1234567890; $30 on 2026-10-25; +1234'), []);
  assert.deepEqual(phoneNumbersIn('+0123456789 +1234567890123456'), []);
  assert.deepEqual(phoneNumbersIn(''), []);
});
