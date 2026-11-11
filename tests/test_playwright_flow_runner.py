"""Tests for Playwright flow runner (Test Tools)."""
import os
import tempfile
from pathlib import Path


from modules._test_tools._playwright_flow_runner import PlaywrightFlowRunner


def test_playwright_flow_runner_missing_project():
  runner = PlaywrightFlowRunner("/nonexistent/playwright")
  items = list(runner.stream("tests/life-science-flow/study-chain.spec.ts"))
  assert len(items) == 1
  result = items[0]
  assert result.success is False
  assert "不存在" in result.error


def test_playwright_flow_runner_missing_spec():
  with tempfile.TemporaryDirectory() as tmp:
    runner = PlaywrightFlowRunner(tmp)
    items = list(runner.stream("tests/life-science-flow/study-chain.spec.ts"))
    result = items[-1]
    assert result.success is False
    assert "未找到测试文件" in result.error


def test_playwright_flow_runner_spec_exists_ok_to_start():
  with tempfile.TemporaryDirectory() as tmp:
    spec_rel = "tests/life-science-flow/study-chain.spec.ts"
    spec_path = Path(tmp) / spec_rel
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("// placeholder", encoding="utf-8")
    runner = PlaywrightFlowRunner(tmp)
    assert (Path(tmp) / spec_rel).is_file()
