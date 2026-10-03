# -*- coding: utf-8 -*-
"""social-auto-upload 的 MCP (Model Context Protocol) 适配层。

薄封装：把已部署的 sau-web API（FastAPI, 默认 8010 端口）暴露成 MCP 工具，
供 Claude / ZCode / OpenClaw 等 Agent 调用。业务逻辑全部复用 Web 后端，
本层只做参数适配、结果精简和二维码图片的内联渲染。
"""
__version__ = "0.1.0"
