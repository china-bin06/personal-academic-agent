# 页面自动采集

此次仅增加页面采集任务控制、独立worker与采集预览衔接，现有命令行脚本、问答、统计和正式导入服务沿用原逻辑。

## 使用

1. 重启本机FastAPI，浏览器Ctrl+F5刷新首页。保持服务绑定127.0.0.1。
2. 在“数据导入 → 自动导入”选择课表、成绩或培养计划；“手动导入”保留已有文件上传流程。
3. 课表和成绩填写连续两年的学年并选择学期；培养计划不需要学期。
4. 点击开始，服务通过同一Python环境运行固定worker，打开本机Edge。
5. 首次或登录失效时，页面显示等待登录。在新Edge窗口中完成学校登录，保留一个教务首页或培养计划标签页，返回Agent页面点击“已完成登录，继续采集”。不需要Inspector。登录未完成则再次等待。
6. 自动查询、导出或展开培养计划，沿用既有文件内容、学期和树结构校验。
7. 成功后在共用的“预览与确认导入”显示预览，并注明自动导入来源；若正在上传、已有未确认预览或页面刷新过，则点击“查看本次采集预览”。不会覆盖正在进行的导入。
8. 核对后使用原“确认导入数据库”。采集成功本身不写学业数据库。

## 接口和状态

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | /api/v1/collections/jobs | 启动固定采集类型，参数由Pydantic校验 |
| GET | /api/v1/collections/jobs | 最近50个页面采集任务 |
| GET | /api/v1/collections/jobs/{task_id} | 实时状态 |
| POST | /api/v1/collections/jobs/{task_id}/continue | 等待登录时继续并重新检查 |
| POST | /api/v1/collections/jobs/{task_id}/cancel | 请求取消 |
| POST | /api/v1/collections/jobs/{task_id}/preview | 从服务器登记的采集文件生成或复用预览 |

任务记录保存在被Git忽略的data/collections/tasks.sqlite3。原logs/collections.jsonl继续保存最终采集日志。页面刷新不会取消后台任务。SQLite事务限制一个活动任务，不接受客户端命令、URL或输出路径。

状态包括starting、running、waiting_login、cancelling、completed、failed、cancelled。完成仅代表文件采集与校验成功，不代表导入。没有自动输入账号密码，认证状态仅保存在原本机playwright/.auth路径。

## 边界与故障

- 仅本地单用户，不适合公开服务部署；Edge打开在运行FastAPI的电脑上。
- 任务最多15分钟；期限和取消在阶段之间及等待登录时检查，当前有界浏览器操作可能仍需一段时间结束。培养计划展开函数执行过程中不会立即中断。
- 关闭采集浏览器会使任务失败或取消，不把关闭窗口当作成功。
- 进程意外退出会记录失败；若服务及worker均异常中断，过期任务在20分钟后解除锁定，此时应先关闭遗留采集窗口再重试。
- 新学期PDF没有确认参考JSON时，采集文件可以成功，但生成完整预览仍会明确提示REFERENCE_REQUIRED。原始PDF保留在data/raw。
- 学校账号无法提供自动测试，学校线上登录、验证码、页面布局变化需要在本机手动验收；系统不会伪称这些情况已通过。

## 验证

测试使用隔离SQLite、浏览器替身及本地Edge模拟接口，不访问教务平台或模型服务，不导入个人数据。

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_collection_control.py tests/test_data_management.py tests/test_management_browser.py tests/test_business_tools.py tests/test_grade_parser.py -q
```

检查请求参数、固定入口、跨源拒绝、并发启动、继续登录、取消、超时、进程失败、异常脱敏、文件路径、预览复用与过期，以及三种worker成功路径与浏览器关闭。

页面验收检查学年学期、培养计划隐藏学期、刷新后恢复任务、继续登录、采集预览、确认导入、取消和窄屏布局。原问答与上传流程另做回归。

2026-10-12实际结果：任务控制19项、Edge浏览器2项、原上传导入17项、原成绩解析及业务15项，共53项通过（分批运行，新增变更后补跑对应测试）；JavaScript语法与git diff --check通过。沙箱临时目录不可写的首次运行未计作通过，经允许在普通权限下使用隔离临时目录重跑成功。

学校线上采集尚未复测。请分别运行三个选项，核对真实学期、课程数量与原始文件，再确认导入；另外测试退出登录后继续、关闭采集窗口和主动取消。没有调用模型API或修改既有统计口径。
