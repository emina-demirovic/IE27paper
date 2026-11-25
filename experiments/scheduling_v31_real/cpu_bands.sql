CREATE TABLE band_tasks(name TEXT PRIMARY KEY, class TEXT NOT NULL CHECK(class IN ('long','medium','short')),
                        fifo_block INTEGER NOT NULL);
CREATE TABLE band_settings(no_wait_at_99 INTEGER NOT NULL);
CREATE TABLE band_dispatch(seq INTEGER PRIMARY KEY, sample_ticks INTEGER NOT NULL UNIQUE, host_percent REAL);

-- Snapshot functions are shared by the assignment guard and the audit trigger.
-- A missing reading (or gated high load) permits a FIFO restart only when idle.
DROP VIEW v2_next;
CREATE VIEW v2_next AS
WITH reading AS (
    SELECT CASE WHEN band_host() < 60 THEN 'long'
                WHEN band_host() < 87.5 THEN 'medium'
                WHEN band_host() < 99 OR (no_wait_at_99 AND band_host() IS NOT NULL)
                    THEN 'short' END AS target
    FROM band_settings
)
SELECT e.Id, t.name
FROM v2_eligible e JOIN v2_tasks t ON t.name=e.Name JOIN band_tasks b ON b.name=t.name
CROSS JOIN v2_config cfg CROSS JOIN v2_load l CROSS JOIN reading
WHERE t.p <= cfg.budget-l.reserved AND (reading.target IS NOT NULL OR l.reserved=0)
  AND band_sample() > COALESCE((SELECT MAX(sample_ticks) FROM band_dispatch),0)
ORDER BY b.fifo_block, CASE WHEN b.class=reading.target THEN 0 ELSE 1 END,
         CASE WHEN b.class=reading.target THEN t.k END DESC, t.arrival
LIMIT 1;

CREATE TRIGGER band_record AFTER INSERT ON v2_events WHEN NEW.delta>0
BEGIN
    INSERT INTO band_dispatch VALUES(NEW.seq,band_sample(),band_host());
END;
