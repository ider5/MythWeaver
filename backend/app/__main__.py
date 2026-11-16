"""本地入口：``python -m app``。默认只监听 127.0.0.1。"""

from __future__ import annotations

import uvicorn

from app.main import local_uvicorn_options


def main() -> None:
    uvicorn.run(**local_uvicorn_options())


if __name__ == "__main__":
    main()
