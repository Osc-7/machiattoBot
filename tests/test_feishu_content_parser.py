"""飞书内容解析器测试。"""

from __future__ import annotations

from agent.content import ContentReference
from agent.frontend.feishu.content_parser import parse_feishu_message


def test_parse_text_message():
    refs, text = parse_feishu_message(
        message_id="om_1",
        message_type="text",
        content='{"text":"明天早上8点开会"}',
    )
    assert refs == []
    assert text == "明天早上8点开会"


def test_parse_image_message():
    refs, text = parse_feishu_message(
        message_id="om_2",
        message_type="image",
        content='{"image_key":"img_xxx"}',
    )
    assert len(refs) == 1
    assert refs[0].source == "feishu"
    assert refs[0].ref_type == "image"
    assert refs[0].key == "img_xxx"
    assert refs[0].extra == {"message_id": "om_2"}
    assert text == "[用户发送了一张图片]"


def test_parse_media_message():
    refs, text = parse_feishu_message(
        message_id="om_3",
        message_type="media",
        content='{"file_key":"file_abc","image_key":"img_xyz","file_name":"vid.mp4","duration":2000}',
    )
    assert len(refs) == 1
    assert refs[0].source == "feishu"
    assert refs[0].ref_type == "video"
    assert refs[0].key == "file_abc"
    assert refs[0].extra == {"message_id": "om_3"}
    assert text == "[用户发送了一段视频]"
