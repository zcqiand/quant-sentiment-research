"""工作台 API 启动脚本：python scripts/run_api.py（默认 127.0.0.1:8610）。

Windows 下 uvicorn 默认 proactor loop 有 accept 崩溃指纹（WinError 64），
统一切 SelectorEventLoop（见 uvicorn-windows-proactor-accept-crash 记忆）。
"""

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402

from quant_sentiment.api.app import create_app  # noqa: E402


def main() -> None:
    port = int(os.getenv("APP_PORT", "8610"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
