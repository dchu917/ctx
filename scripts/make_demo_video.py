#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs"
OUT_VIDEO = OUT_DIR / "ctx-demo.mp4"
OUT_POSTER = OUT_DIR / "ctx-demo-poster.png"
FPS = 12
WIDTH = 1440
HEIGHT = 900
BG = "#f6f6f3"
WINDOW_BG = "#111317"
WINDOW_LINE = "#262a31"
TITLE = "#eef1f4"
TEXT = "#d9dfe5"
MUTED = "#93a0ad"
ACCENT = "#9ae6b4"
COMMAND = "#f8fafc"


@dataclass
class Scene:
    command: str
    output: str
    footer: str | None = None


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/System/Library/Fonts/Monaco.ttf",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


FONT_MAIN = _font(24)
FONT_SMALL = _font(18)
FONT_TITLE = _font(22)


def _run_ctx(args: list[str], env: dict[str, str]) -> str:
    cmd = [shutil.which("ctx") or str(ROOT / "scripts" / "ctx_cmd.py")]
    if cmd[0].endswith("ctx_cmd.py"):
        cmd = ["python3", cmd[0]]
    proc = subprocess.run(
        cmd + args,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _wrap_line(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return [""]
    words = text.split(" ")
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
            continue
        lines.append(current)
        current = word
    lines.append(current)
    expanded: list[str] = []
    for line in lines:
        if draw.textlength(line, font=font) <= max_width:
            expanded.append(line)
            continue
        chunk = ""
        for ch in line:
            trial = chunk + ch
            if draw.textlength(trial, font=font) <= max_width:
                chunk = trial
            else:
                expanded.append(chunk)
                chunk = ch
        if chunk:
            expanded.append(chunk)
    return expanded


def _wrap_block(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        lines.extend(_wrap_line(draw, raw, font, max_width))
    return lines


def _render_frame(command_prefix: str, command_text: str, output_lines: list[str], footer: str | None) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    margin = 48
    win_x0, win_y0 = margin, 70
    win_x1, win_y1 = WIDTH - margin, HEIGHT - 58
    shadow_offset = 18
    draw.rounded_rectangle(
        (win_x0 + shadow_offset, win_y0 + shadow_offset, win_x1 + shadow_offset, win_y1 + shadow_offset),
        radius=26,
        fill="#d9ddd5",
    )
    draw.rounded_rectangle((win_x0, win_y0, win_x1, win_y1), radius=26, fill=WINDOW_BG, outline=WINDOW_LINE, width=2)

    top_bar_h = 50
    draw.rounded_rectangle((win_x0, win_y0, win_x1, win_y0 + top_bar_h), radius=26, fill="#171a20")
    draw.rectangle((win_x0, win_y0 + top_bar_h - 20, win_x1, win_y0 + top_bar_h), fill="#171a20")
    for idx, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        cx = win_x0 + 28 + idx * 20
        cy = win_y0 + 25
        draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=color)
    draw.text((win_x0 + 68, win_y0 + 14), "ctx demo", font=FONT_TITLE, fill=TITLE)

    text_x = win_x0 + 32
    text_y = win_y0 + top_bar_h + 22
    line_h = 34
    content_width = win_x1 - win_x0 - 64

    draw.text((text_x, text_y), command_prefix, font=FONT_MAIN, fill=ACCENT)
    prefix_w = draw.textlength(command_prefix, font=FONT_MAIN)
    draw.text((text_x + prefix_w, text_y), command_text, font=FONT_MAIN, fill=COMMAND)

    y = text_y + line_h + 12
    max_lines = int((win_y1 - y - 42) / line_h)
    visible_lines = output_lines[:max_lines]
    if len(output_lines) > max_lines:
        visible_lines = visible_lines[:-1] + ["..."]
    for line in visible_lines:
        draw.text((text_x, y), line, font=FONT_MAIN, fill=TEXT)
        y += line_h

    if footer:
        footer_lines = _wrap_block(draw, footer, FONT_SMALL, content_width)
        y = win_y1 - 32 - len(footer_lines) * 24
        for line in footer_lines:
            draw.text((text_x, y), line, font=FONT_SMALL, fill=MUTED)
            y += 24

    return img


def _write_video(frames_dir: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(OUT_VIDEO),
        ],
        check=True,
        capture_output=True,
    )


def _make_scenes() -> list[Scene]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        env = os.environ.copy()
        env["CONTEXTFUN_DB"] = str(tmp_path / "demo.db")
        env["CTX_AUTOPULL_DEFAULT"] = "0"
        env["CTX_LOAD_CHAR_BUDGET"] = "2600"
        env["CODEX_HOME"] = str(tmp_path / "codex-home")
        env["CLAUDE_HOME"] = str(tmp_path / "claude-home")
        (tmp_path / "codex-home" / "sessions").mkdir(parents=True, exist_ok=True)
        (tmp_path / "claude-home" / "projects").mkdir(parents=True, exist_ok=True)

        start = _run_ctx(["start", "feature-audit", "--brief"], env)
        _run_ctx(["note", "Review transcript binding drift and branch safety."], env)
        workstreams = _run_ctx(["list"], env)
        start_again = _run_ctx(["start", "feature-audit", "--brief"], env)
        resume = _run_ctx(["resume", "feature-audit", "--brief"], env)
        rename = _run_ctx(["rename", "feature-audit-v2", "--from", "feature-audit"], env)
        search = _run_ctx(["search", "transcript drift", "--limit", "3"], env)

    return [
        Scene(
            command="ctx start feature-audit --brief",
            output="\n".join(start.splitlines()[:16]),
            footer="Create a new workstream and load a compact resume pack.",
        ),
        Scene(
            command="ctx list",
            output=workstreams,
            footer="List saved workstreams with a one-line summary of the goal and latest task.",
        ),
        Scene(
            command="ctx start feature-audit --brief",
            output="\n".join(start_again.splitlines()[:16]),
            footer="If the name already exists, ctx automatically creates a suffixed workstream.",
        ),
        Scene(
            command="ctx resume feature-audit --brief",
            output="\n".join(resume.splitlines()[:16]),
            footer="Resume continues an existing workstream instead of creating a new one.",
        ),
        Scene(
            command="ctx rename feature-audit-v2 --from feature-audit",
            output=rename,
            footer="Rename a workstream explicitly without changing its saved context.",
        ),
        Scene(
            command="ctx search transcript drift --limit 3",
            output=search,
            footer="Search indexed workstreams and snippets when you need to find the right context quickly.",
        ),
        Scene(
            command="ctx web --open",
            output="Open the browser UI to browse workstreams, search context, and copy the exact command to continue a stream.",
            footer="You can run ctx web --open in the terminal or in the agent shell.",
        ),
    ]


def _frame_counts(command: str, output_lines: Iterable[str]) -> tuple[int, int, int]:
    typed = max(10, min(24, len(command)))
    reveal = max(10, min(26, len(list(output_lines)) * 2))
    hold = 14
    return typed, reveal, hold


def main() -> None:
    scenes = _make_scenes()
    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = Path(tmp)
        prompt = "david@ctx-demo % "
        frame_index = 0
        scratch = Image.new("RGB", (WIDTH, HEIGHT), BG)
        scratch_draw = ImageDraw.Draw(scratch)
        content_width = WIDTH - 2 * 48 - 64

        poster_saved = False
        for scene in scenes:
            wrapped_output = _wrap_block(scratch_draw, scene.output, FONT_MAIN, content_width)
            typed_count, reveal_count, hold_count = _frame_counts(scene.command, wrapped_output)

            for idx in range(typed_count):
                chars = int(len(scene.command) * (idx + 1) / typed_count)
                img = _render_frame(prompt, scene.command[:chars], [], scene.footer)
                img.save(frames_dir / f"frame_{frame_index:04d}.png")
                if not poster_saved:
                    img.save(OUT_POSTER)
                    poster_saved = True
                frame_index += 1

            for idx in range(reveal_count):
                lines = int(len(wrapped_output) * (idx + 1) / reveal_count)
                img = _render_frame(prompt, scene.command, wrapped_output[:lines], scene.footer)
                img.save(frames_dir / f"frame_{frame_index:04d}.png")
                frame_index += 1

            for _ in range(hold_count):
                img = _render_frame(prompt, scene.command, wrapped_output, scene.footer)
                img.save(frames_dir / f"frame_{frame_index:04d}.png")
                frame_index += 1

        _write_video(frames_dir)
    print(f"Wrote {OUT_VIDEO}")
    print(f"Wrote {OUT_POSTER}")


if __name__ == "__main__":
    main()
