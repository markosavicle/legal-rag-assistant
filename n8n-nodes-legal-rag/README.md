# n8n-nodes-legal-rag

An [n8n](https://n8n.io/) community node for [Legal RAG Assistant](https://github.com/markosavicle/legal-rag-assistant): ask questions about laws and contracts and get answers grounded in the documents, with the passages they cite. It also searches passages and manages the indexed documents.

Use it to put cited legal answers into any workflow: answer questions that arrive by email or chat, extract key terms from every new contract, or give an AI Agent a tool that only answers from your documents.

[Installation](#installation) · [Operations](#operations) · [Credentials](#credentials) · [Output](#output) · [Example workflows](#example-workflows) · [Compatibility](#compatibility) · [Development](#development)

## Installation

**From the n8n UI** (self-hosted): *Settings → Community Nodes → Install*, enter `n8n-nodes-legal-rag`. See the [community nodes installation guide](https://docs.n8n.io/integrations/community-nodes/installation/).

**Manually** (n8n in Docker, e.g. before a version is on npm):

```bash
npm pack                                   # in this folder: builds n8n-nodes-legal-rag-<version>.tgz
docker cp n8n-nodes-legal-rag-0.1.0.tgz n8n:/tmp/pkg.tgz
docker exec n8n sh -c "mkdir -p ~/.n8n/nodes && cd ~/.n8n/nodes && npm install --omit=dev --legacy-peer-deps /tmp/pkg.tgz"
docker restart n8n
```

`--legacy-peer-deps` stops npm from installing a second copy of `n8n-workflow`. n8n already provides it, and installing it again pulls in native modules that fail to build in the n8n image.

## Operations

| Resource | Operation | What it does |
|---|---|---|
| Question | **Ask** | Answers a question from the documents. Returns the answer, `answered` (false when the documents don't contain it), the passages it cites and a ready-to-post citation text. Can be limited to chosen documents. |
| Passage | **Search** | The passages that best match a query, without generating an answer (semantic, keyword or hybrid). |
| Document | **Upload** | Indexes a PDF, DOCX, TXT or MD file from binary data. *Skip If Already Indexed* (on by default) returns the existing document instead of failing, so a workflow can safely run twice on the same file. |
| Document | **Get Many** | Lists indexed documents. |
| Document | **Delete** | Removes a document and its passages. |

Document pickers load the indexed documents into a dropdown. You can also pass ids with an expression, e.g. `{{ [$json.documentId] }}`.

The node is marked `usableAsTool`, so an **AI Agent** can call it as a tool (n8n adds a *Legal RAG Tool* variant automatically). Give the agent the Ask operation to get answers that only come from your documents and always carry sources.

## Credentials

**Legal RAG API**

- **Base URL**: where the API runs. For n8n in Docker on the same machine, use `http://host.docker.internal:8000`.
- **API Key**: the `API_KEY` set on the API server, sent as `X-API-Key`. Leave it empty if the server runs without one, which is only sensible on your own machine.

*Test* calls `GET /documents`, so it checks both the URL and the key.

## Output

Ask, with *Simplify* on (the default):

```json
{
  "question": "Koliko najmanje traje godišnji odmor?",
  "answer": "U svakoj kalendarskoj godini zaposleni ima pravo na godišnji odmor u trajanju od najmanje 20 radnih dana [1].",
  "answered": true,
  "citations": [
    { "n": 1, "source": "Zakon o radu.pdf, page 14", "text": "Члан 69.\nУ свакој календарској години запослени има право на годишњи одмор ..." }
  ],
  "citationsText": "[1] Zakon o radu.pdf, page 14: Члан 69. У свакој календарској години ...",
  "latencyMs": 1108
}
```

`answered` is false when the answer cites nothing or says the documents don't cover the question, including partial answers ("the address is not given"). Route on it: an answered question can go to a reviewer, an unanswered one to a person. With *Simplify* off you also get every retrieved passage with its score, token usage and timings.

## Example workflows

Import them from [`examples/`](examples/) (*Workflows → Import from File*), then select your credentials in each node.

| Workflow | Flow | Tested |
|---|---|---|
| [01 Q&A webhook](examples/01-legal-qa-webhook.json) | `POST /webhook/legal-question` → Ask → JSON response; errors go to a 422 response through the node's error output | End to end: an answered question, an out-of-scope one (`answered: false`), and an empty one (422) |
| [02 Email → Slack review → reply](examples/02-email-answer-slack-review.json) | IMAP email → Ask → *answered?* → reviewer approves the draft in Slack (*Send reply / Don't send*) → SMTP reply; unanswered → `#legal-escalations` | IMAP trigger, answering and routing tested against a local GreenMail server (one answerable email, one not). The Slack and SMTP steps need your accounts |
| [03 Contract intake → Google Sheet](examples/03-contract-intake-sheet.json) | Form upload → Upload (duplicate-safe) → 5 checklist questions scoped to that contract → one row per contract → Google Sheets | Form, indexing (new file and re-upload) and checklist tested end to end. The Sheets step needs your Google account |

They were tested on n8n 2.43.7 in Docker, with the Slack, SMTP and Sheets nodes disabled in the test copies.

## Compatibility

- Tested with n8n **2.43.7** (self-hosted, Docker) and Legal RAG Assistant from this repository.
- Requires the Legal RAG Assistant API. The `answered` and `citations` fields come from the API; with an older API the node works them out from the answer's `[n]` citations.
- No runtime dependencies.

## Development

```bash
npm ci
npm run lint     # n8n's community-node lint rules (strict mode)
npm run build
npm test         # unit tests for the response shaping (node:test, no extra dependencies)
npm run dev      # n8n with the node and hot reload on http://localhost:5678
```

Releases are published from GitHub Actions with npm provenance, which n8n requires for community nodes. Bump the version in `package.json` and `CHANGELOG.md`, then push a tag `n8n-nodes-legal-rag-v<version>`; see `.github/workflows/n8n-node-publish.yml` in the repository root.

## Version history

See [CHANGELOG.md](CHANGELOG.md).
