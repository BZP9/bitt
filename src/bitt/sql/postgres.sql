-- bitt main database (docs/v2/db.md): schemas, the graph, append-only. Idempotent: safe to run on every open.
CREATE SCHEMA IF NOT EXISTS bitt;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS made;      -- made rows: one table per output contract, shared by every task (foundation §D1)

-- ============================================================ kernel graph
CREATE TABLE IF NOT EXISTS bitt.node (
  id         text PRIMARY KEY,                  -- node id (event identity): h(node body)
  seq        bigint UNIQUE NOT NULL,            -- the journal: commit order
  kind       text NOT NULL,
  spec_h     text,                              -- what it is (cache identity); NULL for events / checks / marks
  task       text,                              -- root goal id (NULL for roots and raw imports)
  name       text,                              -- display name
  state      text,                              -- a goal's: open
  payload    jsonb NOT NULL,
  links      jsonb NOT NULL,                    -- the exact links of the hashed body (bitt.link is the queryable form)
  stamp      jsonb NOT NULL,                    -- {tool, card, contract, actor, at}
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bitt.link (
  child   text NOT NULL REFERENCES bitt.node,
  role    text NOT NULL,
  ord     int  NOT NULL DEFAULT 0,
  parent  text NOT NULL REFERENCES bitt.node,
  lineage boolean NOT NULL,
  PRIMARY KEY (child, role, ord)
);
CREATE INDEX IF NOT EXISTS link_parent ON bitt.link (parent, role);
CREATE INDEX IF NOT EXISTS node_kind_task ON bitt.node (kind, task);
CREATE INDEX IF NOT EXISTS node_task_name ON bitt.node (task, name);
CREATE INDEX IF NOT EXISTS node_spec ON bitt.node (spec_h);
-- names (docs/v2/names.md §5): one line per (namespace, name), ever; the names grammar
CREATE UNIQUE INDEX IF NOT EXISTS name_unique ON bitt.node ((payload->>'ns'), (payload->>'name')) WHERE kind = 'name';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'name_pattern') THEN
    ALTER TABLE bitt.node ADD CONSTRAINT name_pattern CHECK (kind <> 'name' OR (payload->>'name') ~ '^[a-z][a-z0-9_]*$');
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS bitt.refusal_log (seq bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(), entry jsonb NOT NULL);

-- ============================================================ vectors (optional: real[] when pgvector is not installed)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN CREATE EXTENSION IF NOT EXISTS vector; END IF;
END $$;


-- ============================================================ append-only, by trigger
CREATE OR REPLACE FUNCTION bitt.refuse_change() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'bitt: % on %.% is not allowed (append-only)', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME; END $$;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['bitt.node','bitt.link','bitt.refusal_log'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS no_change ON %s', t);
    EXECUTE format('CREATE TRIGGER no_change BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION bitt.refuse_change()', t);
    EXECUTE format('DROP TRIGGER IF EXISTS no_truncate ON %s', t);
    EXECUTE format('CREATE TRIGGER no_truncate BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION bitt.refuse_change()', t);
  END LOOP;
END $$;
-- ============================================================ no direct writes (docs/v2/db.md §6)
-- Every bitt table refuses an INSERT that is not bitt's own: the kernel marks each of its transactions (SET LOCAL bitt.writer =
-- 'kernel'). A direct write on purpose sets bitt.direct_write = '<reason>' first: it goes through and is recorded below.
CREATE TABLE IF NOT EXISTS bitt.direct_write (at timestamptz NOT NULL DEFAULT now(), who text NOT NULL DEFAULT current_user,
                                             tbl text NOT NULL, op text NOT NULL, reason text NOT NULL);
CREATE OR REPLACE FUNCTION bitt.refuse_direct() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF current_setting('bitt.writer', true) = 'kernel' THEN RETURN NEW; END IF;
  IF coalesce(current_setting('bitt.direct_write', true), '') <> '' THEN
    INSERT INTO bitt.direct_write (tbl, op, reason) VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, TG_OP, current_setting('bitt.direct_write'));
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'bitt: a direct % into %.% is refused. next: write through bitt (a bitt command, or bitt call <card>); to write '
                  'directly on purpose, SET bitt.direct_write = ''<your reason>'' first (it is recorded in bitt.direct_write)',
                  TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME;
END $$;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['bitt.node','bitt.link','bitt.refusal_log'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS no_direct ON %s', t);
    EXECUTE format('CREATE TRIGGER no_direct BEFORE INSERT ON %s FOR EACH ROW EXECUTE FUNCTION bitt.refuse_direct()', t);
  END LOOP;
END $$;
-- the operation / registry tables (bitt.recipe, …) come from src/bitt/tables.py, then sql/postgres_nav.sql
