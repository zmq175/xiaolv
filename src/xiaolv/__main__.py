"""Command-line entry point; offline replay by default."""

import asyncio
import json
import os
import signal
import sys
from dataclasses import asdict

from xiaolv.live import LiveRuntimeError, run_live
from xiaolv.replay import main as replay
from xiaolv.settings import ConfigError, Settings, load_settings


async def serve(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
            installed.append(signum)
        summary = await run_live(settings, stop)
        print(json.dumps({"mode": "live", **asdict(summary)}, ensure_ascii=False))
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def main() -> int:
    try:
        settings = load_settings(os.environ)
        asyncio.run(serve(settings) if settings.mode == "live" else replay())
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 2
    except LiveRuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
