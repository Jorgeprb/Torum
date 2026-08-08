"""Repair entry marker timestamps overwritten by close-only MT5 history.

Revision ID: 0027_trade_marker_time_fix
Revises: 0026_position_sync_capacity
"""

from alembic import op

revision = "0027_trade_marker_time_fix"
down_revision = "0026_position_sync_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A previous close reconciliation could replace open_time_msc/opened_at with
    # the close deal timestamp when the incremental MT5 history window contained
    # no entry deal. Recover only records whose opening marker is demonstrably
    # missing or not earlier than their closing marker.
    #
    # Prefer MT5's original broker-chart timestamp stored in JSON. When it is not
    # available, preserve the broker clock offset observed at close and apply it
    # to the order execution time. This keeps the marker aligned with candles
    # whose timestamps use the broker-chart domain rather than wall-clock UTC.
    op.execute(
        """
        WITH marker_repairs AS (
            SELECT
                p.id,
                COALESCE(
                    NULLIF(p.raw_payload_json -> 'resolved_position_snapshot' ->> 'time_msc', '')::bigint,
                    NULLIF(p.raw_payload_json -> 'mt5_open_position' ->> 'time_msc', '')::bigint,
                    NULLIF(o.response_payload_json -> 'resolved_position_snapshot' ->> 'time_msc', '')::bigint,
                    CASE
                        WHEN p.close_time_msc IS NOT NULL AND p.closed_at IS NOT NULL THEN
                            (EXTRACT(EPOCH FROM o.executed_at) * 1000)::bigint
                            + p.close_time_msc
                            - (EXTRACT(EPOCH FROM p.closed_at) * 1000)::bigint
                        ELSE (EXTRACT(EPOCH FROM o.executed_at) * 1000)::bigint
                    END
                ) AS recovered_open_time_msc,
                COALESCE(o.executed_price, p.open_price) AS recovered_open_price
            FROM positions p
            JOIN orders o ON o.id = p.order_id
            WHERE o.executed_at IS NOT NULL
              AND (
                    p.open_time_msc IS NULL
                    OR (p.close_time_msc IS NOT NULL AND p.open_time_msc >= p.close_time_msc)
                    OR (p.closed_at IS NOT NULL AND p.opened_at >= p.closed_at)
              )
        )
        UPDATE positions AS p
        SET
            open_time_msc = r.recovered_open_time_msc,
            opened_at = TO_TIMESTAMP(r.recovered_open_time_msc / 1000.0),
            open_price = r.recovered_open_price
        FROM marker_repairs AS r
        WHERE p.id = r.id
          AND r.recovered_open_time_msc IS NOT NULL
        """
    )


def downgrade() -> None:
    # Data repair is intentionally irreversible: restoring corrupted marker
    # timestamps would provide no useful or safe downgrade behavior.
    pass
