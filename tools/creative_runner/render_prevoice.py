#!/usr/bin/env python3
"""Render the local BidEasy prevoice package without calling Higgsfield."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bideasy_creative_runner.config import (
    DEFAULT_BRAND_POLICY_PATH,
    DEFAULT_FONT_DIR,
)
from bideasy_creative_runner.prevoice import render_prevoice_package

TOOL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TOOL_ROOT.parents[1]
DEFAULT_SPEC = REPO_ROOT / "docs" / "CREATIVE_PREPRODUCTION_15S.json"
DEFAULT_OUTPUT = TOOL_ROOT / "preproduction-output"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate non-publishable A/B storyboards and silent previews"
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--brand-policy", type=Path, default=DEFAULT_BRAND_POLICY_PATH)
    parser.add_argument("--font-dir", type=Path, default=DEFAULT_FONT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--ffprobe-bin", default="ffprobe")
    args = parser.parse_args()
    manifest = render_prevoice_package(
        args.spec,
        args.brand_policy,
        args.font_dir,
        args.output_dir,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
