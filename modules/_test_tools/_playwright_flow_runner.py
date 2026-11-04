"""Run arbitrary Playwright spec files with streaming stdout (Test Tools)."""

from __future__ import annotations

import os
import platform
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from modules._myqima_booking._booking_runner import (
  PLAYWRIGHT_SUMMARY_FAILED_RE,
  PLAYWRIGHT_SUMMARY_PASSED_RE,
  BookingResult,
  _find_npx,
  _iterSubprocessLines,
  _kill_process_tree,
)


@dataclass
class PlaywrightFlowResult:
  """Result of a single Playwright spec run."""

  success: bool = False
  error: str = ""
  logs: list[str] = field(default_factory=list)
  exit_code: int | None = None


class PlaywrightFlowRunner:
  """Execute one spec under a Playwright project root (npx playwright test)."""

  def __init__(self, playwright_project_path: str):
    self.playwright_path = Path(playwright_project_path)

  def stream(
    self,
    spec_relative: str,
    *,
    env_extra: dict[str, str] | None = None,
    headed: bool = False,
    timeout: int = 3600,
    workers: int = 1,
  ) -> Iterator[str | PlaywrightFlowResult]:
    """Yield log lines, then a final PlaywrightFlowResult."""
    npx_cmd = _find_npx()
    result = PlaywrightFlowResult()
    scratch = BookingResult()

    if not self.playwright_path.is_dir():
      result.error = f"Playwright 项目路径不存在: {self.playwright_path}"
      yield result
      return

    spec_path = self.playwright_path / spec_relative.replace("/", os.sep)
    if not spec_path.is_file():
      result.error = f"未找到测试文件: {spec_path}"
      yield result
      return

    process = None
    child_env = os.environ.copy()
    child_env.setdefault("FORCE_COLOR", "0")
    child_env.setdefault("CI", "1")
    child_env.setdefault("PLAYWRIGHT_HTML_OPEN", "never")
    if env_extra:
      for key, value in env_extra.items():
        if value is not None:
          child_env[str(key)] = str(value)

    cmd = [
      npx_cmd,
      "playwright",
      "test",
      spec_relative.replace("\\", "/"),
      "--project=chromium",
      f"--workers={workers}",
      "--reporter=line",
    ]
    if headed:
      cmd.append("--headed")

    try:
      process = subprocess.Popen(
        cmd,
        cwd=str(self.playwright_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        env=child_env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0,
      )

      for line in _iterSubprocessLines(process, scratch, timeout):
        result.logs.append(line)
        yield line

      if process.poll() is None:
        _kill_process_tree(process)
      else:
        try:
          process.wait(timeout=15)
        except subprocess.TimeoutExpired:
          _kill_process_tree(process)

      result.exit_code = process.returncode
      has_passed = any(PLAYWRIGHT_SUMMARY_PASSED_RE.search(l) for l in result.logs)
      has_failed = any(PLAYWRIGHT_SUMMARY_FAILED_RE.search(l) for l in result.logs)
      if has_passed and not has_failed:
        result.success = True
      elif has_failed:
        result.success = False
      else:
        result.success = process.returncode == 0
      if not result.success and process.returncode not in (0, None) and not result.error:
        result.error = f"Process exited with code {process.returncode}"
    except subprocess.TimeoutExpired:
      result.error = f"执行超时（超过 {timeout} 秒）"
      _kill_process_tree(process)
    except Exception as exc:
      result.error = str(exc)
    finally:
      _kill_process_tree(process)

    yield result
