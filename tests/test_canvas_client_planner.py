"""Tests for CanvasClient.get_planner_items and CanvasPlannerItem."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import pytest

from canvas_integration.config import CanvasConfig
from canvas_integration.client import CanvasClient
from canvas_integration.models import CanvasPlannerItem


class _TestCanvasClient(CanvasClient):
    """CanvasClient subclass that stubs request() for testing planner items."""

    def __init__(self, config: CanvasConfig, stub_data: List[Dict[str, Any]]):
        super().__init__(config)
        self._stub_data = stub_data

    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        # We only care about /planner/items in this test.
        assert method == "GET"
        assert endpoint == "/planner/items"
        assert isinstance(params, dict)
        # Ensure start_date/end_date are set
        assert "start_date" in params
        assert "end_date" in params
        return self._stub_data


@pytest.mark.asyncio
async def test_get_planner_items_parses_basic_fields():
    """CanvasClient.get_planner_items should parse core fields into CanvasPlannerItem."""
    stub = [
        {
            "plannable_id": 101,
            "plannable_type": "assignment",
            "new_activity": True,
            "context_type": "course",
            "course_id": 42,
            "plannable": {
                "id": 101,
                "title": "HW1",
                "course_id": 42,
                "course_name": "SE101",
                "due_at": "2026-03-02T16:00:00Z",
                "html_url": "https://canvas.example/courses/42/assignments/101",
            },
            "planner_override": {
                "marked_complete": False,
                "dismissed": False,
            },
            "html_url": "https://canvas.example/courses/42/assignments/101",
        }
    ]

    cfg = CanvasConfig(api_key="x" * 24, base_url="https://canvas.example/api/v1")
    client = _TestCanvasClient(cfg, stub_data=stub)

    items = await client.get_planner_items(start_date="2026-03-01", end_date="2026-03-07")
    assert len(items) == 1

    item = items[0]
    assert isinstance(item, CanvasPlannerItem)
    assert item.plannable_id == 101
    assert item.plannable_type == "assignment"
    assert item.title == "HW1"
    assert item.course_id == 42
    assert item.course_name == "SE101"
    assert item.context_type == "course"
    assert item.html_url.endswith("/assignments/101")
    assert item.new_activity is True
    assert item.marked_complete is False
    assert item.dismissed is False
    assert isinstance(item.due_at, datetime)
    assert item.due_at.tzinfo is not None
    assert item.due_at.tzinfo == timezone.utc

    d = item.to_dict()
    assert d["plannable_id"] == 101
    assert d["title"] == "HW1"
    assert d["course_id"] == 42
    assert d["due_at"] is not None

