# 个人学业 Agent

基于 FastAPI、Pydantic、LLM Tool Calling 和 PostgreSQL，
查询个人成绩、课表和培养计划。

## 功能

- 百分制成绩汇总与学期比较
- 指定教学周的课表查询
- 培养计划学分进度查询
- PDF、Excel 和网页 HTML 数据解析
- 受控查询工具、参数校验和查询审计
- 本地网页问答与数据依据展示

## 技术栈

Python、FastAPI、Pydantic、SQLAlchemy、PostgreSQL、
Playwright、pdfplumber、原生 HTML/CSS/JavaScript。

## 本地使用

1. 创建 Python 虚拟环境并安装 requirements.txt。
2. 根据 .env.example 创建 .env，配置数据库和模型服务。
3. 启动 PostgreSQL，完成数据库迁移及只读账号配置。
4. 采集或准备个人数据，预览确认后正式导入。
5. 启动 FastAPI：

    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

6. 打开 http://127.0.0.1:8000/。

## 数据说明

仓库不包含真实成绩、课表、培养计划、登录状态或密钥。
部分测试需要本地数据文件及数据库，不能在空数据环境下直接运行。

## 当前限制

- 当前用于本地单用户。
- 问答请求不保存多轮对话上下文。
- 培养计划采集仍需要人工确认页面。
- 课表按常规教学安排查询，不包含临时调课。