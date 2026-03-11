"""内容解析器模块测试。"""

from __future__ import annotations


import pytest

from agent_core.content import resolve_content_refs
from agent_core.content.models import ContentReference as CR


class TestContentReference:
    def test_to_dict(self):
        r = CR(source="local", ref_type="image", key="a.png")
        d = r.to_dict()
        assert d["source"] == "local"
        assert d["ref_type"] == "image"
        assert d["key"] == "a.png"

    def test_from_dict(self):
        d = {
            "source": "feishu",
            "ref_type": "image",
            "key": "img_xxx",
            "extra": {"message_id": "om_1"},
        }
        r = CR.from_dict(d)
        assert r.source == "feishu"
        assert r.ref_type == "image"
        assert r.key == "img_xxx"
        assert r.extra == {"message_id": "om_1"}

    def test_from_dict_content_reference(self):
        r0 = CR(source="local", ref_type="image", key="x.png")
        r1 = CR.from_dict(r0)
        assert r0 is r1


@pytest.mark.asyncio
async def test_resolve_local_content_ref_nonexistent():
    refs = [CR(source="local", ref_type="image", key="nonexistent_file_xyz.png")]
    items = await resolve_content_refs(refs)
    assert items == []


@pytest.mark.asyncio
async def test_resolve_local_content_ref_existent(tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
    refs = [CR(source="local", ref_type="image", key=str(img))]
    items = await resolve_content_refs(refs)
    assert len(items) == 1
    assert items[0]["type"] == "image_url"
    assert "data:image/png;base64," in items[0]["image_url"]["url"]
