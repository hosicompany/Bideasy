"""Command-line entry point for the local creative runner."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import RunnerConfig
from .errors import RunnerError
from .runner import CreativeRunner

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BidEasy local Higgsfield creative runner"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="claim at most one queued attempt, then exit",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="verify CLI/account/workspace, then exit",
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = RunnerConfig.from_env()
        runner = CreativeRunner(config)
        try:
            if args.preflight_only:
                runner.preflight()
                logger.info("preflight passed")
                return 0
            if args.once:
                runner.preflight()
                runner.run_once()
                return 0
            runner.run_forever()
        finally:
            runner.close()
    except KeyboardInterrupt:
        return 130
    except RunnerError as exc:
        logger.error("runner stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
