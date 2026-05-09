export interface RevealPayload {
  key_plaintext: string
  key_hash: string
  key_prefix: string
  created_at: string
  project_id: string
  version_id: string | null
}

export interface KeyMeta {
  project_id: string
  key_hash_short: string | null
  created_at: string | null
  last_used: string | null
}
