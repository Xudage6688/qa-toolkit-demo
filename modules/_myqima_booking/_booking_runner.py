import subprocess
import json
import re
import shutil
import platform
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterator


ORDER_ID_RE = re.compile(r'[Oo]rder\s*[Ii][Dd][:\s]+([a-fA-F0-9]{32})')
QIMA_REF_RE = re.compile(r'QIMA\s*[Rr]ef[:\s]+(Q\d{10}-\w{2})')
TOTAL_AMOUNT_RE = re.compile(r'[Tt]otal\s*(?:order\s*)?amount[:\s]+((?:[\$€£]|[A-Z]{3}\s+)?[\d,]+\.?\d*)')
PLAYWRIGHT_SUMMARY_PASSED_RE = re.compile(r'\b\d+\s+passed\b', re.I)
PLAYWRIGHT_SUMMARY_FAILED_RE = re.compile(r'\b\d+\s+failed\b', re.I)
ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


def sanitizeStdoutLine(raw: str) -> str | None:
  """Strip ANSI codes and blank Playwright reporter lines."""
  text = ANSI_ESCAPE_RE.sub('', raw).strip()
  if not text:
    return None
  return text


def formatBookingLogText(lines: list[str], tail: int = 120) -> str:
  """Join log lines for Streamlit without extra blank rows."""
  rows: list[str] = []
  for raw in lines[-tail:]:
    clean = sanitizeStdoutLine(raw)
    if clean:
      rows.append(clean)
  return '\n'.join(rows)


@dataclass
class BookingResult:
  order_id: str = ""
  qima_ref: str = ""
  total_amount: str = ""
  success: bool = False
  error: str = ""
  logs: list[str] = field(default_factory=list)


def parse_log_line(line: str, result: BookingResult) -> None:
  m = ORDER_ID_RE.search(line)
  if m:
    result.order_id = m.group(1)
  m = QIMA_REF_RE.search(line)
  if m:
    result.qima_ref = m.group(1)
  m = TOTAL_AMOUNT_RE.search(line)
  if m:
    result.total_amount = m.group(1)


def _find_npx() -> str:
  if platform.system() == "Windows":
    npx_path = shutil.which("npx.cmd") or shutil.which("npx")
    if npx_path:
      return npx_path
    raise FileNotFoundError(
      "未找到 npx，请确认 Node.js 已安装并添加到 PATH"
    )
  return "npx"


def playwrightOutputIndicatesRunFinished(line: str) -> bool:
  """Detect Playwright / booking-flow completion in a stdout line."""
  if '下单完成' in line:
    return True
  if PLAYWRIGHT_SUMMARY_PASSED_RE.search(line) or PLAYWRIGHT_SUMMARY_FAILED_RE.search(line):
    return True
  if re.search(r'Test timeout of \d+ms exceeded', line, re.I):
    return True
  return False


def _iterSubprocessLines(
  process: subprocess.Popen,
  result: BookingResult,
  timeout: int,
  graceAfterFinishSec: float = 8.0,
) -> Iterator[str]:
  """
  Read subprocess stdout until Playwright exits or finishes summary.
  On Windows, npx/playwright may keep the pipe open after `N passed`; do not block forever.
  """
  start = time.monotonic()
  run_finished = False
  finish_seen_at: float | None = None

  while True:
    if run_finished and finish_seen_at is not None:
      if process.poll() is not None:
        break
      if time.monotonic() - finish_seen_at >= graceAfterFinishSec:
        break

    if time.monotonic() - start > timeout:
      raise subprocess.TimeoutExpired(process.args, timeout)

    line = process.stdout.readline() if process.stdout else ""
    if line:
      line = line.rstrip("\r\n")
      clean = sanitizeStdoutLine(line)
      if not clean:
        continue
      result.logs.append(clean)
      parse_log_line(clean, result)
      yield clean
      if playwrightOutputIndicatesRunFinished(clean):
        run_finished = True
        finish_seen_at = time.monotonic()
      continue

    if process.poll() is not None:
      break

    if run_finished and finish_seen_at is not None:
      time.sleep(0.15)
      continue

    time.sleep(0.1)


def _kill_process_tree(proc: subprocess.Popen | None) -> None:
  if proc is None:
    return
  if platform.system() != "Windows":
    proc.kill()
    proc.wait()
    return
  try:
    pid = proc.pid
    subprocess.run(
      ["taskkill", "/F", "/T", "/PID", str(pid)],
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
      timeout=5,
    )
  except Exception:
    pass


class BookingRunner:
  def __init__(self, playwright_project_path: str):
    self.playwright_path = Path(playwright_project_path)
    self.config_dir = self.playwright_path / "tests" / "myqima-booking-flow"
    self.config_path = self.config_dir / "booking-config.json"

  def run(self, config_dict: dict) -> BookingResult:
    result = BookingResult()
    for item in self.stream(config_dict):
      if isinstance(item, str):
        result.logs.append(item)
      else:
        return item
    return result

  def stream(self, config_dict: dict, timeout: int = 300, headed: bool = False):
    npx_cmd = _find_npx()

    if not self.playwright_path.exists():
      yield BookingResult(
        error=f"Playwright 项目路径不存在: {self.playwright_path}"
      )
      return

    self.config_dir.mkdir(parents=True, exist_ok=True)
    self.config_path.write_text(
      json.dumps(config_dict, indent=2), encoding="utf-8"
    )

    result = BookingResult()

    process = None

    child_env = os.environ.copy()
    child_env.setdefault("FORCE_COLOR", "0")
    child_env.setdefault("CI", "1")
    child_env.setdefault("PLAYWRIGHT_HTML_OPEN", "never")

    cmd = [
      npx_cmd, "playwright", "test",
      "tests/myqima-booking-flow/booking-flow.spec.ts",
      "--project=chromium",
      "--workers=1",
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

      for line in _iterSubprocessLines(process, result, timeout):
        yield line

      if process.poll() is None:
        _kill_process_tree(process)
      else:
        try:
          process.wait(timeout=15)
        except subprocess.TimeoutExpired:
          _kill_process_tree(process)

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
    except Exception as e:
      result.error = str(e)
    finally:
      _kill_process_tree(process)
      if self.config_path.exists():
        self.config_path.unlink()
    yield result
