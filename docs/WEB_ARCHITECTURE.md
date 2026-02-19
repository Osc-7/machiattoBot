# Schedule Agent Web 架构设计

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层 (Frontend)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  对话界面     │  │  日程视图     │  │  任务视图     │     │
│  │  (Chat UI)   │  │ (Calendar)   │  │  (Tasks)     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                  │                  │           │
│         └──────────────────┴──────────────────┘           │
│                        WebSocket / HTTP                    │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                     后端 API 层 (Backend)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  WebSocket   │  │   REST API   │  │  Static      │     │
│  │   Handler    │  │   Endpoints  │  │  Files       │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                  │                  │           │
│         └──────────────────┴──────────────────┘           │
│                        FastAPI Router                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                   业务逻辑层 (Business Logic)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ ScheduleAgent│  │  Tool        │  │  Context     │     │
│  │   (Core)     │  │  Registry    │  │  Manager     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                  │                  │           │
│         └──────────────────┴──────────────────┘           │
│                   现有核心模块 (Existing)                  │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                      数据层 (Data Layer)                     │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Event        │  │ Task         │                        │
│  │ Repository   │  │ Repository   │                        │
│  └──────────────┘  └──────────────┘                        │
│         │                  │                                 │
│         └──────────────────┘                                 │
│                    JSON Storage (Existing)                   │
└───────────────────────────────────────────────────────────────┘
```

## 2. 技术栈选择

### 2.1 后端
- **框架**: FastAPI（异步、高性能、自动 API 文档）
- **WebSocket**: FastAPI WebSocket 支持（实时对话）
- **CORS**: 支持跨域请求
- **静态文件**: FastAPI StaticFiles（开发阶段）

### 2.2 前端
- **方案 A（推荐）**: 原生 HTML + Vanilla JS + Tailwind CSS
  - 轻量级，无需构建工具
  - 快速开发，易于维护
  - 适合中小型应用
  
- **方案 B（可选）**: React + Vite + Tailwind CSS
  - 组件化开发
  - 更好的状态管理
  - 适合复杂交互

### 2.3 实时通信
- **WebSocket**: 用于对话交互（支持流式响应）
- **HTTP SSE**: 备选方案（Server-Sent Events，单向流）

## 3. 目录结构

```
/work
├── src/
│   └── schedule_agent/
│       ├── web/                    # 新增 Web 模块
│       │   ├── __init__.py
│       │   ├── api.py              # REST API 路由
│       │   ├── websocket.py        # WebSocket 处理器
│       │   ├── session_manager.py  # 会话管理（多用户支持）
│       │   └── static/             # 静态文件（开发用）
│       │       ├── index.html
│       │       ├── css/
│       │       │   └── style.css
│       │       ├── js/
│       │       │   ├── app.js      # 主应用逻辑
│       │       │   ├── chat.js     # 对话功能
│       │       │   ├── calendar.js # 日程视图
│       │       │   └── tasks.js    # 任务视图
│       │       └── assets/
│       └── ...                     # 现有模块
├── web_server.py                   # Web 服务器入口
├── requirements.txt                # 更新依赖
└── docs/
    └── WEB_ARCHITECTURE.md         # 本文档
```

## 4. API 设计

### 4.1 REST API Endpoints

#### 4.1.1 日程相关
```
GET    /api/events                    # 获取事件列表（支持查询参数）
GET    /api/events/{event_id}         # 获取单个事件
POST   /api/events                    # 创建事件（直接 API，不通过 Agent）
PUT    /api/events/{event_id}          # 更新事件
DELETE /api/events/{event_id}          # 删除事件
```

#### 4.1.2 任务相关
```
GET    /api/tasks                     # 获取任务列表
GET    /api/tasks/{task_id}           # 获取单个任务
POST   /api/tasks                     # 创建任务
PUT    /api/tasks/{task_id}           # 更新任务
DELETE /api/tasks/{task_id}           # 删除任务
```

#### 4.1.3 会话管理
```
POST   /api/sessions                  # 创建新会话
GET    /api/sessions/{session_id}     # 获取会话信息
DELETE /api/sessions/{session_id}     # 删除会话
GET    /api/sessions/{session_id}/history  # 获取对话历史
```

#### 4.1.4 统计信息
```
GET    /api/stats/token-usage         # Token 用量统计
GET    /api/stats/summary              # 日程/任务摘要
```

### 4.2 WebSocket API

#### 4.2.1 连接
```
ws://localhost:8000/ws/{session_id}
```

#### 4.2.2 消息格式

**客户端 → 服务器**:
```json
{
  "type": "message",
  "content": "明天下午3点有个会议",
  "session_id": "uuid-here"
}
```

**服务器 → 客户端**:
```json
{
  "type": "response",
  "content": "已为您添加会议...",
  "session_id": "uuid-here",
  "timestamp": "2026-02-19T10:30:00Z"
}
```

**工具调用进度**（可选）:
```json
{
  "type": "tool_call",
  "tool_name": "add_event",
  "status": "executing",
  "result": null
}
```

**流式响应**（逐字输出）:
```json
{
  "type": "stream",
  "chunk": "已",
  "done": false
}
```

**错误**:
```json
{
  "type": "error",
  "message": "处理请求时发生错误",
  "code": "PROCESS_ERROR"
}
```

## 5. 会话管理

### 5.1 会话生命周期
1. **创建**: 用户首次访问时创建会话 ID（UUID）
2. **存储**: 会话 ID → ScheduleAgent 实例映射（内存或 Redis）
3. **过期**: 30 分钟无活动自动清理
4. **持久化**: 可选，将会话历史存储到数据库

### 5.2 会话状态
```python
class WebSession:
    session_id: str
    agent: ScheduleAgent
    created_at: datetime
    last_activity: datetime
    message_count: int
    token_usage: TokenUsage
```

## 6. 前端功能模块

### 6.1 对话界面（Chat UI）
- **输入框**: 支持多行输入，快捷键发送（Enter/Ctrl+Enter）
- **消息列表**: 
  - 用户消息（右侧，蓝色）
  - 助手消息（左侧，灰色）
  - 工具调用提示（中间，黄色）
- **流式显示**: 逐字显示 LLM 响应
- **历史记录**: 滚动加载历史消息

### 6.2 日程视图（Calendar）
- **日历组件**: 月视图/周视图/日视图
- **事件展示**: 
  - 时间轴显示
  - 颜色编码（优先级）
  - 拖拽调整时间（可选）
- **快速操作**: 点击日期快速添加事件

### 6.3 任务视图（Tasks）
- **任务列表**: 
  - 待办/进行中/已完成/已过期
  - 优先级排序
  - 标签筛选
- **任务卡片**: 
  - 标题、描述、截止日期
  - 预计时长
  - 快速操作（完成/删除）

### 6.4 侧边栏（Sidebar）
- **会话管理**: 新建/切换/删除会话
- **快捷命令**: 常用操作按钮
- **统计信息**: Token 用量、今日事件数等

## 7. 安全考虑

### 7.1 认证授权（可选）
- **方案 A**: 无认证（单用户本地使用）
- **方案 B**: 简单 Token 认证
- **方案 C**: OAuth2（多用户）

### 7.2 输入验证
- 限制消息长度（如 2000 字符）
- 防止 XSS（前端转义 + 后端验证）
- 防止 SQL 注入（使用参数化查询，虽然当前是 JSON 存储）

### 7.3 速率限制
- WebSocket: 每会话每秒最多 10 条消息
- REST API: 每分钟最多 100 请求

## 8. 性能优化

### 8.1 前端
- **懒加载**: 日历/任务列表分页加载
- **虚拟滚动**: 长消息列表使用虚拟滚动
- **缓存**: 本地存储会话历史（localStorage）
- **防抖**: 输入框防抖，减少无效请求

### 8.2 后端
- **连接池**: LLM 客户端连接复用
- **异步处理**: 所有 I/O 操作异步
- **缓存**: 常用查询结果缓存（如今日事件）
- **压缩**: Gzip 压缩响应

## 9. 部署方案

### 9.1 开发环境
```bash
# 启动 Web 服务器
python web_server.py

# 访问
http://localhost:8000
```

### 9.2 生产环境
- **反向代理**: Nginx
- **进程管理**: Gunicorn + Uvicorn workers
- **静态文件**: Nginx 直接服务（或 CDN）
- **HTTPS**: Let's Encrypt 证书

## 10. 开发优先级

### Phase 1: 基础功能（MVP）
1. ✅ FastAPI 服务器框架
2. ✅ WebSocket 对话接口
3. ✅ 简单 HTML 对话界面
4. ✅ 会话管理（单会话）

### Phase 2: 核心功能
5. ⬜ REST API（事件/任务 CRUD）
6. ⬜ 日程日历视图
7. ⬜ 任务列表视图
8. ⬜ 流式响应支持

### Phase 3: 增强功能
9. ⬜ 多会话支持
10. ⬜ 工具调用进度显示
11. ⬜ 消息历史持久化
12. ⬜ 响应式设计（移动端）

### Phase 4: 优化与扩展
13. ⬜ 性能优化
14. ⬜ 错误处理完善
15. ⬜ 用户认证（如需要）
16. ⬜ 国际化（i18n）

## 11. 技术决策说明

### 11.1 为什么选择 FastAPI？
- ✅ 异步支持，与现有代码兼容
- ✅ 自动生成 API 文档（Swagger）
- ✅ 类型提示支持，代码更安全
- ✅ 性能优秀（基于 Starlette）

### 11.2 为什么选择 WebSocket？
- ✅ 实时双向通信
- ✅ 支持流式响应（逐字输出）
- ✅ 减少 HTTP 请求开销
- ✅ 更好的用户体验

### 11.3 为什么前端用原生 JS？
- ✅ 无需构建工具，快速开发
- ✅ 包体积小，加载快
- ✅ 易于理解和维护
- ✅ 适合中小型应用

## 12. 示例代码结构

### 12.1 Web 服务器入口（web_server.py）
```python
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from schedule_agent.web.api import router as api_router
from schedule_agent.web.websocket import websocket_endpoint

app = FastAPI(title="Schedule Agent Web")
app.include_router(api_router, prefix="/api")
app.add_websocket_route("/ws/{session_id}", websocket_endpoint)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

### 12.2 WebSocket 处理器（websocket.py）
```python
from fastapi import WebSocket
from schedule_agent.core import ScheduleAgent
from schedule_agent.web.session_manager import SessionManager

async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = SessionManager.get_or_create(session_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            if data["type"] == "message":
                response = await session.agent.process_input(data["content"])
                await websocket.send_json({
                    "type": "response",
                    "content": response
                })
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        await websocket.close()
```

## 13. 后续扩展

- **移动端**: PWA（Progressive Web App）支持
- **通知**: Web Push 通知（事件提醒）
- **导入导出**: 支持 iCal、CSV 格式
- **协作**: 多用户共享日程（需要后端扩展）
- **AI 增强**: 语音输入、图片识别等
