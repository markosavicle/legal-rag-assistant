// Pure helpers for shaping API responses into workflow-friendly items. No n8n imports, so they
// can be unit-tested with Node's test runner.

export interface Source {
	n: number;
	source: string;
	chunk_id: number;
	score: number;
	text: string;
}

export interface AskResponse {
	answer: string;
	answered?: boolean;
	citations?: number[];
	sources: Source[];
	usage: Record<string, number>;
	latency_ms: number;
	retrieval_ms?: number;
	generation_ms?: number;
}

/** Passage numbers cited as [1], [1][3] or [1, 3]. */
export function citedNumbers(answer: string): number[] {
	const found = new Set<number>();
	for (const group of answer.matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g)) {
		for (const n of group[1].split(',')) found.add(Number(n.trim()));
	}
	return [...found].sort((a, b) => a - b);
}

/**
 * The answer with only the passages it cites, plus `answered`: false when the API said it could
 * not find the answer, so a workflow can route those questions to a person.
 */
export function simplifyAnswer(question: string, response: AskResponse) {
	const cited = new Set(response.citations ?? citedNumbers(response.answer));
	const citations = response.sources
		.filter((s) => cited.has(s.n))
		.map((s) => ({ n: s.n, source: s.source, text: s.text }));
	return {
		question,
		answer: response.answer,
		answered: response.answered ?? citations.length > 0,
		citations,
		latencyMs: response.latency_ms,
	};
}

/** Plain-text citation list, ready for a Slack message or an email body. */
export function formatCitations(citations: Array<{ n: number; source: string; text: string }>, maxChars = 280): string {
	return citations
		.map((c) => {
			const text = c.text.replace(/\s+/g, ' ').trim();
			return `[${c.n}] ${c.source}: ${text.length > maxChars ? `${text.slice(0, maxChars)}…` : text}`;
		})
		.join('\n');
}

/** The id from the API's 409 message "...already indexed as 'x.pdf' (document 3)." */
export function duplicateDocumentId(detail: string): number | null {
	const match = /\(document (\d+)\)/.exec(detail);
	return match ? Number(match[1]) : null;
}
