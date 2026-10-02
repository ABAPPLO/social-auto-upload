# Web 管理界面（sau-web）

基于主线 `uploader/` / `sau_cli` 能力的局域网 Web 管理台，供团队其他成员通过浏览器使用，
不需要在各自电脑上安装 Python 环境或学习 CLI。

## 功能

- **仪表盘**：彩色统计卡片（账号 / 素材 / 今日任务 / 成功率）+ 图表可视化（近 7 日任务趋势、平台任务分布环形图）+ 各平台能力一览
- **账号管理**：网页扫码登录（二维码直接展示在页面上，支持 8 个平台）、登录态检查、删除账号；
  **上传 cookie 文件**（Bilibili / YouTube 等无法网页扫码的平台，在任意装有本项目的电脑上终端登录后把
  `cookies/<平台>_<账号名>.json` 上传到服务器，上传后自动验证登录态）
- **素材库**：拖拽 / 点击上传；**画廊式浏览**——视频自动提取封面帧并显示时长角标，点击卡片在线播放视频（支持拖动进度条）或查看大图
- **发布任务**：选择平台 + 账号 + 素材，填写标题 / 简介 / 标签，支持立即发布与平台侧定时发布（仅抖音、快手、小红书、Bilibili、视频号支持定时；抖音/视频号支持横竖版双封面、原创声明与带货链接；右侧**实时发布预览卡**（封面 + 标题 + 话题标签，所见即所得）
- **短信验证码**：抖音发布触发短信二次验证时，页面自动弹出验证码输入框（也可在任务记录里手动提交），提交后流程自动继续
- **任务记录**：发布 / 登录 / 检查任务的执行状态与错误信息，发布任务带素材封面缩略图（内存记录，重启后清空）

支持的平台与 CLI 一致（抖音、快手、小红书、Bilibili、视频号、百家号、支付宝生活号、微博、虎扑、YouTube、TikTok）。
其中抖音 / 快手 / 小红书支持图文发布。

视频预览说明：浏览器 `<video>` 能播放的编码即可预览（H.264 / VP9 / AV1 等主流编码都没问题）；
封面帧由 OpenCV 提取，与能否播放无关。个别冷门编码的视频无法在线播放，但不影响发布。

例外：

- **TikTok / Bilibili / YouTube 登录**是交互式流程（无二维码），需在装有本项目的本地电脑终端执行
  `sau <平台> login`，完成后通过网页「上传 cookie」推送到服务器，即可在网页上检查与上传；
  TikTok 在被墙网络下还需在服务器 conf.py 配置 `TK_PROXY`

## 安装与启动

前置条件与 CLI 相同（Python 3.10–3.12、`conf.py`、`patchright install chromium`），
参见 [安装说明](./install.md)。

```bash
uv pip install -e ".[webui]"     # 安装项目 + web 界面依赖（fastapi/uvicorn）
sau-web                           # 启动，默认监听 0.0.0.0:8010
```

局域网其他成员浏览器访问 `http://<服务器IP>:8010` 即可使用。

常用参数与环境变量：

```bash
sau-web --host 0.0.0.0 --port 8010
SAU_WEB_HOST=0.0.0.0 SAU_WEB_PORT=8010 sau-web
SAU_WEB_UPLOAD_CONCURRENCY=2 sau-web   # 同时执行的发布任务数，默认 1
```

前端为无构建静态页（Vue 3 + Element Plus 已内置于 `sau_webapp/static/vendor/`），内网无外网也能正常打开。

## 设计说明

- 上传能力直接复用 `sau_cli.py` 里的 `upload_*` 协程与请求对象，**Web 与 CLI 行为天然同步**，新增平台只需扩展 `sau_webapp/registry.py`
- 扫码登录复用各平台 `*_setup()` 的 `qrcode_callback` 机制，二维码以 data URL 推送到页面
- 视频封面帧与时长由 `sau_webapp/media.py` 用 OpenCV 提取，缓存在 `uploadFile/.thumbs/`（按素材修改时间自动失效）
- 素材文件接口支持 HTTP Range，浏览器内视频播放与进度拖动可用
- 前端为无构建静态页（Vue 3 + Element Plus + ECharts 已内置于 `sau_webapp/static/vendor/`），内网无外网也能正常打开
- 发布任务进入队列串行执行（默认并发 1）：每个任务会启动一个浏览器实例，并发过高会耗尽服务器内存
- 登录 / 检查任务即时执行，并发上限 2

## 安全提示

本界面**没有鉴权**，设计前提是可信局域网。请勿暴露到公网；如需公网访问，请自行加反向代理 +
鉴权（如 nginx basic auth）并限制来源 IP。

## 与旧 Web 版（sau_backend.py）的关系

`sau_backend.py` + `sau_frontend/` 是历史遗留的 Flask Web 版，已停止维护、与主线能力不同步，不要在其上扩展。
本目录（`sau_webapp/`）是当前主线推荐的 Web 形态。

## 给局域网 AI Agent 使用

本服务的全部能力都有 HTTP API，可供其他 agent / 自动化脚本直接调用（上传素材、批量多平台发布、轮询结果、
处理扫码登录），接入说明见 [Agent 接入指南](./agent-webui.md)。需要跨网段或加固时，
启动时设置 `SAU_WEB_TOKEN` 环境变量即可开启 API Token 鉴权。

## API 概览

所有接口以 `/api` 为前缀，返回 JSON；详情可访问服务运行后的交互式文档 `http://<服务器IP>:8010/docs`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/meta` | 平台元信息、Bilibili 分区、视频号分类 |
| GET | `/api/stats` | 仪表盘统计（账号分布、素材计数、近 7 日任务、平台任务分布） |
| GET | `/api/accounts` | 已配置账号列表 |
| POST | `/api/accounts/{platform}/login` | 发起扫码登录任务 |
| POST | `/api/accounts/{platform}/{account}/check` | 检查登录态 |
| DELETE | `/api/accounts/{platform}/{account}` | 删除账号 cookie |
| GET | `/api/materials` | 素材列表（含视频时长 / 分辨率） |
| POST | `/api/materials` | 上传素材（multipart） |
| GET | `/api/materials/{name}/file` | 素材文件流（支持 Range，可在线播放） |
| GET | `/api/materials/{name}/poster` | 视频封面帧（图片返回原图） |
| DELETE | `/api/materials/{name}` | 删除素材 |
| POST | `/api/publish` | 创建发布任务 |
| GET | `/api/tasks` · `/api/tasks/{id}` | 任务列表 / 详情 |
