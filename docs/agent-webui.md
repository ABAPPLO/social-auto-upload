# Agent 接入指南：把本机当作局域网发布中台

面向局域网内的 AI Agent / 自动化脚本：把创作好的视频推到本服务，由本服务驱动真实浏览器完成各平台的登录态维护与发布。人不在线时 Agent 可完成除"扫码"外的全部流程。

服务地址约定：下文用 `http://sau.local:8010` 指代部署本项目的服务器，替换为实际 IP/端口（默认 `8010`）。

- 交互式 API 文档：`http://sau.local:8010/docs`（Swagger UI）
- OpenAPI 机器可读描述：`http://sau.local:8010/openapi.json`（agent 可据此自动发现全部接口）

## 鉴权（可选）

服务端启动时设置了环境变量 `SAU_WEB_TOKEN` 的话，所有 `/api/*` 请求（`/api/health` 除外）必须携带：

```
X-API-Token: <token>
```

或 `Authorization: Bearer <token>`。未设置该变量则无需鉴权（可信局域网模式）。

## 标准工作流

```
①查平台/账号 → ②上传素材 → ③创建发布任务（单个或批量） → ④轮询任务到终态
```

### ① 探测能力与账号

```bash
# 平台能力（谁支持图文/定时、必填附加字段）
curl http://sau.local:8010/api/meta

# 已有账号（cookie 文件）
curl http://sau.local:8010/api/accounts

# 检查某账号登录态是否有效（异步任务）
curl -X POST http://sau.local:8010/api/accounts/douyin/main/check
# → {"task": {"id": "abc123", ...}}，之后轮询该任务
```

平台要点：`bilibili` 发布必填 `extras.tid`（分区ID，可选值见 `/api/meta` 的 `zones.bilibili_tid`）；定时发布仅抖音/快手/小红书/Bilibili/视频号支持。

### ② 上传素材

```bash
curl -F "file=@/path/to/video.mp4" http://sau.local:8010/api/materials
# → {"material": {"name": "video.mp4", "type": "video", "size": ..., "duration": 12.3, ...}}
```

文件名在素材库内唯一，重名返回 400。素材保存在服务器 `uploadFile/` 目录。**Agent 也可跳过上传**，发布时 `file` 直接传服务器上的绝对路径（如 `/data/videos/xxx.mp4`）。

### ③ 创建发布任务

单个平台：

```bash
curl -X POST http://sau.local:8010/api/publish -H "Content-Type: application/json" -d '{
  "platform": "douyin",
  "content_type": "video",
  "account_name": "main",
  "file": "video.mp4",
  "title": "示例标题",
  "desc": "示例简介",
  "tags": ["vlog", "日常"],
  "publish_date": "",
  "headless": true
}'
# → {"task": {"id": "xxxx", "status": "pending", ...}}
```

**一次多平台分发**（推荐，`/api/publish/batch`）：公共字段一份 + 目标数组，任一目标参数不合法则整体 400（不会出现"一半入队"的中间态）：

```bash
curl -X POST http://sau.local:8010/api/publish/batch -H "Content-Type: application/json" -d '{
  "content_type": "video",
  "file": "video.mp4",
  "title": "同一标题多平台分发",
  "desc": "简介",
  "tags": ["自动分发"],
  "headless": true,
  "targets": [
    {"platform": "douyin", "account_name": "main"},
    {"platform": "xiaohongshu", "account_name": "main", "publish_date": "2026-09-30 10:00"},
    {"platform": "bilibili", "account_name": "main", "extras": {"tid": 21}}
  ]
}'
# → {"tasks": [{...}, {...}, {...}]}
```

目标级可覆盖字段：`platform`、`account_name`、`extras`（与公共 extras 合并，目标优先）、`publish_date`（如上例：小红书定时、其余立即）。

字段约定：

| 字段 | 说明 |
| --- | --- |
| `content_type` | `video`（视频）或 `note`（图文，仅抖音/快手/小红书） |
| `file` | 素材库名或服务器绝对路径（video 用） |
| `images` | 图片名数组（note 用，至少 1 张） |
| `title` / `desc` / `note` / `tags` | 标题必填；note 是图文正文（缺省回落到 desc） |
| `publish_date` | `""` 立即；`"YYYY-MM-DD HH:MM"` 平台侧定时，须 ≥ 2 小时后 |
| `thumbnail` | 可选封面（素材库图片名） |
| `thumbnail_landscape` / `thumbnail_portrait` | 可选，横版 / 竖版封面（抖音、视频号） |
| `extras` | 平台附加项：`tid`（bilibili 必填）、`collection_name`、`visibility`/`playlist`（youtube）、`short_title`/`category`/`is_draft`（视频号）、`bgm`（抖音图文）、`declaration`/`product_link`/`product_title`（抖音视频，声明留空时上游默认声明"内容由AI生成"） |
| `headless` | 默认 `true`，服务器无显示器时必须为 true |

### ④ 轮询任务到终态

```bash
curl http://sau.local:8010/api/tasks/<task_id>
```

- 状态机：`pending` → `running` → `success` / `failed`
- 失败原因在 `task.error`（中文、可直接转述给用户）
- 建议轮询间隔 3–5 秒；发布任务走串行队列（默认并发 1），多任务时 `pending` 可能持续较久，属正常排队
- 列表查询支持过滤：`/api/tasks?type=upload&platform=douyin&status=failed&account=main`

**注意**：`success` 表示"上传+提交流程走完"（含定时任务已设置成功），实际内容生效以平台审核为准。

## Cookie 失效处理（需要人的唯一环节）

发布失败且 `error` 提示 cookie 失效/过期时：

```bash
curl -X POST http://sau.local:8010/api/accounts/douyin/login -H "Content-Type: application/json" -d '{"account_name": "main"}'
# → {"task": {...}}，轮询该任务，字段 qrcode_data_url 会出现登录二维码（data URL 图片）
```

Agent 拿到 `qrcode_data_url` 后转给真人（渲染成图片发给用户即可），扫码确认后任务变 `success`，cookie 自动保存，之后重试发布。

### 抖音短信验证码（发布过程中可能触发）

抖音发布有时触发短信二次验证。此时任务的 `waiting_verify_code` 字段变为 `true`（30 秒内持续有效），
`message` 提示等待验证码。Agent 检测到后向用户要验证码并提交：

```bash
curl -X POST $BASE/api/tasks/<task_id>/verify-code -H "Content-Type: application/json" -d '{"code": "123456"}'
```

验证码为 4-8 位数字；写入后发布流程自动继续，无需重试任务。网页端会自动弹出输入框。

### 推送 cookie 文件（TikTok / Instagram / Facebook / X / Bilibili / YouTube / 跨机迁移）

8 个平台支持上述网页扫码；TikTok / Instagram / Facebook / X / Bilibili / YouTube 的登录无法网页化（交互式，无二维码），只能在**任意一台装了本项目的电脑**上终端执行 `sau <平台> login`，然后把生成的 cookie 文件推送到服务器：

```bash
curl -F "platform=bilibili" -F "account_name=main" \
     -F "file=@cookies/bilibili_main.json" \
     http://sau.local:8010/api/accounts/upload-cookie
```

文件须为有效 JSON（Playwright storage_state 或 biliup 账号文件），同名账号覆盖；
上传后建议立即 `POST /api/accounts/{platform}/{account}/check` 验证登录态。
网页端「账号管理 → 上传 cookie」提供同样能力（上传后自动验证）。

## 完整示例：Agent 自动发布一条视频到三个平台

```bash
BASE=http://sau.local:8010

# 1. 上传
curl -sF "file=@out/video.mp4" $BASE/api/materials

# 2. 批量发布
RESP=$(curl -s -X POST $BASE/api/publish/batch -H "Content-Type: application/json" -d '{
  "content_type": "video", "file": "video.mp4", "title": "AI 日报 0928",
  "tags": ["AI", "日报"], "headless": true,
  "targets": [
    {"platform": "douyin", "account_name": "main"},
    {"platform": "kuaishou", "account_name": "main"},
    {"platform": "bilibili", "account_name": "main", "extras": {"tid": 21}}
  ]
}')

# 3. 轮询到终态（伪代码）
for id in $(echo $RESP | jq -r '.tasks[].id'); do
  until curl -s $BASE/api/tasks/$id | jq -e '.task.status | test("success|failed")' >/dev/null; do
    sleep 5
  done
done
```

## 边界与约定

- 任务记录存内存，服务重启清空；cookie 与素材在磁盘不受影响
- 发布队列默认串行（`SAU_WEB_UPLOAD_CONCURRENCY` 可调），大量任务请按队列消化节奏提交
- 视频文件必须存在于服务器本地（先上传或用绝对路径）；支持的格式见 `/api/materials` 返回
- 本服务面向**可信局域网**；如需跨网段使用请启用 `SAU_WEB_TOKEN` 并配合防火墙
