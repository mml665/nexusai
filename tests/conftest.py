"""Test fixtures for NexusAI."""
import sys
import os
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure services/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))


@pytest.fixture
def sample_reading():
    """A normal sensor reading."""
    return {
        "device_id": "CNC-A01",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sensors": {
            "temperature": 45.0,
            "vibration": 0.15,
            "spindle_speed": 3000,
            "cutting_force": 120,
        },
        "status": "running",
    }


@pytest.fixture
def abnormal_reading():
    """A sensor reading with abnormal values."""
    return {
        "device_id": "CNC-A01",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sensors": {
            "temperature": 95.0,  # way above threshold
            "vibration": 0.85,    # bearing wear level
            "spindle_speed": 3000,
            "cutting_force": 120,
        },
        "status": "running",
    }


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    r = AsyncMock()
    r.xadd = AsyncMock()
    r.xack = AsyncMock()
    r.xreadgroup = AsyncMock(return_value=[])
    r.publish = AsyncMock()
    r.xgroup_create = AsyncMock()
    r.pubsub = MagicMock()
    return r


@pytest.fixture
def mock_pool():
    """Mock asyncpg pool."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    pool.acquire = MagicMock(return_value=AsyncContextManager(conn))
    return pool


class AsyncContextManager:
    """Simple async context manager for mocking."""
    def __init__(self, value):
        self.value = value
    async def __aenter__(self):
        return self.value
    async def __aexit__(self, *args):
        pass
