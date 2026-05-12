BEGIN;

DELETE FROM candles
WHERE timeframe = 'H3'
  AND internal_symbol IN ('XAUUSD', 'XAUEUR');

WITH priced AS (
    SELECT
        internal_symbol,
        (
            date_trunc('day', time AT TIME ZONE 'Europe/Madrid')
            + (floor(extract(hour FROM time AT TIME ZONE 'Europe/Madrid') / 3)::int * interval '3 hours')
        ) AT TIME ZONE 'Europe/Madrid' AS bucket_time,
        CASE
            WHEN bid IS NOT NULL AND bid > 0 THEN bid
            WHEN last IS NOT NULL AND last > 0 THEN last
            WHEN ask IS NOT NULL AND ask > 0 THEN ask
            ELSE NULL
        END AS price,
        COALESCE(volume, 0) AS volume_value,
        COALESCE(time_msc, (extract(epoch FROM time) * 1000)::bigint) AS sort_msc,
        time
    FROM ticks
    WHERE internal_symbol IN ('XAUUSD', 'XAUEUR')
),
ranked AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY internal_symbol, bucket_time
            ORDER BY sort_msc ASC, time ASC
        ) AS open_rank,
        row_number() OVER (
            PARTITION BY internal_symbol, bucket_time
            ORDER BY sort_msc DESC, time DESC
        ) AS close_rank
    FROM priced
    WHERE price IS NOT NULL
)
INSERT INTO candles (
    time,
    internal_symbol,
    timeframe,
    open,
    high,
    low,
    close,
    volume,
    tick_count,
    first_tick_time_msc,
    last_tick_time_msc,
    source
)
SELECT
    bucket_time,
    internal_symbol,
    'H3',
    max(price) FILTER (WHERE open_rank = 1),
    max(price),
    min(price),
    max(price) FILTER (WHERE close_rank = 1),
    sum(volume_value),
    count(*),
    min(sort_msc),
    max(sort_msc),
    'TICK_AGGREGATOR'
FROM ranked
GROUP BY internal_symbol, bucket_time
ORDER BY internal_symbol, bucket_time;

COMMIT;

SELECT
    internal_symbol,
    count(*) AS h3_candles,
    min(time AT TIME ZONE 'Europe/Madrid') AS first_madrid_time,
    max(time AT TIME ZONE 'Europe/Madrid') AS last_madrid_time
FROM candles
WHERE timeframe = 'H3'
  AND internal_symbol IN ('XAUUSD', 'XAUEUR')
GROUP BY internal_symbol
ORDER BY internal_symbol;
