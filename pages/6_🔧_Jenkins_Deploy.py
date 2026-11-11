import streamlit as st
import sys
import time
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from modules.user_config_loader import get_jenkins_config, get_user_config_loader, build_jenkins_auth

try:
    from streamlit_cookies_manager import EncryptedCookieManager
    COOKIES_AVAILABLE = True
except ImportError:
    COOKIES_AVAILABLE = False

st.set_page_config(
    page_title="Jenkins 部署",
    page_icon="🔧",
    layout="wide"
)

FIXED_SERVICES = ["pp-public-api", "pp-psi-service"]

# 生产环境服务列表（Prod 文件夹）
PROD_SERVICES = [
    "prod-public-api",
    "prod-public-api-job",
    "prod-psi-service",
    "prod-psi-web",
]
PROD_BRANCH = "master"

# 生产部署解锁口令（当前阶段固定为 None，永不解锁）
PROD_DEPLOY_ENABLED = True

JENKINS_URL_DEFAULT = "https://jenkins.example.com"

# ── 检查用户 ──────────────────────────────────────────────────────
from modules.page_common import require_current_user

current_user = require_current_user()
user_jenkins_cfg = get_jenkins_config(current_user)

cookies = None
if COOKIES_AVAILABLE:
    cookies = EncryptedCookieManager(
        prefix="jenkins_deploy_" + current_user + "_",
        password="jenkins-deploy-" + current_user + "-cookie-key"
    )
    if not cookies.ready():
        st.stop()

config_username = user_jenkins_cfg.get("username", "") if user_jenkins_cfg else ""
config_token = user_jenkins_cfg.get("api_token", "") if user_jenkins_cfg else ""
config_url = user_jenkins_cfg.get("jenkins_url", JENKINS_URL_DEFAULT) if user_jenkins_cfg else JENKINS_URL_DEFAULT
saved_username = cookies.get("username", "") if cookies else ""
saved_token = cookies.get("api_token", "") if cookies else ""
saved_url = cookies.get("jenkins_url", "") if cookies else ""
if not saved_username:
    saved_username = config_username
if not saved_token:
    saved_token = config_token
if not saved_url:
    saved_url = config_url

def saveJenkinsCredentials(username: str, api_token: str, jenkins_url: str) -> None:
    if not cookies or not api_token:
        return
    cookies["username"] = username
    cookies["api_token"] = api_token
    cookies["jenkins_url"] = jenkins_url
    cookies.save()

# ── Session State 初始化 ──────────────────────────────────────────
defaults = {
    "jenkins_logs": [],
    "jenkins_deploying": False,
    "jenkins_results": {},
    "jenkins_done": False,
    "jenkins_deploy_mode": "sequential",
    "jenkins_services_branches": {},
    "jenkins_username_input": saved_username,
    "jenkins_token_input": saved_token,
    "jenkins_url_saved": saved_url,
    "jenkins_test_logs": [],
    "jenkins_test_running": False,
    # Prod tab 专用
    "prod_inspect_logs": [],
    "prod_inspect_running": False,
    "prod_unlock_input": "",
    # PP 查询最新分支
    "pp_branch_options": {},
    "pp_branch_fetching": {},
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


from modules.jenkins_client import (
    buildJobUrl,
    triggerBuild,
    getBuildNumber,
    waitForBuild,
    executeDeploy,
    fetchRecentBranches,
    runDeployThread,
    runConnectionTest,
    runProdInspect,
)


# ── 全局队列（跨 rerun 共享） ─────────────────────────────────────
if "jenkins_log_queue" not in st.session_state:
    st.session_state.jenkins_log_queue = queue.Queue()
if "jenkins_test_queue" not in st.session_state:
    st.session_state.jenkins_test_queue = queue.Queue()
if "prod_inspect_queue" not in st.session_state:
    st.session_state.prod_inspect_queue = queue.Queue()

deploy_q: queue.Queue = st.session_state.jenkins_log_queue
test_q: queue.Queue = st.session_state.jenkins_test_queue
inspect_q: queue.Queue = st.session_state.prod_inspect_queue


# ── UI 渲染 ──────────────────────────────────────────────────────
user_display = get_user_config_loader().get_user_display_name(current_user)
st.title("🔧 Jenkins 部署工具")
st.info(f"👤 当前使用者: **{user_display}** ({current_user})")
st.markdown("---")

# ── 侧边栏 ───────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Jenkins 认证")

    jenkins_url_val = st.text_input(
        "Jenkins URL",
        value=st.session_state.jenkins_url_saved,
        key="jenkins_url_input"
    )
    jenkins_user_val = st.text_input(
        "用户名 (Azure AD Object ID)",
        value=st.session_state.jenkins_username_input,
        key="jenkins_user_field"
    )
    jenkins_token_val = st.text_input(
        "API Token",
        type="password",
        value=st.session_state.jenkins_token_input,
        key="jenkins_token_field"
    )

    st.session_state.jenkins_url_saved = jenkins_url_val
    st.session_state.jenkins_username_input = jenkins_user_val
    st.session_state.jenkins_token_input = jenkins_token_val

    st.markdown("---")

    # ── 连接测试区 ────────────────────────────────────────────
    st.subheader("🔌 连接测试")
    test_btn = st.button(
        "🔍 测试 Jenkins 连接",
        use_container_width=True,
        disabled=st.session_state.jenkins_test_running,
        key="test_conn_btn"
    )

    if test_btn:
        if not jenkins_user_val or not jenkins_token_val:
            st.error("请先填写用户名和 Token")
        else:
            st.session_state.jenkins_test_logs = []
            while not test_q.empty():
                try:
                    test_q.get_nowait()
                except Exception:
                    break
            st.session_state.jenkins_test_running = True
            threading.Thread(
                target=runConnectionTest,
                args=(jenkins_user_val, jenkins_token_val, jenkins_url_val, test_q),
                daemon=True
            ).start()
            st.rerun()

    if st.session_state.jenkins_test_running or st.session_state.jenkins_test_logs:
        while not test_q.empty():
            try:
                item = test_q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__TEST_DONE__":
                    st.session_state.jenkins_test_running = False
                    if item[1]:
                        saveJenkinsCredentials(
                            jenkins_user_val, jenkins_token_val, jenkins_url_val
                        )
                else:
                    st.session_state.jenkins_test_logs.append(str(item))
            except Exception:
                break

        if st.session_state.jenkins_test_running:
            st.info("⏳ 测试中…")
            time.sleep(0.8)
            st.rerun()

        if st.session_state.jenkins_test_logs:
            st.code("\n".join(st.session_state.jenkins_test_logs), language=None)

    st.markdown("---")

    if st.session_state.jenkins_deploying:
        st.warning("⏳ 部署进行中…")
    elif st.session_state.jenkins_results:
        st.subheader("📊 上次部署结果")
        for svc, ok in st.session_state.jenkins_results.items():
            if ok:
                st.success(f"✅ {svc}")
            else:
                st.error(f"❌ {svc}")


# ── 主体导航（单选渲染，避免 st.tabs 多面板叠显）────────────────
prod_tab_label = "🏭 生产环境部署" if PROD_DEPLOY_ENABLED else "🏭 生产环境（调试）"
JENKINS_TAB_PP = "🔧 PP 环境部署"
JENKINS_TAB_OPTIONS = [JENKINS_TAB_PP, prod_tab_label]

if "jenkins_active_tab" not in st.session_state:
    st.session_state.jenkins_active_tab = JENKINS_TAB_OPTIONS[0]
if st.session_state.jenkins_active_tab not in JENKINS_TAB_OPTIONS:
    st.session_state.jenkins_active_tab = JENKINS_TAB_OPTIONS[0]

active_tab = st.segmented_control(
    "功能导航",
    options=JENKINS_TAB_OPTIONS,
    key="jenkins_active_tab",
    label_visibility="collapsed",
    required=True,
    width="stretch"
)
st.markdown("---")


# ════════════════════════════════════════════════════════════════
# Tab 1：PP 环境部署
# ════════════════════════════════════════════════════════════════
if active_tab == JENKINS_TAB_PP:
    st.subheader("🎯 PP 环境部署配置")
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("**填写各服务的分支号（留空则跳过该服务）**")

        # ── 服务分支输入区（form 外，支持"查最新"按钮） ────────────
        for svc in FIXED_SERVICES:
            svc_col_input, svc_col_btn = st.columns([4, 1])
            with svc_col_input:
                st.text_input(
                    f"🔹 {svc}",
                    placeholder="例如: release-1.2.248 或 SP-30520",
                    key=f"branch_{svc}"
                )
            with svc_col_btn:
                st.write("")
                fetch_clicked = st.button(
                    "查最新",
                    key=f"fetch_btn_{svc}",
                    use_container_width=True,
                    help=f"查询 {svc} 最近 5 次成功构建的分支"
                )

            if fetch_clicked:
                if not jenkins_user_val or not jenkins_token_val:
                    st.warning(f"⚠️ 请先在侧边栏填写认证信息")
                else:
                    st.session_state.pp_branch_fetching[svc] = True
                    auth_tmp = build_jenkins_auth(jenkins_user_val, jenkins_token_val)
                    options = fetchRecentBranches(svc, auth_tmp, jenkins_url_val, "PP")
                    st.session_state.pp_branch_options[svc] = options
                    st.session_state.pp_branch_fetching[svc] = False
                    st.rerun()

            options_for_svc = st.session_state.pp_branch_options.get(svc, [])
            if st.session_state.pp_branch_fetching.get(svc):
                st.caption(f"⏳ 查询中…")
            elif options_for_svc:
                labels = [o["label"] for o in options_for_svc]

                def onSelectBranch(svc_name: str = svc, opts: List[dict] = options_for_svc):
                    """将下拉选择的分支名写入对应的 text_input"""
                    sel_label = st.session_state.get(f"select_{svc_name}")
                    if sel_label:
                        matched = next((o for o in opts if o["label"] == sel_label), None)
                        if matched and matched["branch"]:
                            st.session_state[f"branch_{svc_name}"] = matched["branch"]

                st.selectbox(
                    f"选择分支（点击后自动填入上方输入框）",
                    options=[""] + labels,
                    key=f"select_{svc}",
                    on_change=onSelectBranch,
                    label_visibility="collapsed"
                )
            elif f"fetch_btn_{svc}" in st.session_state:
                pass

        st.markdown("---")

        # ── 部署模式 + 提交按钮（保留在 form 内） ───────────────────
        with st.form("jenkins_deploy_form"):
            deploy_mode = st.radio(
                "部署模式",
                ["🔁 顺序部署（一个接一个）", "⚡ 并发部署（同时触发）"],
                help="顺序部署：前一个成功后再触发下一个；并发部署：所有服务同时触发"
            )

            submitted = st.form_submit_button(
                "🚀 开始部署",
                type="primary",
                use_container_width=True,
                disabled=st.session_state.jenkins_deploying
            )

    with col_right:
        st.markdown("**服务说明**")
        st.info(
            "🔹 **pp-public-api**\n"
            "Public API 服务，即将迁移至 EKS\n\n"
            "🔹 **pp-psi-service**\n"
            "PSI 服务，即将迁移至 EKS"
        )
        with st.expander("部署模式说明", expanded=True):
            st.markdown(
                "**🔁 顺序部署**\n"
                "- 按顺序逐一部署，前一个完成才触发下一个\n"
                "- 适合有依赖关系的服务\n\n"
                "**⚡ 并发部署**\n"
                "- 所有服务同时触发，互不等待\n"
                "- 适合相互独立的服务，速度更快"
            )

    # 处理 PP 表单提交
    if submitted:
        if not jenkins_user_val or not jenkins_token_val:
            st.error("❌ 请在侧边栏填写 Jenkins 用户名和 API Token")
        else:
            services_to_deploy = {
                svc: st.session_state.get(f"branch_{svc}", "").strip()
                for svc in FIXED_SERVICES
                if st.session_state.get(f"branch_{svc}", "").strip()
            }

            if not services_to_deploy:
                st.warning("⚠️ 请至少为一个服务填写分支号")
            else:
                while not deploy_q.empty():
                    try:
                        deploy_q.get_nowait()
                    except Exception:
                        break
                st.session_state.jenkins_logs = []
                st.session_state.jenkins_results = {}
                st.session_state.jenkins_done = False
                st.session_state.jenkins_deploying = True
                st.session_state.jenkins_deploy_mode = (
                    "concurrent" if "并发" in deploy_mode else "sequential"
                )
                st.session_state.jenkins_services_branches = services_to_deploy

                auth = build_jenkins_auth(jenkins_user_val, jenkins_token_val)
                threading.Thread(
                    target=runDeployThread,
                    args=(services_to_deploy, auth, jenkins_url_val,
                          "并发" in deploy_mode, deploy_q, "PP"),
                    daemon=True
                ).start()
                st.rerun()

    # PP 部署日志区域
    if st.session_state.jenkins_deploying or st.session_state.jenkins_logs:
        st.markdown("---")

        mode_label = (
            "⚡ 并发" if st.session_state.jenkins_deploy_mode == "concurrent"
            else "🔁 顺序"
        )
        svcs = list(st.session_state.jenkins_services_branches.keys())

        while not deploy_q.empty():
            try:
                item = deploy_q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__DONE__":
                    st.session_state.jenkins_results = item[1]
                    st.session_state.jenkins_deploying = False
                    st.session_state.jenkins_done = True
                else:
                    st.session_state.jenkins_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {item}")
            except Exception:
                break

        if st.session_state.jenkins_deploying:
            st.info(f"⏳ {mode_label} 部署进行中 — {', '.join(svcs)}")
            log_summary = [
                l for l in st.session_state.jenkins_logs
                if any(k in l for k in ("✅", "❌", "🚀", "🔗", "📋", "⏳", "⚠️", "═══", "▶"))
            ]
            if log_summary:
                with st.expander("📋 部署摘要（展开查看详情）", expanded=True):
                    st.code("\n".join(log_summary[-30:]), language=None)
            with st.expander("📜 完整日志", expanded=False):
                st.code("\n".join(st.session_state.jenkins_logs[-200:]), language=None)
            time.sleep(1)
            st.rerun()
        else:
            results = st.session_state.jenkins_results
            ok_count = sum(1 for v in results.values() if v)
            total_count = len(results)

            if ok_count == total_count:
                st.success(f"🎉 全部完成！{ok_count}/{total_count} 个服务部署成功")
            elif ok_count > 0:
                st.warning(f"⚠️ 部分完成：{ok_count}/{total_count} 个服务成功")
            else:
                st.error(f"❌ 全部失败：0/{total_count} 个服务成功")

            c1, c2 = st.columns(2)
            for i, (svc, ok) in enumerate(results.items()):
                col = c1 if i % 2 == 0 else c2
                with col:
                    if ok:
                        st.success(f"✅ **{svc}** 部署成功")
                    else:
                        st.error(f"❌ **{svc}** 部署失败")

            with st.expander("📜 完整部署日志", expanded=False):
                st.code("\n".join(st.session_state.jenkins_logs), language=None)


# ════════════════════════════════════════════════════════════════
# Tab 2：生产环境（调试专用，部署功能锁定）
# ════════════════════════════════════════════════════════════════
elif active_tab == prod_tab_label:
    # 顶部醒目警告
    st.error(
        "🔒 **生产环境 — 部署功能当前已锁定**\n\n"
        "此 Tab 仅供调试：查看服务状态、验证连接权限。\n"
        "**任何部署操作均不可用，防止误操作生产环境。**"
    )

    st.markdown("---")

    # ── 服务列表展示 ──────────────────────────────────────────
    col_info1, col_info2 = st.columns([1, 1])

    with col_info1:
        st.subheader("📋 目标服务")
        for svc in PROD_SERVICES:
            st.markdown(f"🔹 `{svc}`  —  分支: `{PROD_BRANCH}`")

    with col_info2:
        st.subheader("📌 部署规划说明")
        st.info(
            "**部署模式**：并发（4 个服务同时触发）\n\n"
            "**目标分支**：`master`\n\n"
            "**Jenkins 文件夹**：`/job/Prod/`\n\n"
            "**状态**：⏳ 等待迁移完成后开放"
        )

    st.markdown("---")

    # ── 只读巡检区 ────────────────────────────────────────────
    st.subheader("🔍 服务巡检（只读）")
    st.caption("查询 Jenkins 中生产服务的可访问性和最近构建状态，不触发任何构建。")

    inspect_btn = st.button(
        "🔍 开始巡检生产服务",
        use_container_width=False,
        disabled=st.session_state.prod_inspect_running,
        type="secondary",
        key="prod_inspect_btn"
    )

    if inspect_btn:
        if not jenkins_user_val or not jenkins_token_val:
            st.error("❌ 请先在侧边栏填写认证信息")
        else:
            st.session_state.prod_inspect_logs = []
            while not inspect_q.empty():
                try:
                    inspect_q.get_nowait()
                except Exception:
                    break
            st.session_state.prod_inspect_running = True
            threading.Thread(
                target=runProdInspect,
                args=(jenkins_user_val, jenkins_token_val, jenkins_url_val, inspect_q, PROD_SERVICES),
                daemon=True
            ).start()
            st.rerun()

    # 消费巡检队列
    if st.session_state.prod_inspect_running or st.session_state.prod_inspect_logs:
        while not inspect_q.empty():
            try:
                item = inspect_q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__INSPECT_DONE__":
                    st.session_state.prod_inspect_running = False
                else:
                    st.session_state.prod_inspect_logs.append(str(item))
            except Exception:
                break

        if st.session_state.prod_inspect_running:
            st.info("⏳ 巡检中，请稍候…")
            time.sleep(0.8)
            st.rerun()

        if st.session_state.prod_inspect_logs:
            st.code(
                "\n".join(st.session_state.prod_inspect_logs),
                language=None
            )

    st.markdown("---")

    # ── 部署区域 ──────────────────────────────────────────────
    if not PROD_DEPLOY_ENABLED:
        st.subheader("🚀 一键并发部署（锁定中）")
        st.warning(
            "⚠️ 生产部署功能目前处于**锁定状态**，待生产迁移计划确认后由管理员开放。\n\n"
            "开放后将支持：4 个服务并发触发 `master` 分支，实时日志展示。"
        )
        st.button(
            "🔒 生产部署（当前不可用）",
            disabled=True,
            use_container_width=True,
            type="primary",
            key="prod_deploy_locked_btn"
        )
        st.caption("如需开放生产部署，请联系管理员修改 `PROD_DEPLOY_ENABLED = True`。")

    else:
        st.subheader("🚀 一键并发部署 master")
        st.success("✅ 生产部署已开放，将并发触发以下服务的 `master` 分支：")
        for svc in PROD_SERVICES:
            st.markdown(f"  - `{svc}`")

        prod_deploy_btn = st.button(
            "🚀 开始生产并发部署（master）",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.get("prod_deploying", False),
            key="prod_deploy_btn"
        )

        # 初始化 prod 部署专用 session state
        if "prod_deploying" not in st.session_state:
            st.session_state.prod_deploying = False
        if "prod_deploy_logs" not in st.session_state:
            st.session_state.prod_deploy_logs = []
        if "prod_deploy_results" not in st.session_state:
            st.session_state.prod_deploy_results = {}
        if "prod_deploy_done" not in st.session_state:
            st.session_state.prod_deploy_done = False
        if "prod_deploy_queue" not in st.session_state:
            st.session_state.prod_deploy_queue = queue.Queue()

        prod_deploy_q: queue.Queue = st.session_state.prod_deploy_queue

        if prod_deploy_btn:
            if not jenkins_user_val or not jenkins_token_val:
                st.error("❌ 请在侧边栏填写认证信息")
            else:
                while not prod_deploy_q.empty():
                    try:
                        prod_deploy_q.get_nowait()
                    except Exception:
                        break
                st.session_state.prod_deploy_logs = []
                st.session_state.prod_deploy_results = {}
                st.session_state.prod_deploy_done = False
                st.session_state.prod_deploying = True

                services_branches = {svc: PROD_BRANCH for svc in PROD_SERVICES}
                auth = build_jenkins_auth(jenkins_user_val, jenkins_token_val)
                threading.Thread(
                    target=runDeployThread,
                    args=(services_branches, auth, jenkins_url_val,
                          True, prod_deploy_q, "Prod"),
                    daemon=True
                ).start()
                st.rerun()

        # 生产部署日志区域
        if st.session_state.prod_deploying or st.session_state.prod_deploy_logs:
            st.markdown("---")

            while not prod_deploy_q.empty():
                try:
                    item = prod_deploy_q.get_nowait()
                    if isinstance(item, tuple) and item[0] == "__DONE__":
                        st.session_state.prod_deploy_results = item[1]
                        st.session_state.prod_deploying = False
                        st.session_state.prod_deploy_done = True
                    else:
                        st.session_state.prod_deploy_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {item}")
                except Exception:
                    break

            if st.session_state.prod_deploying:
                st.info(f"⚡ 并发部署进行中 — {', '.join(PROD_SERVICES)}")
                log_summary = [
                    l for l in st.session_state.prod_deploy_logs
                    if any(k in l for k in ("✅", "❌", "🚀", "🔗", "📋", "⏳", "⚠️", "═══", "▶"))
                ]
                if log_summary:
                    with st.expander("📋 部署摘要（展开查看详情）", expanded=True):
                        st.code("\n".join(log_summary[-30:]), language=None)
                with st.expander("📜 完整日志", expanded=False):
                    st.code("\n".join(st.session_state.prod_deploy_logs[-200:]), language=None)
                time.sleep(1)
                st.rerun()
            else:
                results = st.session_state.prod_deploy_results
                ok_count = sum(1 for v in results.values() if v)
                total_count = len(results)

                if ok_count == total_count:
                    st.success(f"🎉 全部完成！{ok_count}/{total_count} 个服务部署成功")
                elif ok_count > 0:
                    st.warning(f"⚠️ 部分完成：{ok_count}/{total_count} 个服务成功")
                else:
                    st.error(f"❌ 全部失败：0/{total_count} 个服务成功")

                c1, c2 = st.columns(2)
                for i, (svc, ok) in enumerate(results.items()):
                    col = c1 if i % 2 == 0 else c2
                    with col:
                        if ok:
                            st.success(f"✅ **{svc}** 部署成功")
                        else:
                            st.error(f"❌ **{svc}** 部署失败")

                with st.expander("📜 完整部署日志", expanded=False):
                    st.code("\n".join(st.session_state.prod_deploy_logs), language=None)
