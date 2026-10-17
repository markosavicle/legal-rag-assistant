-- Data-validation checks on the ingested documents, run by scripts/validate_data.py.
-- Each check is one query that returns the offending rows; no rows means the check passes.
-- Header format: -- name: <id> | <error|warning|info> | <what a returned row means>
-- %(embedding_model)s is the configured embedding model.

-- name: duplicate_filename | warning | the same filename is indexed more than once (different file contents)
SELECT filename, count(*) AS documents, array_agg(id ORDER BY id) AS ids
FROM documents GROUP BY filename HAVING count(*) > 1;

-- name: duplicate_document_content | error | two documents have identical text (a re-saved or renamed copy; the file hash differs)
WITH doc_text AS (
    SELECT d.id, d.filename, md5(string_agg(c.search_text, E'\n' ORDER BY c.chunk_index)) AS text_hash
    FROM documents d JOIN chunks c ON c.document_id = d.id GROUP BY d.id
)
SELECT text_hash, array_agg(filename ORDER BY id) AS filenames
FROM doc_text GROUP BY text_hash HAVING count(*) > 1;

-- name: near_duplicate_documents | warning | most chunks of one document also appear in another (an edited copy)
WITH pairs AS (
    SELECT a.document_id AS doc_a, b.document_id AS doc_b, count(DISTINCT a.search_text) AS shared
    FROM chunks a JOIN chunks b ON a.search_text = b.search_text AND a.document_id < b.document_id
    GROUP BY 1, 2
), sizes AS (SELECT document_id, count(DISTINCT search_text) AS n FROM chunks GROUP BY 1)
SELECT da.filename AS document_a, db.filename AS document_b, p.shared,
       round(p.shared::numeric / least(sa.n, sb.n), 2) AS overlap
FROM pairs p
JOIN sizes sa ON sa.document_id = p.doc_a JOIN sizes sb ON sb.document_id = p.doc_b
JOIN documents da ON da.id = p.doc_a JOIN documents db ON db.id = p.doc_b
WHERE p.shared::numeric / least(sa.n, sb.n) >= 0.5;

-- name: duplicate_chunks | warning | the same text is stored as several chunks of one document (repeated boilerplate, or a page extracted twice)
SELECT d.filename, left(c.search_text, 80) AS text, count(*) AS copies, array_agg(c.chunk_index ORDER BY c.chunk_index) AS chunk_indexes
FROM chunks c JOIN documents d ON d.id = c.document_id
GROUP BY d.filename, c.search_text HAVING count(*) > 1;

-- name: documents_without_chunks | error | a document has no chunks, so it can never be found
SELECT d.id, d.filename FROM documents d
WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id);

-- name: missing_document_fields | error | a document has an empty filename or hash, or no upload time
SELECT id, filename, file_hash, created_at FROM documents
WHERE coalesce(trim(filename), '') = '' OR coalesce(file_hash, '') !~ '^[0-9a-f]{64}$' OR created_at IS NULL;

-- name: empty_chunks | error | a chunk has no text, no search text or no stems
SELECT d.filename, c.chunk_index FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE trim(c.content) = '' OR trim(c.search_text) = '' OR trim(c.stems) = '';

-- name: tiny_chunks | warning | a chunk is under 40 characters (usually a page number, header or extraction noise)
SELECT d.filename, c.chunk_index, c.page, c.content FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE length(trim(c.content)) < 40;

-- name: chunk_index_gaps | error | chunk numbers of a document are not 0..n-1 (chunks lost or inserted twice)
SELECT d.filename, count(*) AS chunks, min(c.chunk_index) AS first, max(c.chunk_index) AS last
FROM chunks c JOIN documents d ON d.id = c.document_id
GROUP BY d.filename HAVING min(c.chunk_index) <> 0 OR max(c.chunk_index) <> count(*) - 1 OR count(DISTINCT c.chunk_index) <> count(*);

-- name: pdf_chunk_without_page | error | a PDF chunk has no page number, so its citation cannot point to a page
SELECT d.filename, c.chunk_index FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE d.filename ILIKE '%%.pdf' AND c.page IS NULL;

-- name: pages_out_of_order | error | page numbers go backwards as the chunk number grows
SELECT filename, chunk_index, page, previous_page FROM (
    SELECT d.filename, c.chunk_index, c.page,
           lag(c.page) OVER (PARTITION BY c.document_id ORDER BY c.chunk_index) AS previous_page
    FROM chunks c JOIN documents d ON d.id = c.document_id
) t WHERE page < previous_page;

-- name: zero_embeddings | error | an embedding is all zeros, so cosine similarity is undefined
SELECT d.filename, c.chunk_index FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE vector_norm(c.embedding) = 0;

-- name: cache_from_other_model | info | cached embeddings from another embedding model (unused; safe to delete)
SELECT model, count(*) AS embeddings FROM embedding_cache WHERE model <> %(embedding_model)s GROUP BY model;

-- name: uploaded_in_future | error | a document's upload time is in the future (clock or import problem)
SELECT id, filename, created_at FROM documents WHERE created_at > now() + interval '5 minutes';
