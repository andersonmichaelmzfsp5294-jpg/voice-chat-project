# 语音聊天项目

一个基于 FastAPI + React (Vite) 的语音/文字聊天原型，支持：
- 文字流式对话（/chat/text/stream）
- 语音上传转写与对话（/chat/audio / /chat/audio/stream）
- 历史会话与音频持久化
- 文本回复后生成整段 TTS 并播放

## 目录结构
- `backend/`：FastAPI 后端
- `frontend/`：Vite + React 前端

## 本地启动

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

## 环境变量（最小集合）
以下变量建议放在你自己的 `.env` 或系统环境变量中：

### Ark（文字回复）
- `ARK_API_KEY`
- `ARK_MODEL`
- `ARK_BASE_URL`（可选，默认已设）

### AUC（语音识别）
- `VOLC_APP_ID`
- `VOLC_ACCESS_TOKEN`
- `NGROK_PUBLIC_URL`

### TTS（V1 整段合成）
- `TTS_APP_ID`
- `TTS_ACCESS_TOKEN`
- `TTS_VOICE_TYPE`

## 常用验证
- `GET /health`
- `GET /sessions`
- `POST /chat/text/stream`
- `POST /tts/full`
- `POST /chat/audio/stream`

## 说明
本仓库用于原型开发，代码与接口保持最小可用、可回退为优先。
