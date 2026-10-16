-- LocalLens AX PostgreSQL metadata schema draft.
-- This schema is for the AX document search service layer.
-- Vector payloads remain in Qdrant; PostgreSQL owns metadata, policy, jobs, and logs.

CREATE TABLE IF NOT EXISTS departments (
    department_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    department_id TEXT NOT NULL REFERENCES departments(department_id),
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'employee',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    owner_department_id TEXT NOT NULL REFERENCES departments(department_id),
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    access_level TEXT NOT NULL DEFAULT 'internal',
    current_version_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_versions (
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_path_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, version_id)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL,
    page_no INTEGER,
    chunk_no INTEGER,
    modality TEXT NOT NULL,
    text_preview TEXT NOT NULL,
    qdrant_point_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (document_id, version_id)
        REFERENCES document_versions(document_id, version_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS access_policies (
    policy_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    department_id TEXT REFERENCES departments(department_id),
    acl_tag TEXT NOT NULL,
    can_read BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS indexing_jobs (
    job_id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(document_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS search_logs (
    search_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    query TEXT NOT NULL,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    search_id TEXT REFERENCES search_logs(search_id) ON DELETE SET NULL,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    chunk_id TEXT NOT NULL REFERENCES document_chunks(chunk_id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_owner_department
    ON documents(owner_department_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document
    ON document_chunks(document_id, version_id);

CREATE INDEX IF NOT EXISTS idx_access_policies_document_acl
    ON access_policies(document_id, acl_tag);

CREATE INDEX IF NOT EXISTS idx_search_logs_user_created
    ON search_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_documents_title_fts
    ON documents USING GIN (to_tsvector('simple', title));

CREATE INDEX IF NOT EXISTS idx_document_chunks_preview_fts
    ON document_chunks USING GIN (to_tsvector('simple', text_preview));
