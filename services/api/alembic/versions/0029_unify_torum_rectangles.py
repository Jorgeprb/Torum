"""Unify manual zones into the standard rectangle drawing.

Revision ID: 0029_unify_torum_rectangles
Revises: 0028_entry_spacing_guard
"""

from alembic import op

revision = "0029_unify_torum_rectangles"
down_revision = "0028_entry_spacing_guard"
branch_labels = None
depends_on = None

# Open-ended legacy manual zones did not require a time2.  Standard rectangles
# do, so keep their old "extends forever" semantics with a far-future boundary
# rather than truncating a user's trading zone during migration.
_OPEN_ENDED_RECTANGLE_TIME2 = 32_503_680_000  # 3000-01-01T00:00:00Z


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE chart_drawings
        SET
            drawing_type = 'rectangle',
            payload_json = jsonb_strip_nulls(
                jsonb_build_object(
                    'time1', payload_json::jsonb -> 'time1',
                    'time2', CASE
                        WHEN payload_json::jsonb ->> 'time2' IS NULL
                            THEN to_jsonb({_OPEN_ENDED_RECTANGLE_TIME2}::bigint)
                        ELSE payload_json::jsonb -> 'time2'
                    END,
                    'price1', payload_json::jsonb -> 'price_min',
                    'price2', payload_json::jsonb -> 'price_max',
                    'label', COALESCE(
                        payload_json::jsonb -> 'label',
                        to_jsonb(COALESCE(NULLIF(name, ''), 'Rectangle')::text)
                    )
                )
            )::json,
            metadata_json = (
                COALESCE(metadata_json::jsonb, '{{}}'::jsonb)
                || jsonb_build_object(
                    'legacy_manual_zone_migrated', true,
                    'legacy_manual_zone_open_ended', (payload_json::jsonb ->> 'time2') IS NULL
                )
            )::json,
            revision = revision + 1
        WHERE drawing_type = 'manual_zone'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE chart_drawings
        SET
            drawing_type = 'manual_zone',
            payload_json = jsonb_build_object(
                'time1', payload_json::jsonb -> 'time1',
                'time2', CASE
                    WHEN COALESCE((metadata_json::jsonb ->> 'legacy_manual_zone_open_ended')::boolean, false)
                        THEN 'null'::jsonb
                    ELSE payload_json::jsonb -> 'time2'
                END,
                'price_min', payload_json::jsonb -> 'price1',
                'price_max', payload_json::jsonb -> 'price2',
                'direction', to_jsonb(COALESCE(metadata_json::jsonb ->> 'direction', 'BUY')::text),
                'label', COALESCE(payload_json::jsonb -> 'label', '"Manual zone"'::jsonb),
                'rules', '{}'::jsonb,
                'metadata', '{}'::jsonb
            )::json,
            metadata_json = (
                COALESCE(metadata_json::jsonb, '{}'::jsonb)
                - 'legacy_manual_zone_migrated'
                - 'legacy_manual_zone_open_ended'
            )::json,
            revision = revision + 1
        WHERE drawing_type = 'rectangle'
          AND COALESCE((metadata_json::jsonb ->> 'legacy_manual_zone_migrated')::boolean, false)
        """
    )
