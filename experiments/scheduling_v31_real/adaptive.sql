-- The same v2_next view and assignment triggers consult this capacity view.
CREATE TABLE v31_dispatch(seq INTEGER PRIMARY KEY, effective INTEGER, fallback TEXT, solo INTEGER);

CREATE VIEW v31_limits AS
SELECT cfg.budget AS base, v31_effective() AS effective, l.reserved,
    (SELECT MIN(t.p) FROM Experiments e JOIN v2_tasks t ON t.name=e.Name WHERE e.Status=0) AS smallest,
    COALESCE((SELECT ticks FROM v2_events ORDER BY seq DESC LIMIT 1),0) AS last_change
FROM v2_config cfg CROSS JOIN v2_load l;

DROP VIEW v2_capacity;
CREATE VIEW v2_capacity AS
SELECT 1 AS constrained, CASE
    WHEN reserved=0 AND smallest>effective AND v31_grace_elapsed(smallest,last_change) THEN base
    WHEN reserved>0 AND EXISTS (
        SELECT 1 FROM v31_dispatch d JOIN v2_events ev USING(seq)
        JOIN Experiments e ON e.Name=ev.task AND e.Attempt=ev.attempt
        WHERE d.solo=1 AND e.Status=1) THEN 0
    ELSE effective END AS budget FROM v31_limits;

CREATE TRIGGER v31_record AFTER INSERT ON v2_events WHEN NEW.delta>0
BEGIN
    INSERT INTO v31_dispatch VALUES(NEW.seq,v31_effective(),v31_fallback(),NEW.delta>v31_effective());
END;

-- Observe an actual idle-worker poll where fixed capacity could dispatch.
CREATE VIEW v31_poll AS
SELECT (SELECT name FROM v2_next) AS Name,
    (SELECT t.name FROM v2_eligible e JOIN v2_tasks t ON t.name=e.Name
     WHERE t.p<=cfg.budget-l.reserved ORDER BY t.k DESC,t.arrival LIMIT 1) AS Fixed,
    (SELECT COALESCE(MAX(seq),0) FROM v2_events) AS Seq, v31_fallback() AS Fallback
FROM v2_config cfg CROSS JOIN v2_load l;
