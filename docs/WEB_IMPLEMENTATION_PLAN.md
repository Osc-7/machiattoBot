# Schedule Agent Web 实现计划

## 概述

本文档详细说明如何将 Schedule Agent 从 CLI 扩展到 Web 界面，包括具体的实现步骤、代码结构和接口定义。

## 实现步骤

### Step 1: 项目结构准备

创建 Web 模块目录结构：

```
src/schedule_agent/web/
├── __init__.py
├── api.py              # REST API 路由
├── websocket.py        # WebSocket 处理器
├── session_manager.py  # 会话管理
└── models.py           # Web 层数据模型
```

### Step 2: 依赖更新

在 `requirements.txt` 中添加：

```txt
# Web 框架
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
websockets>=12.0
```

### Step 3: 会话管理器实现

**文件**: `src/schedule_agent/web/session_manager.py`

```python
"""
Web 会话管理器

管理用户会话，每个会话对应一个 ScheduleAgent 实例。
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
from schedule_agent.core import ScheduleAgent
from schedule_agent.config import get_config
from schedule_agent.core.tools import (
    ParseTimeTool, AddEventTool, AddTaskTool,
    GetEventsTool, GetTasksTool, UpdateTaskTool,
    DeleteScheduleDataTool, GetFreeSlotsTool, PlanTasksTool,
)

class WebSession:
    """Web 会话"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        
        # 创建 Agent 实例
        config = get_config()
        tools = [
            ParseTimeTool(),
            AddEventTool(),
            AddTaskTool(),
            GetEventsTool(),
            GetTasksTool(),
            UpdateTaskTool(),
            DeleteScheduleDataTool(),
            GetFreeSlotsTool(),
            PlanTasksTool(),
        ]
        self.agent = ScheduleAgent(
            config=config,
            tools=tools,
            max_iterations=config.agent.max_iterations,
            timezone=config.time.timezone,
        )
    
    def update_activity(self):
        """更新最后活动时间"""
        self.last_activity = datetime.now()
    
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """检查会话是否过期"""
        return (datetime.now() - self.last_activity).total_seconds() > timeout_minutes * 60


class SessionManager:
    """会话管理器（单例）"""
    _instance = None
    _sessions: Dict[str, WebSession] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def create_session(cls) -> WebSession:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        session = WebSession(session_id)
        cls._sessions[session_id] = session
        return session
    
    @classmethod
    def get_session(cls, session_id: str) -> Optional[WebSession]:
        """获取会话"""
        session = cls._sessions.get(session_id)
        if session and not session.is_expired():
            session.update_activity()
            return session
        elif session:
            # 删除过期会话
            del cls._sessions[session_id]
        return None
    
    @classmethod
    def get_or_create(cls, session_id: Optional[str] = None) -> WebSession:
        """获取或创建会话"""
        if session_id:
            session = cls.get_session(session_id)
            if session:
                return session
        return cls.create_session()
    
    @classmethod
    def delete_session(cls, session_id: str) -> bool:
        """删除会话"""
        if session_id in cls._sessions:
            del cls._sessions[session_id]
            return True
        return False
    
    @classmethod
    def cleanup_expired(cls):
        """清理过期会话"""
        expired_ids = [
            sid for sid, session in cls._sessions.items()
            if session.is_expired()
        ]
        for sid in expired_ids:
            del cls._sessions[sid]
        return len(expired_ids)
```

### Step 4: WebSocket 处理器实现

**文件**: `src/schedule_agent/web/websocket.py`

```python
"""
WebSocket 处理器

处理实时对话交互。
"""

import json
import asyncio
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from schedule_agent.web.session_manager import SessionManager

async def websocket_endpoint(websocket: WebSocket, session_id: Optional[str] = None):
    """
    WebSocket 端点
    
    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID（可选）
    """
    await websocket.accept()
    
    # 获取或创建会话
    session = SessionManager.get_or_create(session_id)
    
    # 发送会话 ID（如果是新创建的）
    if not session_id or session.session_id != session_id:
        await websocket.send_json({
            "type": "session_created",
            "session_id": session.session_id
        })
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            
            if data.get("type") == "message":
                user_input = data.get("content", "").strip()
                
                if not user_input:
                    await websocket.send_json({
                        "type": "error",
                        "message": "消息内容不能为空"
                    })
                    continue
                
                # 处理用户输入
                try:
                    response = await session.agent.process_input(user_input)
                    
                    # 发送响应
                    await websocket.send_json({
                        "type": "response",
                        "content": response,
                        "session_id": session.session_id,
                        "token_usage": session.agent.get_token_usage()
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"处理请求时发生错误: {str(e)}",
                        "code": "PROCESS_ERROR"
                    })
            
            elif data.get("type") == "ping":
                # 心跳检测
                await websocket.send_json({"type": "pong"})
            
            elif data.get("type") == "clear":
                # 清空对话历史
                session.agent.clear_context()
                await websocket.send_json({
                    "type": "cleared",
                    "message": "对话历史已清空"
                })
    
    except WebSocketDisconnect:
        # 客户端断开连接
        pass
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": f"连接错误: {str(e)}"
        })
    finally:
        await websocket.close()
```

### Step 5: REST API 实现

**文件**: `src/schedule_agent/web/api.py`

```python
"""
REST API 路由

提供事件、任务、会话等 RESTful API。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from schedule_agent.models import Event, Task
from schedule_agent.storage import EventRepository, TaskRepository
from schedule_agent.web.session_manager import SessionManager
from schedule_agent.config import get_config

router = APIRouter()

# 数据模型
class SessionCreate(BaseModel):
    """创建会话请求"""
    pass

class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    created_at: str
    last_activity: str
    message_count: int
    token_usage: dict

# 会话管理 API
@router.post("/sessions", response_model=dict)
async def create_session():
    """创建新会话"""
    session = SessionManager.create_session()
    return {
        "session_id": session.session_id,
        "created_at": session.created_at.isoformat()
    }

@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """获取会话信息"""
    session = SessionManager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    
    return SessionInfo(
        session_id=session.session_id,
        created_at=session.created_at.isoformat(),
        last_activity=session.last_activity.isoformat(),
        message_count=session.agent.get_turn_count(),
        token_usage=session.agent.get_token_usage()
    )

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if SessionManager.delete_session(session_id):
        return {"message": "会话已删除"}
    raise HTTPException(status_code=404, detail="会话不存在")

# 事件 API
@router.get("/events", response_model=List[dict])
async def get_events(
    query_type: str = Query("all", alias="type"),
    days: Optional[int] = Query(None, alias="days"),
    search: Optional[str] = Query(None),
):
    """获取事件列表"""
    config = get_config()
    repo = EventRepository(
        data_dir=config.storage.data_dir,
        filename=config.storage.events_file
    )
    
    if query_type == "today":
        events = repo.get_today()
    elif query_type == "upcoming":
        events = repo.get_upcoming(days or 7)
    elif query_type == "search":
        if not search:
            raise HTTPException(status_code=400, detail="搜索关键词不能为空")
        events = repo.search(search)
    else:
        events = repo.get_all()
    
    return [e.model_dump() for e in events]

@router.get("/events/{event_id}", response_model=dict)
async def get_event(event_id: str):
    """获取单个事件"""
    config = get_config()
    repo = EventRepository(
        data_dir=config.storage.data_dir,
        filename=config.storage.events_file
    )
    
    event = repo.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")
    
    return event.model_dump()

# 任务 API
@router.get("/tasks", response_model=List[dict])
async def get_tasks(
    query_type: str = Query("todo", alias="type"),
    search: Optional[str] = Query(None),
):
    """获取任务列表"""
    config = get_config()
    repo = TaskRepository(
        data_dir=config.storage.data_dir,
        filename=config.storage.tasks_file
    )
    
    if query_type == "todo":
        tasks = repo.get_todo()
    elif query_type == "completed":
        tasks = repo.get_completed()
    elif query_type == "overdue":
        tasks = repo.get_overdue()
    elif query_type == "search":
        if not search:
            raise HTTPException(status_code=400, detail="搜索关键词不能为空")
        tasks = repo.search(search)
    else:
        tasks = repo.get_all()
    
    return [t.model_dump() for t in tasks]

@router.get("/tasks/{task_id}", response_model=dict)
async def get_task(task_id: str):
    """获取单个任务"""
    config = get_config()
    repo = TaskRepository(
        data_dir=config.storage.data_dir,
        filename=config.storage.tasks_file
    )
    
    task = repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return task.model_dump()

# 统计 API
@router.get("/stats/summary")
async def get_summary():
    """获取摘要统计"""
    config = get_config()
    event_repo = EventRepository(
        data_dir=config.storage.data_dir,
        filename=config.storage.events_file
    )
    task_repo = TaskRepository(
        data_dir=config.storage.data_dir,
        filename=config.storage.tasks_file
    )
    
    return {
        "events_today": len(event_repo.get_today()),
        "events_upcoming": len(event_repo.get_upcoming(7)),
        "tasks_todo": len(task_repo.get_todo()),
        "tasks_overdue": len(task_repo.get_overdue()),
    }
```

### Step 6: Web 服务器入口

**文件**: `web_server.py`

```python
#!/usr/bin/env python3
"""
Schedule Agent Web 服务器

启动 FastAPI Web 服务器，提供 Web 界面和 API。
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from schedule_agent.web.api import router as api_router
from schedule_agent.web.websocket import websocket_endpoint

# 创建 FastAPI 应用
app = FastAPI(
    title="Schedule Agent Web",
    description="智能日程管理助手 Web 界面",
    version="0.1.0"
)

# CORS 配置（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, prefix="/api", tags=["API"])

# WebSocket 路由
app.add_websocket_route("/ws/{session_id}", websocket_endpoint)
app.add_websocket_route("/ws", websocket_endpoint)  # 无 session_id 时创建新会话

# 静态文件（开发用）
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


def main():
    """启动服务器"""
    uvicorn.run(
        "web_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式自动重载
        log_level="info"
    )


if __name__ == "__main__":
    main()
```

### Step 7: 前端实现（简单版本）

**文件**: `web/static/index.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Schedule Agent - 智能日程管理助手</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>📅 Schedule Agent</h1>
            <div class="session-info">
                <span id="session-id">会话: -</span>
                <button id="clear-btn">清空对话</button>
            </div>
        </header>
        
        <main>
            <div class="chat-container">
                <div id="messages" class="messages"></div>
                <div class="input-area">
                    <textarea id="input" placeholder="输入你的需求..."></textarea>
                    <button id="send-btn">发送</button>
                </div>
            </div>
        </main>
    </div>
    
    <script src="/js/app.js"></script>
</body>
</html>
```

**文件**: `web/static/js/app.js`

```javascript
// WebSocket 连接管理
class ChatApp {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.init();
    }
    
    init() {
        this.connect();
        this.setupEventListeners();
    }
    
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket 连接已建立');
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket 错误:', error);
            this.addMessage('系统', '连接错误，请刷新页面重试', 'error');
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket 连接已关闭');
            // 5 秒后重连
            setTimeout(() => this.connect(), 5000);
        };
    }
    
    handleMessage(data) {
        switch (data.type) {
            case 'session_created':
                this.sessionId = data.session_id;
                document.getElementById('session-id').textContent = `会话: ${data.session_id.substring(0, 8)}...`;
                break;
            
            case 'response':
                this.addMessage('助手', data.content, 'assistant');
                break;
            
            case 'error':
                this.addMessage('系统', data.message, 'error');
                break;
            
            case 'cleared':
                document.getElementById('messages').innerHTML = '';
                this.addMessage('系统', data.message, 'info');
                break;
        }
    }
    
    sendMessage(content) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            alert('连接未建立，请稍候再试');
            return;
        }
        
        this.ws.send(JSON.stringify({
            type: 'message',
            content: content,
            session_id: this.sessionId
        }));
        
        this.addMessage('你', content, 'user');
    }
    
    addMessage(sender, content, type) {
        const messagesDiv = document.getElementById('messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${type}`;
        
        messageDiv.innerHTML = `
            <div class="message-sender">${sender}</div>
            <div class="message-content">${this.escapeHtml(content)}</div>
        `;
        
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    setupEventListeners() {
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('send-btn');
        const clearBtn = document.getElementById('clear-btn');
        
        sendBtn.addEventListener('click', () => {
            const content = input.value.trim();
            if (content) {
                this.sendMessage(content);
                input.value = '';
            }
        });
        
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendBtn.click();
            }
        });
        
        clearBtn.addEventListener('click', () => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'clear' }));
            }
        });
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', () => {
    new ChatApp();
});
```

## 测试计划

### 1. 单元测试
- 会话管理器测试
- WebSocket 处理器测试
- REST API 测试

### 2. 集成测试
- WebSocket 对话流程测试
- REST API 与存储层集成测试

### 3. E2E 测试
- 浏览器自动化测试（Playwright）
- 完整用户流程测试

## 部署检查清单

- [ ] 更新 `requirements.txt`
- [ ] 创建 Web 模块目录结构
- [ ] 实现会话管理器
- [ ] 实现 WebSocket 处理器
- [ ] 实现 REST API
- [ ] 创建 Web 服务器入口
- [ ] 创建前端 HTML/JS/CSS
- [ ] 编写测试用例
- [ ] 更新文档
- [ ] 测试完整流程
