# AGENTS

## 项目结构
- backend/main.py 作为入口层（FastAPI app 初始化与 include_router）。
- backend/routes_*.py 为路由层，仅做请求/响应编排与调用 service。
- backend/*_service.py 为业务层（纯业务逻辑，尽量返回普通 Python 数据）。
- backend/config.py / backend/models.py / backend/storage_utils.py / backend/utils.py 为基础支撑层。

## 修改规则
- 不擅自修改 API path。
- 不擅自修改 SSE 事件名。
- STORE_LOCK 保持现有边界，除非明确要求。
- 优先小改动，避免无关重构。

## 输出格式规则
1. Logic Trace
2. 修改文件清单
3. 每个文件改动说明
4. 完整代码
5. 验证步骤

## 测试规则
- 改动后优先建议运行 `smoke_test.ps1`。
- 不编造未运行结果。
