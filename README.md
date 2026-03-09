# 语音聊天项目

一个基于 FastAPI + React (Vite) 的语音/文字聊天原型，支持文本流式回复、语音上传转写、历史会话与 TTS 播放。

## 后端模块结构
- `backend/main.py`：入口层（FastAPI app 初始化与 include_router）
- `backend/routes_*.py`：路由层（仅做请求/响应编排与调用 service）
- `backend/*_service.py`：业务层（尽量返回普通 Python 数据）
- `backend/config.py` / `backend/models.py` / `backend/storage_utils.py` / `backend/utils.py`：基础支撑层

## 启动方式
### 后端
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### 前端
```bash
cd frontend
npm install
npm run dev
```
浏览器访问：
```
http://127.0.0.1:5173
```

## Smoke Test
在仓库根目录运行：
```powershell
.\backend\smoke_test.ps1
```
如需指定后端地址：
```powershell
$env:SMOKE_BASE_URL="http://127.0.0.1:8001"
.\backend\smoke_test.ps1
```

## 前后端联调最小说明
1. 启动后端（8001）。
2. 启动前端（5173）。
3. 前端通过 Vite 代理转发 `/chat`、`/sessions`、`/audio`、`/download`、`/health`、`/audio-registry`、`/tts` 到后端。
4. 打开前端页面发送文本/语音，确认回复与 TTS 播放正常。
