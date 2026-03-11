"""
飞书 Markdown 过滤工具测试。
"""

from frontend.feishu.markdown_filter import filter_markdown_for_feishu


class TestFeishuMarkdownFilter:
    def test_basic_markdown_stripped(self):
        src = "# 标题\n\n这是 **粗体** 和 *斜体* 文本。"
        out = filter_markdown_for_feishu(src)

        assert "标题" in out
        assert "**" not in out
        assert "*" not in out

    def test_links_converted_to_plain_text(self):
        src = "请查看 [文档](https://example.com/docs)。"
        out = filter_markdown_for_feishu(src)

        # 链接内容和 URL 至少应该都还在
        assert "文档" in out
        assert "https://example.com/docs" in out

    def test_multiple_empty_lines_collapsed(self):
        src = "第一段\n\n\n\n第二段"
        out = filter_markdown_for_feishu(src)

        # 最多允许 2 个连续空行
        assert "\n\n\n" not in out
