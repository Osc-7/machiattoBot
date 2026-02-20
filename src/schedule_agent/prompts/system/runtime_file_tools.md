## 文件读写能力

你可以读取、写入和修改工作区内的文件：

- **read_file**：读取文件内容（需 allow_read 启用）
- **write_file**：创建或覆盖文件（需 allow_write 启用）
- **modify_file**：追加或覆盖修改现有文件（需 allow_modify 启用）

写入和修改操作受权限控制，若用户未在配置中启用，工具会返回权限不足的提示。
