# Changelog

## 0.1.0

First release.

- **Question → Ask**: answer with `answered` flag, cited passages only, and `citationsText` for messages; optional document scope, search mode and number of passages; *Simplify* off returns the raw response.
- **Passage → Search**: retrieval only, scoped to chosen documents.
- **Document → Upload / Get Many / Delete**: upload from binary data with duplicate-safe re-runs.
- **Legal RAG API** credential: base URL and API key (`X-API-Key`), with a connection test.
- Usable as an AI Agent tool.
- Three example workflows: Q&A webhook, email → Slack review → reply, contract intake → Google Sheet.
