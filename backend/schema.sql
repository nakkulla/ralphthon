CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    summary text,
    raw_text text,
    tech_stack text[] NOT NULL DEFAULT '{}',
    domain text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'simple',
            coalesce(name, '') || ' ' ||
            coalesce(summary, '') || ' ' ||
            coalesce(raw_text, '') || ' ' ||
            coalesce(array_to_string(tech_stack, ' '), '')
        )
    ) STORED
);

CREATE TABLE IF NOT EXISTS images (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    file_path text NOT NULL,
    url text NOT NULL,
    prompt text,
    mime_type text NOT NULL,
    width int,
    height int,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('tag', 'keyword')),
    UNIQUE (name, kind)
);

CREATE TABLE IF NOT EXISTS profile_tags (
    profile_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (profile_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_profiles_search_vector ON profiles USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_profiles_tech_stack ON profiles USING gin(tech_stack);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name_kind ON tags(name, kind);
CREATE INDEX IF NOT EXISTS idx_profile_tags_tag_id ON profile_tags(tag_id);
