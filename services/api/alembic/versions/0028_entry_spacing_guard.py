"""Enable pyramiding and reserve the third Torum entry by price spacing.

Revision ID: 0028_entry_spacing_guard
Revises: 0027_trade_marker_time_fix
"""

from alembic import op

revision = "0028_entry_spacing_guard"
down_revision = "0027_trade_marker_time_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The previous active config captured in production had
    # one_position_per_symbol=true, which stopped the strategy before it could
    # evaluate a second valid pullback.  The requested accumulation behaviour
    # needs that legacy guard disabled; total exposure remains bounded by
    # max_equivalent_positions and the risk planner.
    op.execute(
        """
        UPDATE strategy_configs
        SET params_json = (
            jsonb_set(
                jsonb_set(
                    jsonb_set(
                        COALESCE(params_json::jsonb, '{}'::jsonb),
                        '{one_position_per_symbol}',
                        'false'::jsonb,
                        true
                    ),
                    '{third_entry_spacing_enabled}',
                    'true'::jsonb,
                    true
                ),
                '{third_entry_min_distance_pct}',
                '0.20'::jsonb,
                true
            )
        )::json
        WHERE strategy_key = 'torum_v1'
        """
    )
    op.execute(
        """
        UPDATE strategy_definitions
        SET default_params_json = (
            jsonb_set(
                jsonb_set(
                    jsonb_set(
                        COALESCE(default_params_json::jsonb, '{}'::jsonb),
                        '{one_position_per_symbol}',
                        'false'::jsonb,
                        true
                    ),
                    '{third_entry_spacing_enabled}',
                    'true'::jsonb,
                    true
                ),
                '{third_entry_min_distance_pct}',
                '0.20'::jsonb,
                true
            )
        )::json
        WHERE key = 'torum_v1'
        """
    )


def downgrade() -> None:
    # Keep one_position_per_symbol=false: its previous value cannot be inferred
    # safely.  Only remove the newly introduced spacing options.
    op.execute(
        """
        UPDATE strategy_configs
        SET params_json = ((COALESCE(params_json::jsonb, '{}'::jsonb)
            - 'third_entry_spacing_enabled'
            - 'third_entry_min_distance_pct'))::json
        WHERE strategy_key = 'torum_v1'
        """
    )
    op.execute(
        """
        UPDATE strategy_definitions
        SET default_params_json = ((COALESCE(default_params_json::jsonb, '{}'::jsonb)
            - 'third_entry_spacing_enabled'
            - 'third_entry_min_distance_pct'))::json
        WHERE key = 'torum_v1'
        """
    )
