"""Test defaults for local collection.

Production configuration still comes from environment variables.  These values only
make imports deterministic when pytest is run from a clean checkout.
"""
from __future__ import annotations

import os

_DEFAULTS = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": "sqlite+pysqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379/15",
    "JWT_SECRET_KEY": "test-only-jwt-secret-change-me",
    "INITIAL_ADMIN_USERNAME": "admin",
    "INITIAL_ADMIN_EMAIL": "admin@example.com",
    "INITIAL_ADMIN_PASSWORD": "test-admin-password",
    "INITIAL_TRADER_USERNAME": "trader",
    "INITIAL_TRADER_EMAIL": "trader@example.com",
    "INITIAL_TRADER_PASSWORD": "test-trader-password",
    "INTERNAL_AUTH_REQUIRED": "false",
    "TORUM_SERVICE_TOKEN": "",
    "RUN_INTERNAL_SCHEDULERS": "false",
    "RISK_USE_MT5_PROFIT_CALIBRATION": "false",
}

for _name, _value in _DEFAULTS.items():
    os.environ.setdefault(_name, _value)
