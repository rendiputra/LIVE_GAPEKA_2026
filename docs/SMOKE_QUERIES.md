# Smoke queries

All three run against `data/gapeka.db` after `python -m pipeline.build_db`.

## 1. The full stop list of KA 249

```sql
SELECT s.seq, s.station_code, st.name, s.arrive, s.depart, s.day_offset, s.stop_type
FROM stop_times s
JOIN trips t   ON t.trip_id = s.trip_id
JOIN stations st ON st.code = s.station_code
WHERE t.train_no = '249'
ORDER BY s.seq;
```

Expected: 20 rows, SMC (08:40) to BB (11:03), with `pass` rows for the `Ls`
stations.

## 2. All trips through a station in a time window

```sql
SELECT t.train_no, s.arrive, s.depart, t.book
FROM stop_times s
JOIN trips t ON t.trip_id = s.trip_id
WHERE s.station_code = 'TG'
  AND (s.arrive IS NOT NULL AND s.arrive BETWEEN '10:00:00' AND '14:00:00')
ORDER BY s.arrive;
```

Swap `'TG'` for any code; the window is station-local time.

## 3. Trips with day_offset >= 1

```sql
SELECT t.train_no, t.book, COUNT(*) AS late_rows
FROM stop_times s
JOIN trips t ON t.trip_id = s.trip_id
WHERE s.day_offset >= 1
GROUP BY t.trip_id
ORDER BY late_rows DESC;
```

Lists trains that cross midnight, which is what Phase 5 must handle.
