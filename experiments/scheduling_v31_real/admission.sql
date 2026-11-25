-- Installed only in the private database of one V2 batch. The Running row
-- IS the reservation. Updating it and its audit entries is one transaction.
CREATE TABLE v2_config (budget INTEGER NOT NULL, constrained INTEGER NOT NULL, matrix_cap INTEGER);
CREATE TABLE v2_tasks (name TEXT PRIMARY KEY, arrival INTEGER UNIQUE NOT NULL,
                       k REAL NOT NULL, p INTEGER NOT NULL);
CREATE TABLE v2_events (seq INTEGER PRIMARY KEY, task TEXT NOT NULL, worker TEXT NOT NULL,
                        attempt INTEGER NOT NULL, ticks INTEGER NOT NULL, delta INTEGER NOT NULL,
                        utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));

CREATE VIEW v2_load AS
SELECT COALESCE(SUM(t.p), 0) AS reserved FROM Experiments e JOIN v2_tasks t ON t.name=e.Name
WHERE e.Status=1;

CREATE VIEW v2_capacity AS SELECT * FROM v2_config;

-- Both the scheduler read and the assignment trigger use this live count.
CREATE VIEW v2_eligible AS
SELECT e.Id, e.Name FROM Experiments e CROSS JOIN v2_config cfg
WHERE e.Status=0 AND (cfg.matrix_cap IS NULL OR e.Algorithm <> 'numeric-matmul'
    OR (SELECT COUNT(*) FROM Experiments WHERE Status=1 AND Algorithm='numeric-matmul') < cfg.matrix_cap);

CREATE VIEW v2_next AS
SELECT e.Id, t.name FROM v2_eligible e JOIN v2_tasks t ON t.name=e.Name
CROSS JOIN v2_capacity cfg CROSS JOIN v2_load l
WHERE cfg.constrained=0 OR t.p <= cfg.budget-l.reserved
ORDER BY t.k DESC, t.arrival LIMIT 1;

-- The scheduler's read is advisory. Recheck the winner, budget and worker
-- under the SQLite write lock. A losing assignment updates zero rows and
-- goes through the existing command processor's conflict/retry path.
CREATE TRIGGER v2_admit BEFORE UPDATE OF Status ON Experiments
WHEN NEW.Status=1 AND OLD.Status<>1
BEGIN
    SELECT RAISE(IGNORE) WHERE NEW.Id IS NOT (SELECT Id FROM v2_next)
        OR EXISTS (SELECT 1 FROM Experiments WHERE Status=1 AND AssignedWorkerId=NEW.AssignedWorkerId);
END;
CREATE TRIGGER v2_reserve AFTER UPDATE OF Status ON Experiments
WHEN NEW.Status=1 AND OLD.Status<>1
BEGIN
    INSERT INTO v2_events(task,worker,attempt,ticks,delta)
    SELECT NEW.Name,NEW.AssignedWorkerId,NEW.Attempt,v2_ticks(),p FROM v2_tasks WHERE name=NEW.Name;
END;
-- Includes successful, failed, cancelled, and requeued attempts. A request
-- to cancel a still-running job keeps its reservation until the attempt ends.
CREATE TRIGGER v2_release AFTER UPDATE OF Status ON Experiments
WHEN OLD.Status=1 AND NEW.Status<>1
BEGIN
    INSERT INTO v2_events(task,worker,attempt,ticks,delta)
    SELECT OLD.Name,OLD.AssignedWorkerId,OLD.Attempt,v2_ticks(),-p FROM v2_tasks WHERE name=OLD.Name;
END;

-- Preserve the outcome of each reservation in case the benchmark is interrupted
-- or the coordinator requeues a task before the final report is written.
CREATE TABLE v2_outcomes(task TEXT, attempt INTEGER, status INTEGER, duration_ms INTEGER,
                         PRIMARY KEY(task, attempt));
CREATE TRIGGER v2_outcome AFTER UPDATE OF Status ON Experiments
WHEN OLD.Status=1 AND NEW.Status<>1
BEGIN
    INSERT INTO v2_outcomes VALUES(OLD.Name, OLD.Attempt, NEW.Status, NEW.ExecutionDurationMs);
END;
