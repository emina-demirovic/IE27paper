-- The family slots and long-matrix flags are frozen before the gate opens.
CREATE TABLE family_tasks (name TEXT PRIMARY KEY, arrival INTEGER UNIQUE NOT NULL,
                           family TEXT NOT NULL, is_long INTEGER NOT NULL);
DROP VIEW v2_next;
CREATE VIEW v2_next AS
WITH slot AS (
    SELECT t.family FROM family_tasks t
    WHERE t.arrival=(SELECT COUNT(*) FROM v2_events WHERE delta>0)
), running AS (
    SELECT COUNT(*) AS long_count FROM Experiments e JOIN family_tasks f ON f.name=e.Name WHERE e.Status=1 AND f.is_long=1
)
SELECT e.Id, t.name FROM Experiments e
JOIN v2_tasks t ON t.name=e.Name
JOIN family_tasks f ON f.name=e.Name
JOIN slot ON slot.family=f.family
CROSS JOIN running CROSS JOIN v2_load l CROSS JOIN v2_capacity cfg
WHERE e.Status=0 AND t.p <= cfg.budget-l.reserved
ORDER BY CASE WHEN e.Algorithm='numeric-matmul' AND running.long_count>=2 AND f.is_long=1 THEN 1 ELSE 0 END,
         CASE WHEN e.Algorithm='numeric-matmul' AND running.long_count<2 THEN t.k ELSE 0 END DESC,
         t.arrival
LIMIT 1;
