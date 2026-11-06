-- bitt navigation (docs/v2/db.md): functions and views. Run after the bitt.* tables exist.
-- ============================================================ navigation: functions
-- a name or a unique id prefix (≥ 8 chars) → the full node id (a name wins; NULL if none or ambiguous)
CREATE OR REPLACE FUNCTION bitt.id(ref text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    (SELECT CASE WHEN count(*) = 1 THEN min(id) END FROM bitt.node WHERE name = ref),
    (SELECT CASE WHEN count(*) = 1 THEN min(id) END FROM bitt.node WHERE length(ref) >= 8 AND starts_with(id, ref)))
$$;
-- a unique run hash prefix → the run hash
CREATE OR REPLACE FUNCTION bitt.run(ref text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN count(*) = 1 THEN min(bitt_run_hash) END FROM bitt.run WHERE length(ref) >= 8 AND starts_with(bitt_run_hash, ref)
$$;
-- every raw or output row with that bitt_row_hash (or prefix), in any registered table
CREATE OR REPLACE FUNCTION bitt.row(ref text) RETURNS TABLE (schema text, tbl text, data jsonb) LANGUAGE plpgsql STABLE AS $$
DECLARE t record; BEGIN
  IF length(ref) < 8 THEN RETURN; END IF;
  FOR t IN SELECT b.schema AS s, b.name AS n FROM bitt.table b WHERE b.kind IN ('raw', 'output') ORDER BY b.schema, b.name LOOP
    RETURN QUERY EXECUTE format('SELECT %L::text, %L::text, to_jsonb(x) FROM %I.%I x WHERE starts_with(bitt_row_hash, $1)', t.s, t.n, t.s, t.n)
      USING ref;
  END LOOP;
END $$;
-- what X was built from (lineage links only), with the depth: the walker's walk.up (docs/v2/walk.md W5; a link's lineage flag is the
-- role registry's class when the link was written, so SQL and Python read one meaning of lineage)
CREATE OR REPLACE FUNCTION bitt.lineage(ref text)
RETURNS TABLE (id text, kind text, name text, depth int) LANGUAGE sql STABLE AS $$
  WITH RECURSIVE up(id, depth) AS (
    SELECT bitt.id(ref), 0
    UNION
    SELECT l.parent, up.depth + 1 FROM bitt.link l JOIN up ON l.child = up.id
    WHERE l.lineage
  )
  SELECT n.id, n.kind, n.name, min(up.depth) FROM up JOIN bitt.node n USING (id) GROUP BY n.id, n.kind, n.name ORDER BY 4, 2
$$;
-- every node X links to, story included (why / where / judged by): NOT lineage; for "what was X made from" use bitt.lineage
CREATE OR REPLACE FUNCTION bitt.upstream(ref text)
RETURNS TABLE (id text, kind text, name text, depth int) LANGUAGE sql STABLE AS $$
  WITH RECURSIVE up(id, depth) AS (
    SELECT bitt.id(ref), 0
    UNION
    SELECT l.parent, up.depth + 1 FROM bitt.link l JOIN up ON l.child = up.id
  )
  SELECT n.id, n.kind, n.name, min(up.depth) FROM up JOIN bitt.node n USING (id) GROUP BY n.id, n.kind, n.name ORDER BY 4, 2
$$;
-- everything made from X (lineage links, the reverse way), with the depth: the walker's walk.down (W5)
CREATE OR REPLACE FUNCTION bitt.downstream(ref text)
RETURNS TABLE (id text, kind text, name text, depth int) LANGUAGE sql STABLE AS $$
  WITH RECURSIVE down(id, depth) AS (
    SELECT bitt.id(ref), 0
    UNION
    SELECT l.child, down.depth + 1 FROM bitt.link l JOIN down ON l.parent = down.id
    WHERE l.lineage
  )
  SELECT n.id, n.kind, n.name, min(down.depth) FROM down JOIN bitt.node n USING (id) GROUP BY n.id, n.kind, n.name ORDER BY 4, 2
$$;
-- the graph as of journal position N
CREATE OR REPLACE FUNCTION bitt.at(n bigint) RETURNS SETOF bitt.node LANGUAGE sql STABLE AS $$
  SELECT * FROM bitt.node WHERE seq <= n ORDER BY seq
$$;

-- ============================================================ names (docs/v2/names.md): the registry, read the way the kernel reads it
-- ns: '' (a task), 'lib' (the shelf: modules, artifacts), 'raw' (a raw line), or a task's root goal id (its data lines and recipes)
CREATE OR REPLACE VIEW bitt.v_name AS
  SELECT n.payload->>'ns' AS ns, n.payload->>'name' AS name, n.payload->>'class' AS class, n.payload->>'kind' AS kind, l.parent AS target,
         n.created_at, n.id
  FROM bitt.node n JOIN bitt.link l ON l.child = n.id AND l.role = 'target' WHERE n.kind = 'name';
-- the root of a node's line (itself when it is a root)
CREATE OR REPLACE FUNCTION bitt.line_of(nid text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE((SELECT parent FROM bitt.link WHERE child = nid AND role = 'line'), nid)
$$;
-- a line's members in commit order: its root, then every node linking `line` to it
CREATE OR REPLACE FUNCTION bitt.members(root text) RETURNS SETOF bitt.node LANGUAGE sql STABLE AS $$
  SELECT n.* FROM bitt.node n WHERE n.id = root OR n.id IN (SELECT child FROM bitt.link WHERE parent = root AND role = 'line') ORDER BY n.seq
$$;
-- how a node's line is named: `task`, `lib/name`, `raw/name` or `task/name` (NULL if its line has no name)
CREATE OR REPLACE FUNCTION bitt.name_of(nid text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT CASE v.ns WHEN '' THEN v.name WHEN 'raw' THEN 'raw/' || v.name WHEN 'lib' THEN 'lib/' || v.name
         ELSE (SELECT t.name FROM bitt.v_name t WHERE t.ns = '' AND t.target = v.ns) || '/' || v.name END
  FROM bitt.v_name v WHERE v.target = bitt.line_of(nid) ORDER BY v.created_at LIMIT 1
$$;
-- its version (a version tag, set once: W14), or NULL when unversioned
CREATE OR REPLACE FUNCTION bitt.version_of(nid text) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT t.payload->>'value' FROM bitt.node t JOIN bitt.link l ON l.child = t.id AND l.role = 'target'
  WHERE l.parent = nid AND t.kind = 'tag' AND t.payload->>'tag' = 'version' ORDER BY t.seq LIMIT 1
$$;
-- a reference → a node id, as the kernel resolves it (names.md §3): an id, a unique ≥8-hex prefix, `[ns/]name[@N | @N.M | @alias]`.
-- `task` (a root goal id) is the reader's own task (its names, then the shelf, then a task name); without one a short name resolves
-- when exactly one namespace other than raw has it. NULL = no answer.
CREATE OR REPLACE FUNCTION bitt.resolve(ref text, task text DEFAULT NULL) RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE m text[]; ns_ text; nm text; at_ text; b record; fam text; hit text; n int;
BEGIN
  IF EXISTS (SELECT 1 FROM bitt.node WHERE id = ref) THEN RETURN ref; END IF;
  IF ref ~ '^[0-9a-f]{8,}$' THEN
    SELECT CASE WHEN count(*) = 1 THEN min(id) END INTO hit FROM bitt.node WHERE starts_with(id, ref);
    IF hit IS NOT NULL THEN RETURN hit; END IF;
  END IF;
  m := regexp_match(ref, '^(?:([a-z][a-z0-9_]*)/)?([a-z][a-z0-9_]*)(?:@([0-9]+(?:\.[0-9]+)?|[a-z][a-z0-9_]*))?$');
  IF m IS NULL THEN RETURN NULL; END IF;
  nm := m[2]; at_ := m[3];
  IF m[1] IN ('raw', 'lib') THEN ns_ := m[1];
  ELSIF m[1] IS NOT NULL THEN SELECT target INTO ns_ FROM bitt.v_name WHERE ns = '' AND name = m[1];
    IF ns_ IS NULL THEN RETURN NULL; END IF;
  END IF;
  IF ns_ IS NOT NULL THEN SELECT * INTO b FROM bitt.v_name WHERE ns = ns_ AND name = nm;
  ELSIF task IS NOT NULL THEN
    SELECT * INTO b FROM bitt.v_name WHERE name = nm AND ns IN (task, 'lib', '')
     ORDER BY CASE ns WHEN task THEN 0 WHEN 'lib' THEN 1 ELSE 2 END LIMIT 1;
  ELSE
    SELECT count(*) INTO n FROM bitt.v_name WHERE name = nm AND ns <> 'raw';
    IF n <> 1 THEN RETURN NULL; END IF;
    SELECT * INTO b FROM bitt.v_name WHERE name = nm AND ns <> 'raw';
  END IF;
  IF b IS NULL THEN RETURN NULL; END IF;
  SELECT split_part(kind, ':', 1) INTO fam FROM bitt.node WHERE id = b.target;
  IF fam = 'goal' THEN RETURN b.target; END IF;
  IF fam = 'raw' THEN                                                -- a raw line's versions are its imports, @1 …
    IF at_ IS NULL THEN SELECT id INTO hit FROM bitt.members(b.target) ORDER BY seq DESC LIMIT 1;
    ELSIF at_ ~ '^[0-9]+$' THEN SELECT id INTO hit FROM bitt.members(b.target) ORDER BY seq OFFSET at_::int - 1 LIMIT 1;
    END IF;
    RETURN hit;
  END IF;
  IF at_ IS NULL THEN
    SELECT id INTO hit FROM bitt.members(b.target) WHERE split_part(kind, ':', 1) = fam ORDER BY seq DESC LIMIT 1;
  ELSIF at_ ~ '^[0-9]' THEN                                          -- @2 = the newest 2.x, @2.1 = exactly that version
    SELECT x.id INTO hit FROM bitt.members(b.target) x
     WHERE split_part(x.kind, ':', 1) = fam AND bitt.version_of(x.id) IS NOT NULL
       AND (CASE WHEN at_ LIKE '%.%' THEN string_to_array(bitt.version_of(x.id), '.')::int[] = string_to_array(at_, '.')::int[]
                 ELSE split_part(bitt.version_of(x.id), '.', 1)::int = at_::int END)
     ORDER BY string_to_array(bitt.version_of(x.id), '.')::int[] DESC LIMIT 1;
  ELSE                                                               -- an alias tag: the newest one with that value on the line
    SELECT l.parent INTO hit FROM bitt.node t JOIN bitt.link l ON l.child = t.id AND l.role = 'target'
     WHERE t.kind = 'tag' AND t.payload->>'tag' = 'alias' AND t.payload->>'value' = at_ AND bitt.line_of(l.parent) = b.target
     ORDER BY t.seq DESC LIMIT 1;
  END IF;
  RETURN hit;
END $$;

-- ============================================================ navigation: views
CREATE OR REPLACE VIEW bitt.v_task AS
  SELECT id, bitt.name_of(id) AS name, payload->>'problem' AS problem, stamp->>'actor' AS opened_by, created_at
  FROM bitt.node WHERE kind = 'goal' AND task IS NULL;
CREATE OR REPLACE VIEW bitt.v_node AS
  SELECT left(n.id, 12) AS short, n.kind, t.name AS task, n.name, n.state, n.stamp->>'actor' AS actor, n.stamp->>'card' AS card,
         n.seq, n.created_at, n.id
  FROM bitt.node n LEFT JOIN bitt.v_task t ON t.id = n.task;
CREATE OR REPLACE VIEW bitt.v_tag AS
  SELECT t.name AS task, bitt.name_of(n.links->>'target') AS line, n.payload->>'tag' AS tag, n.payload->>'value' AS value,
         left(n.links->>'target', 12) AS target, n.stamp->>'actor' AS by, n.created_at, n.id
  FROM bitt.node n LEFT JOIN bitt.v_task t ON t.id = n.task WHERE n.kind = 'tag';
CREATE OR REPLACE VIEW bitt.v_refusal AS
  SELECT t.name AS task, n.payload->>'card' AS card, n.payload->>'actor' AS actor, n.payload->>'reason' AS reason, n.created_at
  FROM bitt.node n LEFT JOIN bitt.v_task t ON t.id = n.task WHERE n.kind = 'refusal'
  UNION ALL
  SELECT NULL, entry->>'card', entry->>'actor', entry->>'reason', at FROM bitt.refusal_log;
CREATE OR REPLACE VIEW bitt.v_edge AS
  SELECT left(child, 12) AS child, role, left(parent, 12) AS parent, lineage FROM bitt.link;
CREATE OR REPLACE VIEW bitt.v_import AS
  SELECT n.id AS import, bitt.name_of(n.id) AS line, n.payload->>'table' AS tbl, n.payload->>'set' AS set,
         row_number() OVER (PARTITION BY bitt.line_of(n.id) ORDER BY n.seq) AS n,
         n.payload->>'origin' AS file, n.payload->>'sheet' AS sheet, n.payload->>'bytes_h' AS file_hash,
         (n.payload->>'n_rows')::int AS rows, (n.payload->>'new_rows')::int AS new_rows,
         (n.payload->>'skipped_empty')::int AS skipped_empty, n.created_at AS at
  FROM bitt.node n WHERE n.kind = 'raw';
CREATE OR REPLACE VIEW bitt.v_run AS
  SELECT r.bitt_run_hash AS run, r.kind, r.task, r.bitt_recipe_hash AS work,
         (SELECT tbl FROM bitt.set WHERE bitt_set_hash = e.out_set) AS out_table, r.input, r.rung, r.env,
         r.n_samples, r.started_at, e.finished_at, COALESCE(e.status, 'open') AS status, e.rows_total, e.made, e.reused, e.failed, e.calls,
         (SELECT count(*) FROM bitt.run_error x WHERE x.bitt_run_hash = r.bitt_run_hash) AS errors
  FROM bitt.run r LEFT JOIN bitt.run_end e USING (bitt_run_hash);

-- ============================================================ the graph as a branch tree (docs/v2/db.md §5)
-- `SELECT line FROM bitt.tree('raw/qs')`: what was made from a node (dir 'down') or what it was made from ('up'). The graph is a DAG,
-- so each node shows once, under one parent: the data it was made from (inputs, dataset, run, model) first, then another lineage
-- parent (recipe, module, …), then any other (in, subject, …); among equals the latest committed. `also` = its other parents in
-- the tree. `hide` = kinds left out with everything under them (default: the bookkeeping: events, checks, names, jobs).
CREATE OR REPLACE FUNCTION bitt.tree(ref text, dir text DEFAULT 'down', max_depth int DEFAULT 30,
                          hide text[] DEFAULT '{event,check,name,job_status,job}')
RETURNS TABLE (line text, depth int, role text, id text, kind text, label text, actor text, at timestamptz, also text[], path bigint[])
LANGUAGE sql STABLE AS $$
  WITH RECURSIVE e(a, b, role, lineage) AS (                         -- a → b, in the walking direction
    SELECT parent, child, l.role, l.lineage FROM bitt.link l WHERE dir = 'down'
    UNION ALL SELECT child, parent, l.role, l.lineage FROM bitt.link l WHERE dir = 'up'
  ), reach(id, d) AS (
    SELECT bitt.resolve(ref), 0                                      -- a name (raw/x, task/x, x@1.0), an id or a prefix
    UNION
    SELECT e.b, r.d + 1 FROM reach r JOIN e ON e.a = r.id JOIN bitt.node n ON n.id = e.b
    WHERE r.d < max_depth AND NOT n.kind = ANY(hide)
  ), best AS (SELECT reach.id, min(reach.d) AS d FROM reach WHERE reach.id IS NOT NULL GROUP BY reach.id
  ), edge AS (                                                         -- each node's tree parent (the start has none)
    SELECT DISTINCT ON (e.b) e.b AS id, e.a AS up, e.role FROM e JOIN best c ON c.id = e.b AND c.d > 0 JOIN best p ON p.id = e.a
    JOIN bitt.node pn ON pn.id = e.a
    ORDER BY e.b, CASE WHEN e.role IN ('inputs', 'dataset', 'run', 'model') THEN 0 WHEN e.lineage THEN 1 ELSE 2 END, pn.seq DESC, e.role
  ), t(id, role, depth, path) AS (
    SELECT best.id, NULL::text, 0, ARRAY[n.seq] FROM best JOIN bitt.node n USING (id) WHERE best.d = 0
    UNION ALL
    SELECT edge.id, edge.role, t.depth + 1, t.path || n.seq FROM t JOIN edge ON edge.up = t.id JOIN bitt.node n ON n.id = edge.id
  ), x AS (
    SELECT t.depth, t.role, n.id, n.kind, COALESCE(bitt.name_of(n.id), n.name, n.payload->>'card', n.payload->>'question', '') AS label,
           n.stamp->>'actor' AS actor, n.created_at AS at, t.path,
           ARRAY(SELECT e.role || ' ' || left(e.a, 12) FROM e JOIN best p ON p.id = e.a WHERE e.b = n.id AND e.a <> edge.up ORDER BY 1) AS also
    FROM t JOIN bitt.node n USING (id) LEFT JOIN edge USING (id)
  )
  SELECT repeat('  ', x.depth) || COALESCE(x.role || ' → ', '') || x.kind || CASE WHEN x.label <> '' THEN ' ' || x.label ELSE '' END
         || '  ' || left(x.id, 12), x.depth, x.role, x.id, x.kind, x.label, x.actor, x.at, x.also, x.path
  FROM x ORDER BY x.path
$$;

-- ============================================================ a task's own rows (A23): `<task>.<name>` views
-- Made rows live in `made` (one table per output contract, shared by every task); a task's rows are those its runs made or reused
-- (the members of their output sets). Every task gets a schema of its name and a view per made table. Rebuilt by the record when a
-- task is named or a made table appears (and on every open); `bitt data tables --task T` reads the same rows.
CREATE OR REPLACE FUNCTION bitt.task_views() RETURNS void LANGUAGE plpgsql AS $$
DECLARE t record; o record;
BEGIN
  FOR t IN SELECT name, target FROM bitt.v_name WHERE ns = '' AND name NOT IN ('bitt', 'raw', 'made', 'lib', 'public')
                                                  AND name NOT LIKE 'pg\_%' LOOP
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', t.name);
    FOR o IN SELECT b.name FROM bitt.table b WHERE b.schema = 'made' AND b.kind = 'output'
                                              AND to_regclass(format('made.%I', b.name || '__sets')) IS NOT NULL LOOP
      EXECUTE format('CREATE OR REPLACE VIEW %I.%I AS SELECT x.* FROM made.%I x WHERE x.bitt_row_hash IN ('
                     'SELECT s.bitt_row_hash FROM bitt.run r JOIN bitt.run_end e USING (bitt_run_hash) '
                     'JOIN bitt.set o ON o.bitt_set_hash = e.out_set '        -- a prefix set reads its parent's first k
                     'JOIN made.%I s ON s.bitt_set_hash = COALESCE(o.parent, o.bitt_set_hash) AND (o.k IS NULL OR s.ord < o.k) '
                     'WHERE r.task = %L)', t.name, o.name, o.name, o.name || '__sets', t.target);
    END LOOP;
  END LOOP;
END $$;
SELECT bitt.task_views();
