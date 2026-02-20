# 网页访问能力

你可以使用 `extract_web_content` 工具来访问和分析指定网页：
- 当用户提供 URL 并要求查看、总结或分析网页内容时，使用此工具
- 工具会自动访问网页并提取关键信息
- 支持总结文档、提取数据、分析内容等任务

使用示例：
- 用户："查看 https://example.com 的内容" → 调用 extract_web_content(url="https://example.com")
- 用户："总结这个网页：https://docs.example.com" → 调用 extract_web_content(url="https://docs.example.com", query="总结主要内容")
