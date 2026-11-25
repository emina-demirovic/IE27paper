-- Installed only in the private database of one V2 batch. The Running row
-- IS the reservation. Updating it and its audit entries is one transaction.
CREATE TABLE v2_config (budget INTEGER NOT NULL, constrained INTEGER NOT NULL);
CREATE TABLE v2_tasks (name TEXT PRIMARY KEY, arrival INTEGER UNIQUE NOT NULL,
                       k REAL NOT NULL, p INTEGER NOT NULL);
CREATE TABLE v2_events (seq INTEGER PRIMARY KEY, task TEXT NOT NULL, worker TEXT NOT NULL,
                        attempt INTEGER NOT NULL, ticks INTEGER NOT NULL, delta INTEGER NOT NULL);

CREATE VIEW v2_load AS
SELECT COALESCE(SUM(t.p), 0) AS reserved FROM Experiments e JOIN v2_tasks t ON t.name=e.Name
WHERE e.Status=1;

CREATE VIEW v2_capacity AS SELECT * FROM v2_config;

CREATE VIEW v2_next AS
SELECT e.Id, t.name FROM Experiments e JOIN v2_tasks t ON t.name=e.Name
CROSS JOIN v2_capacity cfg CROSS JOIN v2_load l
WHERE e.Status=0 AND (cfg.constrained=0 OR t.p <= cfg.budget-l.reserved)
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
