-- check: outside-recovery
SELECT json_build_object(
  'event', 'check',
  'name', 'outside-recovery',
  'result', CASE WHEN pg_is_in_recovery() THEN 'FAIL' ELSE 'PASS' END,
  'observed', json_build_object('pgIsInRecovery', pg_is_in_recovery())
)::text;

-- check: known-row-readable
SELECT json_build_object(
  'event', 'check',
  'name', 'known-row-readable',
  'result', CASE WHEN count(*) = 1 AND min(marker) = 'ok-145-real-backup' THEN 'PASS' ELSE 'FAIL' END,
  'observed', json_build_object('matchingRows', count(*), 'marker', coalesce(min(marker), '<missing>'))
)::text
FROM restore_probe
WHERE id = 145;

-- check: restore-probe-heap-readable
SELECT json_build_object(
  'event', 'check',
  'name', 'restore-probe-heap-readable',
  'result', CASE WHEN count(*) = 1 AND min(id) = 145 AND max(id) = 145 THEN 'PASS' ELSE 'FAIL' END,
  'observed', json_build_object('rowCount', count(*), 'minimumId', min(id), 'maximumId', max(id))
)::text
FROM restore_probe;

-- check: primary-key-index-readable
BEGIN;
SET LOCAL enable_seqscan = off;
SELECT json_build_object(
  'event', 'check',
  'name', 'primary-key-index-readable',
  'result', CASE
    WHEN count(*) = 1 AND bool_and(index_valid) AND bool_and(index_ready) THEN 'PASS'
    ELSE 'FAIL'
  END,
  'observed', json_build_object(
    'matchingRows', count(*),
    'indexName', coalesce(min(index_name), '<missing>'),
    'indexValid', coalesce(bool_and(index_valid), false),
    'indexReady', coalesce(bool_and(index_ready), false)
  )
)::text
FROM (
  SELECT p.id,
         i.relname AS index_name,
         x.indisvalid AS index_valid,
         x.indisready AS index_ready
  FROM restore_probe AS p
  JOIN pg_index AS x ON x.indrelid = 'restore_probe'::regclass AND x.indisprimary
  JOIN pg_class AS i ON i.oid = x.indexrelid
  WHERE p.id = 145 AND p.marker = 'ok-145-real-backup'
) AS indexed_probe;
ROLLBACK;
