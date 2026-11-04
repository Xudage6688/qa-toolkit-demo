"""后台运行 myQIMA Cypress 周跑，日志落盘，页面切换不中断。"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_PATH = ""
DEFAULT_SPEC = "cypress/integration/my-qima/**/*.js"
DEFAULT_BROWSER = "chrome"
ENV_FILE_NAME = "cypress.env.json"
EDITABLE_ENV_KEYS = (
  "xray_jira_integration_enabled",
  "test_execution_key",
  "sprint",
  "week",
)
XRAY_SECRET_ENV_KEYS = ("xray_client_id", "xray_client_secret")
ALLOWED_BROWSERS = ("chrome", "electron", "edge", "firefox", "chromium")
EXECUTION_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]+-\d+$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SECRET_RE = re.compile(
  r"(api_access_token|xray_client_secret|xray_client_id|authorization|bearer)"
  r"(\s*[:=]\s*)(\S+)",
  re.IGNORECASE,
)
SUMMARY_RE = re.compile(
  r"(All specs passed!|\d+\s+of\s+\d+\s+failed\s+\([^)]+\))\s+"
  r"(\d+:\d+)\s+(\d+)\s+(\d+)\s+(\d+|-)\s+(\d+|-)\s+(\d+|-)",
  re.IGNORECASE,
)
JSON_VALUE_RE_TEMPLATE = (
  r'("{key}"\s*:\s*)(true|false|null|-?\d+(?:\.\d+)?|"(?:\\.|[^"\\])*")'
)


class CypressWeeklyError(Exception):
  """可直接展示给用户的 Cypress 周跑错误。"""


@dataclass
class CypressRunState:
  """一次后台 Cypress 运行的持久化状态。"""

  pid: int
  logPath: str
  projectPath: str
  spec: str
  browser: str
  headless: bool
  command: str
  startedAt: str
  state: str
  exitCode: int | None = None
  finishedAt: str | None = None
  summary: str = ""
  tests: int | None = None
  passing: int | None = None
  failing: int | None = None


def defaultCypressStateDir() -> Path:
  """返回日志与状态文件目录（位于 results/，不入库）。"""
  return Path(__file__).resolve().parents[2] / "results" / "cypress_weekly"


def defaultCypressPrefs() -> dict[str, object]:
  """返回未保存过偏好时的默认运行参数。"""
  return {
    "projectPath": DEFAULT_PROJECT_PATH,
    "spec": DEFAULT_SPEC,
    "browser": DEFAULT_BROWSER,
    "headless": True,
  }


def loadCypressWeeklyPrefs(stateDir: Path | None = None) -> dict[str, object]:
  """读取上次保存的项目路径、spec、浏览器与 headless。"""
  prefs = defaultCypressPrefs()
  path = _prefsPath(stateDir)
  if not path.is_file():
    return prefs
  try:
    stored = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as ex:
    logger.warning("读取 Cypress 偏好失败: %s", ex)
    return prefs
  if not isinstance(stored, dict):
    return prefs
  for key in ("projectPath", "spec", "browser"):
    if isinstance(stored.get(key), str) and stored[key].strip():
      prefs[key] = stored[key].strip()
  if isinstance(stored.get("headless"), bool):
    prefs["headless"] = stored["headless"]
  return prefs


def saveCypressWeeklyPrefs(
  prefs: dict[str, object],
  stateDir: Path | None = None,
) -> None:
  """保存不含密钥的运行偏好。"""
  path = _prefsPath(stateDir)
  path.parent.mkdir(parents=True, exist_ok=True)
  payload = {
    "projectPath": str(prefs.get("projectPath", "")).strip(),
    "spec": str(prefs.get("spec", "")).strip(),
    "browser": str(prefs.get("browser", "")).strip(),
    "headless": bool(prefs.get("headless", True)),
  }
  _writeJson(path, payload)


def cypressEnvPath(projectPath: str) -> Path:
  """返回项目下的 cypress.env.json 路径。"""
  return Path(projectPath).expanduser() / ENV_FILE_NAME


def readEditableCypressEnv(projectPath: str) -> dict[str, object]:
  """只读取日常会改的四个字段，不返回密钥。"""
  envPath = cypressEnvPath(projectPath)
  if not envPath.is_file():
    raise CypressWeeklyError(f"未找到 {envPath}")
  try:
    data = json.loads(envPath.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as ex:
    raise CypressWeeklyError(f"无法读取 {envPath}: {ex}") from ex
  if not isinstance(data, dict):
    raise CypressWeeklyError(f"{envPath} 不是 JSON 对象")
  return {
    "xray_jira_integration_enabled": bool(
      data.get("xray_jira_integration_enabled", False)
    ),
    "test_execution_key": str(data.get("test_execution_key", "") or ""),
    "sprint": _asInt(data.get("sprint"), default=1),
    "week": _asInt(data.get("week"), default=1),
  }


def writeEditableCypressEnv(projectPath: str, fields: dict[str, object]) -> None:
  """只改四个字段，保留 cypress.env.json 其余内容与密钥。"""
  envPath = cypressEnvPath(projectPath)
  if not envPath.is_file():
    raise CypressWeeklyError(f"未找到 {envPath}")
  normalized = _normalizeEditableFields(fields)
  try:
    original = envPath.read_text(encoding="utf-8")
  except OSError as ex:
    raise CypressWeeklyError(f"无法读取 {envPath}: {ex}") from ex
  updated = original
  missing: list[str] = []
  for key in EDITABLE_ENV_KEYS:
    updated, replaced = _replaceJsonField(updated, key, normalized[key])
    if not replaced:
      missing.append(key)
  if missing:
    updated = _dumpWithMissingKeys(original, normalized, missing)
  if updated != original:
    _writeTextAtomic(envPath, updated)


def _defaultUsersConfigPath() -> Path:
  """webtools 根目录下的 users_config（不入库）。"""
  return Path(__file__).resolve().parents[2] / "config" / "users_config.json"


def _isPlaceholderCredential(value: str) -> bool:
  """判断 cypress.env 里是否为占位符。"""
  cleaned = (value or "").strip()
  if not cleaned:
    return True
  upper = cleaned.upper()
  if "YOUR_" in upper or "PLACEHOLDER" in upper:
    return True
  return False


def resolveXrayCredentials(
  username: str | None = None,
  usersConfigPath: str | Path | None = None,
) -> tuple[str, str]:
  """从环境变量或 users_config 解析 Xray 凭证（不记录日志）。"""
  envId = os.environ.get("XRAY_CLIENT_ID", "").strip()
  envSecret = os.environ.get("XRAY_CLIENT_SECRET", "").strip()
  if envId and envSecret:
    return envId, envSecret

  if not username:
    return "", ""

  configPath = Path(usersConfigPath) if usersConfigPath else _defaultUsersConfigPath()
  if not configPath.is_file():
    return "", ""
  try:
    data = json.loads(configPath.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as ex:
    logger.warning("读取 users_config 失败: %s", ex)
    return "", ""

  userBlock = data.get("users", {}).get(username) if isinstance(data, dict) else None
  if not isinstance(userBlock, dict):
    return "", ""
  xray = userBlock.get("xray", {})
  if not isinstance(xray, dict):
    return "", ""
  clientId = str(xray.get("client_id", "") or "").strip()
  clientSecret = str(xray.get("client_secret", "") or "").strip()
  if _isPlaceholderCredential(clientId) or _isPlaceholderCredential(clientSecret):
    return "", ""
  return clientId, clientSecret


def writeXraySecretsToCypressEnv(
  projectPath: str,
  clientId: str,
  clientSecret: str,
) -> None:
  """把 Xray OAuth 凭证写入 cypress.env.json（界面不展示）。"""
  if not clientId.strip() or not clientSecret.strip():
    raise CypressWeeklyError(
      "未配置 Xray 凭证：请在 config/users_config.json 的 xray.client_id / "
      "client_secret 中配置，或设置环境变量 XRAY_CLIENT_ID / XRAY_CLIENT_SECRET",
    )
  envPath = cypressEnvPath(projectPath)
  if not envPath.is_file():
    raise CypressWeeklyError(f"未找到 {envPath}")
  try:
    original = envPath.read_text(encoding="utf-8")
  except OSError as ex:
    raise CypressWeeklyError(f"无法读取 {envPath}: {ex}") from ex

  updated = original
  secrets = {
    "xray_client_id": clientId.strip(),
    "xray_client_secret": clientSecret.strip(),
  }
  missing: list[str] = []
  for key in XRAY_SECRET_ENV_KEYS:
    updated, replaced = _replaceJsonField(updated, key, secrets[key])
    if not replaced:
      missing.append(key)
  if missing:
    try:
      data = json.loads(original)
    except json.JSONDecodeError as ex:
      raise CypressWeeklyError(f"cypress.env.json 无法解析: {ex}") from ex
    if not isinstance(data, dict):
      raise CypressWeeklyError("cypress.env.json 不是 JSON 对象")
    for key in XRAY_SECRET_ENV_KEYS:
      data[key] = secrets[key]
    updated = json.dumps(data, indent="\t", ensure_ascii=False) + "\n"
  if updated != original:
    _writeTextAtomic(envPath, updated)


def applyXrayCredentialsToCypressEnv(
  projectPath: str,
  *,
  username: str | None = None,
  usersConfigPath: str | Path | None = None,
) -> None:
  """启动前注入 Xray client_id / client_secret，避免占位符导致 401。"""
  clientId, clientSecret = resolveXrayCredentials(username, usersConfigPath)
  writeXraySecretsToCypressEnv(projectPath, clientId, clientSecret)


def buildCypressCommand(
  spec: str,
  browser: str,
  headless: bool,
  npxCmd: str | None = None,
) -> list[str]:
  """组装与手工执行一致的 npx cypress run 命令。"""
  exe = npxCmd or _findNpx()
  cmd = [exe, "cypress", "run", "--spec", spec]
  if headless:
    cmd.append("--headless")
  cmd.extend(["--browser", browser])
  return cmd


def formatCypressCommand(cmd: list[str]) -> str:
  """把命令格式化成可阅读的一行，npx 不展示绝对路径。"""
  parts: list[str] = []
  for index, part in enumerate(cmd):
    shown = "npx" if index == 0 else part
    if any(ch in shown for ch in " *"):
      parts.append(f'"{shown}"')
    else:
      parts.append(shown)
  return " ".join(parts)


def startCypressWeeklyRun(
  *,
  projectPath: str,
  spec: str,
  browser: str,
  headless: bool,
  xrayEnabled: bool,
  testExecutionKey: str,
  sprint: int,
  week: int,
  stateDir: Path | None = None,
  commandOverride: list[str] | None = None,
  configUsername: str | None = None,
  usersConfigPath: str | Path | None = None,
) -> CypressRunState:
  """写入 env 后启动脱离页面的 Cypress 进程，并立即返回。"""
  project = _validateProjectPath(projectPath)
  cleanSpec = _validateSpec(spec)
  cleanBrowser = _validateBrowser(browser)
  fields = _normalizeEditableFields({
    "xray_jira_integration_enabled": xrayEnabled,
    "test_execution_key": testExecutionKey,
    "sprint": sprint,
    "week": week,
  })
  _validateExecutionKey(
    bool(fields["xray_jira_integration_enabled"]),
    str(fields["test_execution_key"]),
  )
  root = _stateDir(stateDir)
  current = refreshCypressWeeklyRun(root)
  if current is not None and current.state == "running":
    raise CypressWeeklyError(
      f"已有任务在运行（PID {current.pid}），请先停止或等待结束"
    )
  cmd = commandOverride or buildCypressCommand(cleanSpec, cleanBrowser, headless)
  writeEditableCypressEnv(str(project), fields)
  if bool(fields["xray_jira_integration_enabled"]):
    applyXrayCredentialsToCypressEnv(
      str(project),
      username=configUsername,
      usersConfigPath=usersConfigPath,
    )
  saveCypressWeeklyPrefs(
    {
      "projectPath": str(project),
      "spec": cleanSpec,
      "browser": cleanBrowser,
      "headless": headless,
    },
    root,
  )
  logPath = root / "cypress.log"
  _rotateLog(logPath)
  startedAt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  commandText = (
    formatCypressCommand(cmd) if commandOverride is None else " ".join(cmd)
  )
  logPath.parent.mkdir(parents=True, exist_ok=True)
  logPath.write_text(
    f"[{startedAt}] {commandText}\n",
    encoding="utf-8",
  )
  try:
    pid = launchDetachedProcess(cmd, project, logPath)
  except OSError as ex:
    raise CypressWeeklyError(f"启动 Cypress 失败: {ex}") from ex
  state = CypressRunState(
    pid=pid,
    logPath=str(logPath),
    projectPath=str(project),
    spec=cleanSpec,
    browser=cleanBrowser,
    headless=headless,
    command=commandText,
    startedAt=startedAt,
    state="running",
  )
  _writeState(root, state)
  logger.info("Cypress 周跑已启动 pid=%s", pid)
  return state


def stopCypressWeeklyRun(stateDir: Path | None = None) -> CypressRunState | None:
  """结束当前后台任务及其子进程。"""
  root = _stateDir(stateDir)
  state = refreshCypressWeeklyRun(root)
  if state is None:
    return None
  if state.state == "running":
    _killPidTree(state.pid)
    alive, exitCode = queryProcessExit(state.pid)
    state.state = "stopped"
    state.exitCode = None if alive else exitCode
    state.finishedAt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _applySummary(state)
    _writeState(root, state)
    logger.info("Cypress 周跑已停止 pid=%s", state.pid)
  return state


def refreshCypressWeeklyRun(stateDir: Path | None = None) -> CypressRunState | None:
  """根据进程是否存活刷新状态文件。"""
  root = _stateDir(stateDir)
  state = _readState(root)
  if state is None or state.state != "running":
    return state
  alive, exitCode = queryProcessExit(state.pid)
  if alive:
    before = (state.summary, state.tests, state.passing, state.failing)
    _applySummary(state)
    after = (state.summary, state.tests, state.passing, state.failing)
    if after != before:
      _writeState(root, state)
    return state
  if exitCode not in (0, None) or _summaryIndicatesFailure(state):
    state.state = "failed"
  else:
    state.state = "finished"
  state.exitCode = exitCode
  state.finishedAt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  _applySummary(state)
  _writeState(root, state)
  return state


def readCypressWeeklyLog(
  stateDir: Path | None = None,
  maxLines: int = 200,
) -> str:
  """读取当前日志末尾，并遮盖可能出现的密钥。"""
  root = _stateDir(stateDir)
  state = _readState(root)
  logPath = Path(state.logPath) if state else root / "cypress.log"
  return redactCypressLog(tailTextFile(logPath, maxLines=maxLines))


def redactCypressLog(text: str) -> str:
  """去掉 ANSI 颜色，并遮盖 token / secret。"""
  cleaned = ANSI_RE.sub("", text)
  return SECRET_RE.sub(r"\1\2[REDACTED]", cleaned)


def tailTextFile(path: Path, maxLines: int = 200, maxBytes: int = 262144) -> str:
  """只读文件末尾，避免整份大日志反复载入。"""
  if not path.is_file():
    return ""
  try:
    size = path.stat().st_size
    with path.open("rb") as handle:
      if size > maxBytes:
        handle.seek(size - maxBytes)
      data = handle.read()
  except OSError as ex:
    logger.warning("读取 Cypress 日志失败: %s", ex)
    return ""
  text = data.decode("utf-8", errors="replace")
  if size > maxBytes:
    text = text.split("\n", 1)[-1]
  return "\n".join(text.splitlines()[-maxLines:])


def launchDetachedProcess(cmd: list[str], cwd: Path, logPath: Path) -> int:
  """启动独立进程组，把标准输出写入日志文件。

  切换 Streamlit 页面不会停掉它，因为它不属于某一次页面脚本。
  关掉整个 Web 应用进程时，这次运行会一起结束。
  """
  logPath.parent.mkdir(parents=True, exist_ok=True)
  handle = open(logPath, "ab", buffering=0)
  try:
    kwargs: dict[str, object] = {
      "args": cmd,
      "cwd": str(cwd),
      "stdout": handle,
      "stderr": subprocess.STDOUT,
      "stdin": subprocess.DEVNULL,
      "env": _childEnv(),
      "close_fds": True,
    }
    if platform.system() == "Windows":
      # DETACHED_PROCESS 会丢掉 .cmd（npx）的标准输出，日志会是空的。
      # 新进程组已足够在切换 Streamlit 页面时不被一起停掉。
      kwargs["creationflags"] = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
      )
    else:
      kwargs["start_new_session"] = True
    proc = subprocess.Popen(**kwargs)
    return int(proc.pid)
  finally:
    handle.close()


def queryProcessExit(pid: int) -> tuple[bool, int | None]:
  """返回 (是否仍在运行, 退出码)。运行中退出码为 None。"""
  if pid <= 0:
    return False, None
  if platform.system() == "Windows":
    return _queryWindowsProcess(pid)
  try:
    os.kill(pid, 0)
  except OSError:
    return False, None
  return True, None


def _queryWindowsProcess(pid: int) -> tuple[bool, int | None]:
  """用 OpenProcess 判断 Windows 进程是否仍在运行。"""
  kernel32 = ctypes.windll.kernel32
  processQuery = 0x1000
  kernel32.OpenProcess.argtypes = [
    ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32,
  ]
  kernel32.OpenProcess.restype = ctypes.c_void_p
  kernel32.GetExitCodeProcess.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
  ]
  kernel32.GetExitCodeProcess.restype = ctypes.c_bool
  kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
  kernel32.CloseHandle.restype = ctypes.c_bool
  handle = kernel32.OpenProcess(processQuery, False, pid)
  if not handle:
    return False, None
  try:
    code = ctypes.c_uint32()
    if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
      return False, None
    stillActive = 259
    if code.value == stillActive:
      return True, None
    return False, int(code.value)
  finally:
    kernel32.CloseHandle(handle)


def _killPidTree(pid: int) -> None:
  """结束进程树。"""
  if pid <= 0:
    return
  if platform.system() == "Windows":
    try:
      subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
      )
    except Exception as ex:
      logger.warning("停止 Cypress 进程失败 pid=%s: %s", pid, ex)
    return
  try:
    os.kill(pid, 15)
  except OSError as ex:
    logger.warning("停止 Cypress 进程失败 pid=%s: %s", pid, ex)


def _findNpx() -> str:
  """查找 npx 可执行文件。"""
  import shutil
  if platform.system() == "Windows":
    npxPath = shutil.which("npx.cmd") or shutil.which("npx")
    if npxPath:
      return npxPath
    raise CypressWeeklyError("未找到 npx，请确认 Node.js 已安装并加入 PATH")
  return "npx"


def _childEnv() -> dict[str, str]:
  """子进程环境：关掉颜色，避免日志里堆 ANSI。"""
  env = os.environ.copy()
  env["NO_COLOR"] = "1"
  env["FORCE_COLOR"] = "0"
  return env


def _validateProjectPath(projectPath: str) -> Path:
  """确认 Cypress 项目目录存在。"""
  project = Path(projectPath).expanduser()
  if not str(project).strip() or not project.is_dir():
    raise CypressWeeklyError(f"Cypress 项目路径不存在: {projectPath}")
  return project.resolve()


def _validateSpec(spec: str) -> str:
  """校验 spec，拒绝可能被 shell 误用的字符。"""
  cleaned = (spec or "").strip()
  if not cleaned:
    raise CypressWeeklyError("请填写 Cypress spec")
  if any(ch in cleaned for ch in "\n\r\"'|&;<>"):
    raise CypressWeeklyError("spec 含有不允许的字符")
  return cleaned


def _validateBrowser(browser: str) -> str:
  """校验浏览器名称。"""
  cleaned = (browser or "").strip().lower()
  if cleaned not in ALLOWED_BROWSERS:
    allowed = ", ".join(ALLOWED_BROWSERS)
    raise CypressWeeklyError(f"不支持的浏览器: {browser}（可选 {allowed}）")
  return cleaned


def _validateExecutionKey(xrayEnabled: bool, testExecutionKey: str) -> None:
  """开启 Xray 时要求 Test Execution Key 格式正确。"""
  key = testExecutionKey.strip()
  if xrayEnabled and not key:
    raise CypressWeeklyError("已开启 Xray 集成，请填写 Test Execution Key")
  if key and not EXECUTION_KEY_RE.match(key):
    raise CypressWeeklyError("Test Execution Key 格式应为类似 SP-37670")


def _normalizeEditableFields(fields: dict[str, object]) -> dict[str, object]:
  """把四个字段规范成写入 JSON 的类型。"""
  sprint = _asInt(fields.get("sprint"), default=0)
  week = _asInt(fields.get("week"), default=0)
  if sprint < 1:
    raise CypressWeeklyError("sprint 必须是大于 0 的整数")
  if week < 1 or week > 53:
    raise CypressWeeklyError("week 必须是 1 到 53 的整数")
  return {
    "xray_jira_integration_enabled": bool(fields.get("xray_jira_integration_enabled")),
    "test_execution_key": str(fields.get("test_execution_key", "") or "").strip(),
    "sprint": sprint,
    "week": week,
  }


def _asInt(value: object, default: int) -> int:
  """把 JSON 数字或数字字符串转成 int。"""
  if isinstance(value, bool) or value is None:
    return default
  if isinstance(value, int):
    return value
  if isinstance(value, float) and value.is_integer():
    return int(value)
  if isinstance(value, str) and value.strip().lstrip("-").isdigit():
    return int(value.strip())
  return default


def _replaceJsonField(text: str, key: str, value: object) -> tuple[str, bool]:
  """替换已有 JSON 字段，不改动文件其他内容。"""
  encoded = json.dumps(value, ensure_ascii=False)
  pattern = re.compile(JSON_VALUE_RE_TEMPLATE.format(key=re.escape(key)))
  updated, count = pattern.subn(lambda match: match.group(1) + encoded, text, count=1)
  return updated, count == 1


def _dumpWithMissingKeys(
  original: str,
  fields: dict[str, object],
  missing: list[str],
) -> str:
  """字段不存在时回退为整文件写回，并保留其余键。"""
  try:
    data = json.loads(original)
  except json.JSONDecodeError as ex:
    raise CypressWeeklyError(
      f"cypress.env.json 缺少字段 {', '.join(missing)}，且文件无法解析: {ex}"
    ) from ex
  if not isinstance(data, dict):
    raise CypressWeeklyError("cypress.env.json 不是 JSON 对象")
  for key in EDITABLE_ENV_KEYS:
    data[key] = fields[key]
  return json.dumps(data, indent="\t", ensure_ascii=False) + "\n"


def _rotateLog(logPath: Path) -> None:
  """新运行开始前把上一份日志改名为 previous。"""
  if not logPath.is_file() or logPath.stat().st_size == 0:
    return
  previous = logPath.with_name("cypress.previous.log")
  try:
    if previous.exists():
      previous.unlink()
    logPath.replace(previous)
  except OSError as ex:
    logger.warning("轮转 Cypress 日志失败: %s", ex)


def _applySummary(state: CypressRunState) -> None:
  """从日志末尾提取 Cypress 汇总行。"""
  text = tailTextFile(Path(state.logPath), maxLines=80)
  match = None
  for candidate in SUMMARY_RE.finditer(text):
    match = candidate
  if match is None:
    return
  state.summary = " ".join(match.group(1).split())
  state.tests = _countOrNone(match.group(3))
  state.passing = _countOrNone(match.group(4))
  state.failing = _countOrNone(match.group(5))


def _summaryIndicatesFailure(state: CypressRunState) -> bool:
  """汇总行是否表明有失败用例。"""
  _applySummary(state)
  if state.failing:
    return True
  return "failed" in (state.summary or "").lower()


def _countOrNone(raw: str) -> int | None:
  """Cypress 表格里的 '-' 视为没有计数。"""
  if raw == "-" or not raw.isdigit():
    return None
  return int(raw)


def _prefsPath(stateDir: Path | None) -> Path:
  """偏好文件路径。"""
  return _stateDir(stateDir) / "prefs.json"


def _statePath(stateDir: Path) -> Path:
  """状态文件路径。"""
  return stateDir / "run_status.json"


def _stateDir(stateDir: Path | None) -> Path:
  """解析状态目录。"""
  return stateDir or defaultCypressStateDir()


def _readState(stateDir: Path) -> CypressRunState | None:
  """读取状态文件。损坏时返回 None。"""
  path = _statePath(stateDir)
  if not path.is_file():
    return None
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as ex:
    logger.warning("读取 Cypress 运行状态失败: %s", ex)
    return None
  if not isinstance(data, dict):
    return None
  try:
    return CypressRunState(
      pid=int(data.get("pid") or 0),
      logPath=str(data.get("logPath") or ""),
      projectPath=str(data.get("projectPath") or ""),
      spec=str(data.get("spec") or ""),
      browser=str(data.get("browser") or ""),
      headless=bool(data.get("headless", True)),
      command=str(data.get("command") or ""),
      startedAt=str(data.get("startedAt") or ""),
      state=str(data.get("state") or ""),
      exitCode=_optionalInt(data.get("exitCode")),
      finishedAt=data.get("finishedAt"),
      summary=str(data.get("summary") or ""),
      tests=_optionalInt(data.get("tests")),
      passing=_optionalInt(data.get("passing")),
      failing=_optionalInt(data.get("failing")),
    )
  except (TypeError, ValueError) as ex:
    logger.warning("Cypress 运行状态字段无效: %s", ex)
    return None


def _optionalInt(value: object) -> int | None:
  """把可空数字转成 int。"""
  if value is None or value == "":
    return None
  try:
    return int(value)
  except (TypeError, ValueError):
    return None


def _writeState(stateDir: Path, state: CypressRunState) -> None:
  """原子写入运行状态。"""
  stateDir.mkdir(parents=True, exist_ok=True)
  _writeJson(_statePath(stateDir), asdict(state))


def _writeJson(path: Path, payload: dict[str, object]) -> None:
  """原子写入 JSON。"""
  text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
  _writeTextAtomic(path, text)


def _writeTextAtomic(path: Path, text: str) -> None:
  """先写临时文件再替换，避免写到一半损坏原文件。"""
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix(path.suffix + ".tmp")
  tmp.write_text(text, encoding="utf-8")
  tmp.replace(path)
