"""Jenkins API 客户端（从 pages/6_🔧_Jenkins_Deploy.py 下沉的纯 HTTP 逻辑）。

不依赖 Streamlit，可直接单元测试。页面通过 log_cb / log_q 回调接收日志输出。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

from modules.user_config_loader import build_jenkins_auth

logger = logging.getLogger(__name__)


def buildJobUrl(service: str, jenkins_url: str, folder: str = "PP") -> str:
    """构建 Jenkins job URL"""
    return f"{jenkins_url.rstrip('/')}/job/{folder}/job/{service}"


def triggerBuild(service: str, branch: str, auth: HTTPBasicAuth,
                 jenkins_url: str, folder: str = "PP") -> Optional[str]:
    """触发构建，返回队列 URL"""
    url = f"{buildJobUrl(service, jenkins_url, folder)}/buildWithParameters"
    try:
        resp = requests.post(url, auth=auth, params={"BRANCH": branch}, timeout=30)
        if resp.status_code in (200, 201):
            return resp.headers.get("Location")
        return None
    except Exception as e:
        logging.warning(f"[Jenkins] triggerBuild failed for {service}: {e}")
        return None


def getBuildNumber(queue_url: str, auth: HTTPBasicAuth,
                   timeout: int = 90) -> Optional[int]:
    """从队列 URL 获取构建编号"""
    api_url = f"{queue_url}api/json"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(api_url, auth=auth, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("executable"):
                    return data["executable"]["number"]
        except Exception as e:
            logging.warning(f"[Jenkins] getBuildNumber polling error: {e}")
        time.sleep(3)
    return None


_CONSOLE_KEYWORDS = (
    "error", "exception", "failed", "failure", "fatal",
    "warning", "warn",
    "build", "deploy", "step", "stage",
    "success", "successfully", "finished",
    "started", "running", "pushing", "pulling",
    "docker", "kubectl", "helm",
)

_CONSOLE_NOISE_PREFIXES = (
    "downloading", "progress", "transferring",
    "send request", "receive response",
    "[debug]", "[trace]",
)


def isKeyConsoleLine(line: str) -> bool:
    """判断是否为需要展示的关键日志行"""
    lower = line.lower().strip()
    if not lower:
        return False
    for prefix in _CONSOLE_NOISE_PREFIXES:
        if lower.startswith(prefix):
            return False
    for kw in _CONSOLE_KEYWORDS:
        if kw in lower:
            return True
    return False


def waitForBuild(service: str, build_number: int, auth: HTTPBasicAuth,
                 jenkins_url: str, log_cb: Callable[[str], None],
                 folder: str = "PP", build_timeout: int = 1800) -> bool:
    """轮询等待构建完成，通过 log_cb 回调输出日志（只输出关键行）"""
    job_url = buildJobUrl(service, jenkins_url, folder)
    build_url = f"{job_url}/{build_number}/api/json"
    console_url = f"{job_url}/{build_number}/consoleText"
    start = time.time()
    interval = 15
    last_console_len = 0
    last_progress_log = 0

    while time.time() - start < build_timeout:
        try:
            resp = requests.get(build_url, auth=auth, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                building = data.get("building", False)
                result = data.get("result")

                try:
                    cr = requests.get(console_url, auth=auth, timeout=10)
                    if cr.status_code == 200:
                        full_text = cr.text
                        new_text = full_text[last_console_len:]
                        last_console_len = len(full_text)
                        for line in new_text.splitlines():
                            if isKeyConsoleLine(line):
                                log_cb(f"  │ {line.strip()}")
                except Exception as e:
                    logging.debug(f"[Jenkins] console fetch error (non-fatal): {e}")

                if not building:
                    return result == "SUCCESS"

                now = time.time()
                if now - last_progress_log >= 30:
                    elapsed = int(now - start)
                    log_cb(f"⏳ [{service}] 构建进行中… 已耗时 {elapsed // 60}m{elapsed % 60}s")
                    last_progress_log = now
        except Exception as e:
            log_cb(f"⚠️ [{service}] 查询状态异常: {e}")

        time.sleep(interval)

    log_cb(f"⏱️ [{service}] 构建监控超时")
    return False


def executeDeploy(service: str, branch: str, auth: HTTPBasicAuth,
                  jenkins_url: str, log_cb: Callable[[str], None],
                  folder: str = "PP") -> bool:
    """执行单服务完整部署流程"""
    log_cb(f"🚀 [{service}] 触发构建 (分支: {branch})")
    queue_url = triggerBuild(service, branch, auth, jenkins_url, folder)
    if not queue_url:
        log_cb(f"❌ [{service}] 触发失败，请检查认证信息和服务名称")
        return False

    log_cb(f"📋 [{service}] 已加入队列，等待分配构建编号…")
    build_number = getBuildNumber(queue_url, auth)
    if not build_number:
        log_cb(f"❌ [{service}] 无法获取构建编号，队列超时")
        return False

    build_link = f"{buildJobUrl(service, jenkins_url, folder)}/{build_number}"
    log_cb(f"🔗 [{service}] 构建 #{build_number} 已启动: {build_link}")
    success = waitForBuild(service, build_number, auth, jenkins_url, log_cb, folder)

    if success:
        log_cb(f"✅ [{service}] 构建 #{build_number} 成功！")
    else:
        log_cb(f"❌ [{service}] 构建 #{build_number} 失败")
    return success


def fetchRecentBranches(service: str, auth: HTTPBasicAuth,
                        jenkins_url: str, folder: str = "PP",
                        max_count: int = 5) -> List[dict]:
    """查询最近成功构建列表，返回 [{"label": ..., "branch": ...}, ...]"""
    base = jenkins_url.rstrip("/")
    tree = "builds[number,result,displayName,timestamp,actions[parameters[name,value]]]{0,20}"
    url = f"{base}/job/{folder}/job/{service}/api/json?tree={tree}"
    tz_cst = timezone(timedelta(hours=8))
    try:
        resp = requests.get(url, auth=auth, timeout=15)
        if resp.status_code != 200:
            return []
        builds = resp.json().get("builds", [])
    except Exception:
        return []

    results = []
    for build in builds:
        if build.get("result") != "SUCCESS":
            continue

        number = build.get("number", "?")
        display_name = build.get("displayName", f"#{number}")
        ts = build.get("timestamp", 0)

        branch = ""
        for action in build.get("actions", []):
            for param in action.get("parameters", []):
                if param.get("name") == "BRANCH":
                    branch = param.get("value", "")
                    break
            if branch:
                break

        if ts:
            dt = datetime.fromtimestamp(ts / 1000, tz=tz_cst)
            time_str = dt.strftime("%b %d, %Y, %I:%M %p")
        else:
            time_str = "N/A"

        label = f"#{number}  {branch or display_name}  ({time_str})"
        results.append({"label": label, "branch": branch or "", "number": number})

        if len(results) >= max_count:
            break

    return results


def runDeployThread(services_branches: Dict[str, str], auth: HTTPBasicAuth,
                    jenkins_url: str, is_concurrent: bool,
                    log_q: "queue.Queue", folder: str = "PP"):
    """后台部署线程入口"""
    total = len(services_branches)
    mode = "并发" if is_concurrent else "顺序"
    log_q.put(f"═══ {mode}部署开始，共 {total} 个服务 ═══\n")

    results: Dict[str, bool] = {}

    if is_concurrent:
        def deploy_one(svc: str, br: str):
            return svc, executeDeploy(svc, br, auth, jenkins_url,
                                      log_cb=lambda m: log_q.put(m),
                                      folder=folder)

        with ThreadPoolExecutor(max_workers=total) as executor:
            futures = {
                executor.submit(deploy_one, svc, br): svc
                for svc, br in services_branches.items()
            }
            for future in as_completed(futures):
                try:
                    svc, ok = future.result()
                    results[svc] = ok
                except Exception as e:
                    svc = futures[future]
                    log_q.put(f"❌ [{svc}] 异常: {e}")
                    results[svc] = False
    else:
        for idx, (svc, br) in enumerate(services_branches.items(), 1):
            log_q.put(f"\n▶ [{idx}/{total}] 开始部署 {svc}")
            results[svc] = executeDeploy(svc, br, auth, jenkins_url,
                                         log_cb=lambda m: log_q.put(m),
                                         folder=folder)

    ok = sum(1 for v in results.values() if v)
    log_q.put(f"\n═══ {mode}部署完成: {ok}/{total} 成功 ═══")
    log_q.put(("__DONE__", results))


def runConnectionTest(username: str, api_token: str, jenkins_url: str,
                      log_q: "queue.Queue"):
    """后台测试 Jenkins 连接（PP 环境）"""
    auth = build_jenkins_auth(username, api_token)
    base = jenkins_url.rstrip("/")

    def put(msg: str):
        log_q.put(msg)

    put("══════════════════════════════════")
    put("  Jenkins API 连接测试")
    put("══════════════════════════════════")
    put(f"  URL   : {base}")
    put(f"  用户  : {username}")
    put(f"  Token : {'*' * 10}{api_token[-4:] if len(api_token) >= 4 else '****'}")
    put("")

    put("【测试 1】验证凭证有效性（/me/api/json）…")
    auth_ok = False
    try:
        r = requests.get(f"{base}/me/api/json", auth=auth, timeout=10)
        if r.status_code == 200:
            d = r.json()
            put(f"  ✅ 成功  Full Name: {d.get('fullName', 'N/A')}")
            put(f"         User ID  : {d.get('id', 'N/A')}")
            auth_ok = True
        elif r.status_code in (401, 403):
            # /me 不可用时，回退用根 API 做凭证探测
            put(f"  ⚠️ /me 返回 {r.status_code}，尝试根 API 验证…")
            r2 = requests.get(f"{base}/api/json", auth=auth, timeout=10)
            if r2.status_code == 200:
                put(f"  ✅ 根 API 可访问，凭证有效")
                auth_ok = True
            else:
                put(f"  ❌ 凭证无效  状态码: {r2.status_code}")
                put(f"         响应: {r2.text[:300]}")
                put("══════════════════════════════════")
                log_q.put(("__TEST_DONE__", False))
                return
        else:
            put(f"  ❌ 失败  状态码: {r.status_code}")
            put(f"         响应: {r.text[:300]}")
            put("══════════════════════════════════")
            log_q.put(("__TEST_DONE__", False))
            return
    except Exception as e:
        put(f"  ❌ 异常: {e}")
        log_q.put(("__TEST_DONE__", False))
        return

    put("")
    put("【测试 2】获取 PP 文件夹任务列表…")
    try:
        r = requests.get(f"{base}/job/PP/api/json", auth=auth, timeout=10)
        if r.status_code == 200:
            jobs = r.json().get("jobs", [])
            put(f"  ✅ 成功  共 {len(jobs)} 个任务")
            for j in jobs[:5]:
                put(f"         - {j['name']}")
            if len(jobs) > 5:
                put(f"         … 还有 {len(jobs) - 5} 个")
        else:
            put(f"  ❌ 失败  状态码: {r.status_code}")
    except Exception as e:
        put(f"  ❌ 异常: {e}")

    put("")
    put("【测试 3】访问 pp-public-api 任务详情…")
    try:
        r = requests.get(f"{base}/job/PP/job/pp-public-api/api/json", auth=auth, timeout=10)
        if r.status_code == 200:
            d = r.json()
            put(f"  ✅ 成功  任务: {d.get('name', 'N/A')}")
            put(f"         可构建: {d.get('buildable', False)}")
            lb = d.get("lastBuild")
            if lb:
                put(f"         最近构建: #{lb.get('number', 'N/A')}")
        else:
            put(f"  ⚠️ 状态码: {r.status_code}（可能权限不足）")
    except Exception as e:
        put(f"  ❌ 异常: {e}")

    put("")
    put("══════════════════════════════════")
    put("  ✅ 连接测试完成，认证有效")
    put("══════════════════════════════════")
    log_q.put(("__TEST_DONE__", True))


def runProdInspect(username: str, api_token: str, jenkins_url: str,
                   log_q: "queue.Queue", prod_services: List[str]):
    """只读查询生产服务状态，绝不触发构建"""
    auth = build_jenkins_auth(username, api_token)
    base = jenkins_url.rstrip("/")

    def put(msg: str):
        log_q.put(msg)

    put("══════════════════════════════════════════")
    put("  🔍 生产服务巡检（只读模式）")
    put("══════════════════════════════════════════")
    put(f"  Jenkins : {base}")
    put(f"  服务数量: {len(prod_services)} 个")
    put("")

    # 先尝试获取 Prod 文件夹列表
    put("【步骤 1】探测 Prod 文件夹结构…")
    try:
        r = requests.get(f"{base}/job/Prod/api/json", auth=auth, timeout=10)
        if r.status_code == 200:
            folder_jobs = r.json().get("jobs", [])
            put(f"  ✅ Prod 文件夹存在，共 {len(folder_jobs)} 个任务")
            folder_names = [j["name"] for j in folder_jobs]
            # 检查目标服务是否存在于 Prod 文件夹
            for svc in prod_services:
                found = svc in folder_names
                status = "✅ 存在" if found else "⚠️  未找到"
                put(f"     {status} : {svc}")
        elif r.status_code == 404:
            put("  ⚠️  Prod 文件夹不存在或路径不同，将逐个直接查询服务")
        else:
            put(f"  ❌ 查询失败  状态码: {r.status_code}")
    except Exception as e:
        put(f"  ❌ 异常: {e}")

    put("")
    put("【步骤 2】逐一查询各服务详情（Prod 路径）…")

    for svc in prod_services:
        put(f"\n  ▷ {svc}")
        # 尝试 /job/Prod/job/<svc>
        url = f"{base}/job/Prod/job/{svc}/api/json"
        try:
            r = requests.get(url, auth=auth, timeout=10)
            if r.status_code == 200:
                d = r.json()
                buildable = d.get("buildable", False)
                desc = d.get("description") or "（无描述）"
                lb = d.get("lastBuild")
                ls = d.get("lastSuccessfulBuild")
                lf = d.get("lastFailedBuild")
                put(f"    ✅ 可访问  可构建: {buildable}")
                put(f"    描述      : {desc[:80]}")
                if lb:
                    put(f"    最近构建  : #{lb.get('number', 'N/A')}")
                if ls:
                    put(f"    最近成功  : #{ls.get('number', 'N/A')}")
                if lf:
                    put(f"    最近失败  : #{lf.get('number', 'N/A')}")
            elif r.status_code == 404:
                put(f"    ⚠️  /job/Prod/job/{svc} 不存在，尝试顶层路径…")
                # fallback：直接 /job/<svc>
                r2 = requests.get(f"{base}/job/{svc}/api/json", auth=auth, timeout=10)
                if r2.status_code == 200:
                    d2 = r2.json()
                    put(f"    ✅ 顶层路径可访问  可构建: {d2.get('buildable', False)}")
                    lb2 = d2.get("lastBuild")
                    if lb2:
                        put(f"    最近构建: #{lb2.get('number', 'N/A')}")
                else:
                    put(f"    ❌ 顶层路径也不存在  状态码: {r2.status_code}")
            else:
                put(f"    ❌ 状态码: {r.status_code}")
                put(f"    响应: {r.text[:200]}")
        except Exception as e:
            put(f"    ❌ 异常: {e}")

    put("")
    put("══════════════════════════════════════════")
    put("  ✅ 巡检完成（未触发任何构建）")
    put("══════════════════════════════════════════")
    log_q.put(("__INSPECT_DONE__", None))
