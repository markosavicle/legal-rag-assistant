import assert from 'node:assert/strict';
import { test } from 'node:test';

import { citedNumbers, duplicateDocumentId, formatCitations, simplifyAnswer } from '../nodes/LegalRag/answers.ts';

const sources = [
	{ n: 1, source: 'Zakon o radu.pdf, page 14', chunk_id: 10, score: 0.9, text: 'Član 69.\nnajmanje 20 radnih dana' },
	{ n: 2, source: 'ugovor.txt', chunk_id: 11, score: 0.8, text: 'Član 6.\n22 radna dana' },
];
const response = { answer: '', sources, usage: { prompt_tokens: 1 }, latency_ms: 1200 };

test('citedNumbers reads [1], [1][3] and [1, 3]', () => {
	assert.deepEqual(citedNumbers('A [2]. B [1][3]. C [4, 1].'), [1, 2, 3, 4]);
	assert.deepEqual(citedNumbers('No citations here.'), []);
});

test('simplifyAnswer keeps only cited passages', () => {
	const simple = simplifyAnswer('Q?', { ...response, answer: 'Najmanje 20 radnih dana [1].' });
	assert.equal(simple.answered, true);
	assert.deepEqual(simple.citations.map((c) => c.n), [1]);
	assert.equal(simple.latencyMs, 1200);
});

test('simplifyAnswer trusts the API answered flag and citation list when present', () => {
	const refusal = { ...response, answer: 'Nisam pronašao odgovor [1][2].', answered: false, citations: [] };
	const simple = simplifyAnswer('Q?', refusal);
	assert.equal(simple.answered, false);
	assert.deepEqual(simple.citations, []);
});

test('simplifyAnswer without citations counts as not answered', () => {
	assert.equal(simplifyAnswer('Q?', { ...response, answer: 'I could not find it.' }).answered, false);
});

test('formatCitations makes one line per passage and truncates', () => {
	const text = formatCitations([{ n: 1, source: 'a.pdf', text: 'x'.repeat(10) + '\n  y' }], 5);
	assert.equal(text, '[1] a.pdf: xxxxx…');
});

test('duplicateDocumentId parses the 409 message', () => {
	assert.equal(duplicateDocumentId("This file is already indexed as 'a.pdf' (document 3)."), 3);
	assert.equal(duplicateDocumentId('Something else'), null);
});
