# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

social-auto-upload automates publishing videos and image-notes (图文) to Chinese and international social platforms — 抖音 (Douyin), Bilibili, 小红书 (Xiaohongshu), 快手 (Kuaishou), 视频号 (Tencent Channels), 百家号, 支付宝生活号 (Alipay), 微博 (Weibo), 虎扑 (Hupu), YouTube, TikTok — via browser automation with `patchright` (a stealth-hardened Playwright fork). The mainline is the `sau` CLI; an older Flask web UI is retained but unmaintained.

README, docs, code comments, and user-facing strings are in Chinese (zh-CN) — match that in new code.

## Setup & Commands

```bash
uv venv && source .venv/bin/activate    # Python >=3.10,<3.13
uv pip install -e .                     # installs deps + registers the `sau` command
patchright install chromium             # browser driver (CN mirror: PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright)
cp conf.example.py conf.py              # REQUIRED — see gotcha below
```

- **`conf.py` is required before anything runs.** It is gitignored but imported at module level by `sau_cli`, `utils/*`, and every uploader — even the tests fail to import without it.
- `uv` is the package manager (`uv.lock`); `requirements.txt` is legacy compatibility only, not the install entrypoint.
- Browser code imports from `patchright.async_api`, never `playwright`.

### CLI usage

```bash
sau <platform> login|check|upload-video [upload-note] --account <account_name> ...
# e.g.
sau douyin upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2
```

CLI platforms: douyin, kuaishou, xiaohongshu, bilibili, tencent, baijiahao, alipay, weibo, hupu, youtube (TikTok has no CLI yet). Metadata convention: video = `title + desc + tags`; note = `title + note + tags`. Full flag reference: `docs/CLI.md`.

### Tests

Stdlib `unittest` — no pytest configured. From the repo root (needs `conf.py` + installed deps):

```bash
python -m unittest discover -s tests                              # all
python -m unittest tests.test_sau_browser_cli                     # one module
python -m unittest tests.test_sau_browser_cli.BrowserCliParserTests  # one case
```

Tests mock the browser layer (`unittest.mock.AsyncMock`) and exercise parser/handler logic only; they never launch a real browser.

## Architecture

### Mainline: CLI → per-platform uploaders

- `sau_cli.py` — the entire CLI in one file: `build_parser()` defines every subcommand, `main()` (sau_cli.py:1445) dispatches via `asyncio.run`. Per-platform dataclass request objects (`DouyinVideoUploadRequest`, …) carry arguments into the uploaders.
- `uploader/<platform>_uploader/main.py` — every browser platform exports the same surface:
  - `cookie_auth(account_file)` — restore the saved `storage_state` and verify the session is still logged in
  - `<platform>_setup(account_file, ...)` — interactive QR-code login; saves a timestamped `<account>_login_qrcode_<ts>.png` next to the account file (`utils/login_qrcode.py`)
  - `<X>Video` / `<X>Note` classes — async `upload()`: launch the browser with `storage_state=account_file`, drive the platform's creator portal, save `storage_state` back after publishing
- Account cookie files are `<uploader_dir>/<account_name>.json` (gitignored). One `account_name` = one JSON file; different accounts can run concurrently.
- `uploader/base_video.py::BaseVideoUploader` — shared validation: allowed video/image extensions, and `publish_date` of `0` (immediate) or a `datetime` at least 2 hours out. Each platform defines `*_PUBLISH_STRATEGY_IMMEDIATE` / `*_SCHEDULED` constants. Scheduling logic historically assumes "publish tomorrow" — check per-platform behavior before changing it.
- Directory-name mapping is inconsistent: kuaishou → `ks_uploader`, 视频号 → `tencent_uploader`, 小红书 mainline → `xiaohongshu_uploader` (browser automation). `xhs_uploader` is the old `XHS_SERVER`-based implementation — legacy.

### Pattern exceptions

- **Bilibili** uploads without a browser: `uploader/bilibili_uploader/runtime.py` downloads/updates the external `biliup` binary from GitHub releases into `~/.social-auto-upload/tools/biliup` and shells out to it. Users should run `sau bilibili login` themselves in a real terminal (QR code; open the generated `qrcode.png` if the terminal renders it poorly).
- **YouTube** deliberately uses browser automation rather than the official API — uploads through unreviewed Google API projects are force-locked private. It waits for 100% upload progress before clicking publish. Set `YT_PROXY` in `conf.py` where youtube.com is blocked; the driven chromium ignores system proxies.

### Douyin SMS re-verification

If publishing triggers an SMS check, the CLI reads the code from `verify_code.txt` in the repo root (or prompts in an interactive terminal), then deletes the file on success. Agents bridge the check by writing that file.

### Legacy web — do not extend

`sau_backend.py` (Flask), `sau_frontend/`, `myUtils/`, `db/`, `static/`, and the direct-uploader scripts in `examples/` belong to the retained-but-unmaintained web version (`docs/legacy-web.md`). Route new capability through the CLI instead.

### Agent-facing surfaces (keep in sync)

- `skills/<platform>-upload/` — SKILL.md plus `references/cli-contract.md` for douyin, kuaishou, xiaohongshu, bilibili. CLI flag changes for these platforms must update the matching cli-contract.md.
- `docs/agent-bootstrap.md` and the "For AI Agents" section of `docs/install.md` describe how agents are expected to install and drive this repo.
- Design docs and implementation plans live in `docs/superpowers/specs/` and `docs/superpowers/plans/` (dated markdown); substantial refactors have followed that spec → plan flow.
