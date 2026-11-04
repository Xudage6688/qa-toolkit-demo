"""Cypress 周跑后台执行器单元测试。"""

import json
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

from modules._test_tools._cypress_weekly_runner import (
  CypressWeeklyError,
  applyXrayCredentialsToCypressEnv,
  buildCypressCommand,
  formatCypressCommand,
  launchDetachedProcess,
  queryProcessExit,
  readEditableCypressEnv,
  redactCypressLog,
  refreshCypressWeeklyRun,
  startCypressWeeklyRun,
  stopCypressWeeklyRun,
  writeEditableCypressEnv,
)


ENV_TEXT = """{
\t"sanitize": false,
\t"api_access_token": "secret-token",
\t"xray_client_secret": "secret-value",
\t"xray_jira_integration_enabled": false,
\t"test_execution_key": "SP-37670",
\t"sprint": 43,
\t"week": 1,
\t"sp_team": "Mermaid"
}
"""


def _project(tmp_path: Path) -> Path:
  """创建一个只含 env 文件的假 Cypress 项目。"""
  project = tmp_path / "cypress-project"
  project.mkdir()
  (project / "cypress.env.json").write_text(ENV_TEXT, encoding="utf-8")
  return project


class TestXraySecrets:
  def testInjectsFromUsersConfig(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """启动前把 users_config 的 Xray 凭证写入 cypress.env.json。"""
    monkeypatch.delenv("XRAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("XRAY_CLIENT_SECRET", raising=False)
    project = _project(tmp_path)
    envPath = project / "cypress.env.json"
    envData = json.loads(envPath.read_text(encoding="utf-8"))
    envData["xray_client_id"] = "YOUR_CLIENT_ID"
    envData["xray_client_secret"] = "YOUR_CLIENT_SECRET"
    envPath.write_text(json.dumps(envData, indent="\t") + "\n", encoding="utf-8")
    usersConfig = tmp_path / "users_config.json"
    usersConfig.write_text(
      json.dumps({
        "users": {
          "Daisy": {
            "xray": {
              "client_id": "id-from-config",
              "client_secret": "secret-from-config",
            },
          },
        },
      }),
      encoding="utf-8",
    )
    applyXrayCredentialsToCypressEnv(
      str(project),
      username="Daisy",
      usersConfigPath=usersConfig,
    )
    data = json.loads((project / "cypress.env.json").read_text(encoding="utf-8"))
    assert data["xray_client_id"] == "id-from-config"
    assert data["xray_client_secret"] == "secret-from-config"
    assert data["api_access_token"] == "secret-token"


class TestEditableEnv:
  def testPreservesSecretsAndOtherKeys(self, tmp_path: Path):
    """只改四个日常字段，密钥和其余配置保持原样。"""
    project = _project(tmp_path)
    writeEditableCypressEnv(str(project), {
      "xray_jira_integration_enabled": True,
      "test_execution_key": "SP-99999",
      "sprint": 44,
      "week": 2,
    })
    text = (project / "cypress.env.json").read_text(encoding="utf-8")
    assert '"api_access_token": "secret-token"' in text
    assert '"xray_client_secret": "secret-value"' in text
    assert '"sp_team": "Mermaid"' in text
    assert '"sanitize": false' in text
    fields = readEditableCypressEnv(str(project))
    assert fields["xray_jira_integration_enabled"] is True
    assert fields["test_execution_key"] == "SP-99999"
    assert fields["sprint"] == 44
    assert fields["week"] == 2
    assert "secret-token" not in json.dumps(fields)

  def testRejectsBadWeekWithoutWriting(self, tmp_path: Path):
    """非法 week 不改文件。"""
    project = _project(tmp_path)
    before = (project / "cypress.env.json").read_text(encoding="utf-8")
    with pytest.raises(CypressWeeklyError):
      writeEditableCypressEnv(str(project), {
        "xray_jira_integration_enabled": False,
        "test_execution_key": "SP-37670",
        "sprint": 43,
        "week": 0,
      })
    assert (project / "cypress.env.json").read_text(encoding="utf-8") == before


class TestCommand:
  def testMatchesManualWeeklyCommand(self):
    """命令顺序与每周手工执行一致。"""
    cmd = buildCypressCommand(
      "cypress/integration/my-qima/**/*.js",
      "chrome",
      True,
      npxCmd="npx.cmd",
    )
    assert cmd == [
      "npx.cmd",
      "cypress",
      "run",
      "--spec",
      "cypress/integration/my-qima/**/*.js",
      "--headless",
      "--browser",
      "chrome",
    ]
    assert formatCypressCommand(cmd) == (
      'npx cypress run --spec "cypress/integration/my-qima/**/*.js"'
      " --headless --browser chrome"
    )


class TestRedact:
  def testHidesSecretsAndAnsi(self):
    """日志里的 token 和颜色码不原样展示。"""
    raw = "\x1b[31mxray_client_secret: abcdef\x1b[0m"
    cleaned = redactCypressLog(raw)
    assert "abcdef" not in cleaned
    assert "[REDACTED]" in cleaned
    assert "\x1b" not in cleaned


class TestBackgroundRun:
  def testDetachedRunKeepsGoingAndCanBeStopped(self, tmp_path: Path):
    """脱离启动后进程独立存活，停止后不再运行。"""
    project = _project(tmp_path)
    stateDir = tmp_path / "state"
    state = startCypressWeeklyRun(
      projectPath=str(project),
      spec="cypress/integration/my-qima/**/*.js",
      browser="chrome",
      headless=True,
      xrayEnabled=False,
      testExecutionKey="SP-37670",
      sprint=43,
      week=1,
      stateDir=stateDir,
      commandOverride=[
        sys.executable,
        "-c",
        "import time; print('still-running', flush=True); time.sleep(30)",
      ],
    )
    try:
      alive, _exitCode = queryProcessExit(state.pid)
      assert alive is True
      again = startCypressWeeklyRun(
        projectPath=str(project),
        spec="cypress/integration/my-qima/**/*.js",
        browser="chrome",
        headless=True,
        xrayEnabled=False,
        testExecutionKey="SP-37670",
        sprint=43,
        week=1,
        stateDir=stateDir,
        commandOverride=[sys.executable, "-c", "print('nope')"],
      )
      assert again.pid == state.pid
    except CypressWeeklyError:
      again = None
    else:
      stopCypressWeeklyRun(stateDir)
      raise AssertionError("重复启动应该被拒绝")
    finally:
      stopCypressWeeklyRun(stateDir)
    assert again is None
    alive, _exitCode = queryProcessExit(state.pid)
    assert alive is False
    stopped = refreshCypressWeeklyRun(stateDir)
    assert stopped is not None
    assert stopped.state == "stopped"

  def testRefreshSeesFinishedLog(self, tmp_path: Path):
    """进程结束后仍能从日志文件读到结果。"""
    project = _project(tmp_path)
    stateDir = tmp_path / "state"
    script = (
      "print('All specs passed! 00:01 3 3 - - -', flush=True)"
    )
    startCypressWeeklyRun(
      projectPath=str(project),
      spec="cypress/integration/my-qima/**/*.js",
      browser="chrome",
      headless=True,
      xrayEnabled=False,
      testExecutionKey="SP-10001",
      sprint=44,
      week=2,
      stateDir=stateDir,
      commandOverride=[sys.executable, "-c", script],
    )
    deadline = time.time() + 8
    state = None
    while time.time() < deadline:
      state = refreshCypressWeeklyRun(stateDir)
      if state is not None and state.state != "running":
        break
      time.sleep(0.2)
    assert state is not None
    assert state.state == "finished"
    assert state.passing == 3
    assert state.tests == 3
    text = (project / "cypress.env.json").read_text(encoding="utf-8")
    assert '"xray_jira_integration_enabled": false' in text
    assert '"test_execution_key": "SP-10001"' in text
    assert '"api_access_token": "secret-token"' in text


REAL_ENV = Path(
  r"C:\Users\demo\cypress-project\cypress.env.json"
)


def _jsonStringField(text: str, key: str) -> str | None:
  """取出 JSON 字符串字段。比较失败时不把原值写进断言信息。"""
  matched = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
  return matched.group(1) if matched else None


class TestRealEnvShape:
  def testSameValuesDoNotRewriteSecrets(self, tmp_path: Path):
    """按本机 cypress.env.json 的真实结构回写，不改动密钥。"""
    if not REAL_ENV.is_file():
      pytest.skip("本机 cypress.env.json 不存在")
    original = REAL_ENV.read_text(encoding="utf-8")
    project = tmp_path / "real-shape"
    project.mkdir()
    envPath = project / "cypress.env.json"
    envPath.write_text(original, encoding="utf-8")
    fields = readEditableCypressEnv(str(project))
    writeEditableCypressEnv(str(project), fields)
    rewritten = envPath.read_text(encoding="utf-8")
    if rewritten != original:
      raise AssertionError("写回相同字段时改动了 cypress.env.json")
    nextWeek = 2 if int(fields["week"]) != 2 else 1
    writeEditableCypressEnv(str(project), {**fields, "week": nextWeek})
    changed = envPath.read_text(encoding="utf-8")
    assert readEditableCypressEnv(str(project))["week"] == nextWeek
    for secretKey in ("api_access_token", "xray_client_secret", "xray_client_id"):
      if _jsonStringField(changed, secretKey) != _jsonStringField(original, secretKey):
        raise AssertionError(f"{secretKey} 被改动")


class TestNpxLog:
  def testNpxVersionReachesLog(self, tmp_path: Path):
    """npx.cmd 在无窗口进程组里仍要把输出写进日志。"""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
      pytest.skip("未安装 npx")
    logPath = tmp_path / "npx.log"
    pid = launchDetachedProcess([npx, "--version"], tmp_path, logPath)
    deadline = time.time() + 20
    text = ""
    while time.time() < deadline:
      alive, _exitCode = queryProcessExit(pid)
      text = logPath.read_text(encoding="utf-8", errors="replace") if logPath.is_file() else ""
      if text.strip() and not alive:
        break
      time.sleep(0.2)
    assert text.strip()
