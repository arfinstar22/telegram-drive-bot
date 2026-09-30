-- Migration 001: Security Hardening & Constraints
-- Safe & Non-Destructive: Add missing columns and tables without dropping production data

-- 1. Account Recovery Codes Table (replaces insecure username-based takeover)
CREATE TABLE IF NOT EXISTS account_recovery_codes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recovery_codes_user ON account_recovery_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_recovery_codes_lookup ON account_recovery_codes(code_hash) WHERE used = FALSE;

-- 2. Granular Share Columns for Files (optional dedicated columns if metadata is split from share_token)
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_expires_at TIMESTAMPTZ;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_pin_hash TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_download_limit INT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_download_count INT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_revoked_at TIMESTAMPTZ;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_enabled BOOLEAN DEFAULT TRUE;

-- 3. Granular Share Columns for Folders
ALTER TABLE folders ADD COLUMN IF NOT EXISTS share_revoked_at TIMESTAMPTZ;
ALTER TABLE folders ADD COLUMN IF NOT EXISTS share_enabled BOOLEAN DEFAULT TRUE;

-- 4. Composite & Performance Indexes
CREATE INDEX IF NOT EXISTS idx_files_user_folder ON files(user_id, folder_id);
CREATE INDEX IF NOT EXISTS idx_files_user_trashed ON files(user_id, is_trashed);
CREATE INDEX IF NOT EXISTS idx_files_unique_user ON files(user_id, file_unique_id);
CREATE INDEX IF NOT EXISTS idx_folders_user_parent ON folders(user_id, parent_id);

-- 5. Data Consistency Audit Queries
-- Run these queries to check for existing anomalies in production data:

-- Audit 1: Files whose user_id does not match their parent folder's user_id
-- SELECT f.id AS file_id, f.user_id AS file_user_id, fo.id AS folder_id, fo.user_id AS folder_user_id
-- FROM files f
-- JOIN folders fo ON fo.id = f.folder_id
-- WHERE f.user_id <> fo.user_id;

-- Audit 2: Child folders whose user_id does not match their parent folder's user_id
-- SELECT c.id AS child_id, c.user_id AS child_user_id, p.id AS parent_id, p.user_id AS parent_user_id
-- FROM folders c
-- JOIN folders p ON p.id = c.parent_id
-- WHERE c.user_id <> p.user_id;

-- Audit 3: Orphan files (folder does not exist)
-- SELECT f.id, f.file_name, f.user_id, f.folder_id
-- FROM files f
-- LEFT JOIN folders fo ON fo.id = f.folder_id
-- WHERE fo.id IS NULL;

-- Audit 4: Self-referencing folders (folder whose parent is itself)
-- SELECT id, name, user_id FROM folders WHERE id = parent_id;
