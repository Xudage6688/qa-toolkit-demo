import streamlit as st
from pathlib import Path

# 导入配置和状态管理
from circleCi.pipeline_config import init_session_state, get_services_list

# 导入视图模块
from circleCi.trigger_view import render_trigger_tab
from circleCi.pipeline_list_view import render_pipeline_list_tab
from circleCi.monitor_view import render_monitor_tab
from circleCi.commit_search_view import render_commit_search_tab
from circleCi.batch_ops_view import render_batch_ops_tab
from circleCi.branch_merge_view import render_branch_merge_tab

# 导入用户配置
from modules.user_config_loader import get_user_config_loader

# 页面配置
st.set_page_config(
    page_title="CircleCI Pipeline管理",
    page_icon="🚀",
    layout="wide"
)

# 检查当前用户并加载 CircleCI 配置
from modules.page_common import require_current_user, require_user_config

current_user = require_current_user()
user_circleci_config = require_user_config(current_user, "circleci")

# 使用用户配置
CIRCLECI_API_TOKEN = user_circleci_config.get('api_token', '')
VCS_TYPE = user_circleci_config.get('vcs_type', 'github')
ORGANIZATION = user_circleci_config.get('organization', 'your-org')
DEFAULT_PROJECT = user_circleci_config.get('default_project', 'your-project')
DEFAULT_BRANCH = user_circleci_config.get('default_branch', 'master')

# 项目根目录
project_root = Path(__file__).parent.parent

# 初始化 session state
init_session_state(DEFAULT_PROJECT, DEFAULT_BRANCH)

# 标题
st.title("🚀 CircleCI Pipeline 管理工具")

# 显示当前用户
user_display_name = get_user_config_loader().get_user_display_name(current_user)
st.info(f"👤 当前使用者: **{user_display_name}** ({current_user})")

st.markdown("---")

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 配置")

    # API Token状态
    if CIRCLECI_API_TOKEN and CIRCLECI_API_TOKEN != 'YOUR_CIRCLECI_TOKEN_HERE':
        st.success("✅ API Token: 已配置")
    else:
        st.error("❌ 未配置API Token")

    st.markdown("---")

    # 默认配置显示
    st.subheader("📋 默认配置")
    st.info(f"**VCS**: {VCS_TYPE}")
    st.info(f"**组织**: {ORGANIZATION}")
    st.info(f"**项目**: {DEFAULT_PROJECT}")
    st.info(f"**分支**: {DEFAULT_BRANCH}")

    st.markdown("---")

    # 历史记录
    st.subheader("📜 触发历史")
    if st.session_state.pipeline_history:
        for i, history in enumerate(reversed(st.session_state.pipeline_history[-5:])):
            with st.expander(f"Pipeline #{history['number']}"):
                st.write(f"**ID:** {history['id'][:16]}...")
                st.write(f"**分支:** {history['branch']}")
                st.write(f"**时间:** {history['time']}")
    else:
        st.write("暂无历史记录")

# 侧边栏设置（Tab 外）
with st.sidebar:
    st.subheader("⚙️ 设置")

    cached_users = len(st.session_state.get('user_cache', {}))
    if cached_users > 0:
        st.info(f"👤 已缓存 {cached_users} 个用户信息")
        if st.button("🗑️ 清空用户缓存", use_container_width=True):
            st.session_state.user_cache = {}
            st.success("✅ 缓存已清空")
            st.rerun()
    else:
        st.caption("暂无用户缓存")

    st.markdown("---")

    st.caption(f"🔑 Token: {CIRCLECI_API_TOKEN[:15]}...")
    st.caption(f"🏢 Organization: {ORGANIZATION}")
    st.caption(f"📦 VCS: {VCS_TYPE}")

# 单选导航：只渲染当前 Tab，避免 st.tabs 多面板叠显
TAB_TRIGGER = "🎯 触发Pipeline"
TAB_LIST = "📋 Pipeline列表"
TAB_MONITOR = "📊 监控Pipeline"
TAB_COMMIT = "🔍 Commit ID 搜索"
TAB_BATCH = "📦 批量操作"
TAB_MERGE = "🔀 合分支"
TAB_OPTIONS = [TAB_TRIGGER, TAB_LIST, TAB_MONITOR, TAB_COMMIT, TAB_BATCH, TAB_MERGE]

# GitHub Token（合分支 Tab 使用）
_user_full_config = get_user_config_loader().get_user_config(current_user) or {}
GITHUB_TOKEN = (_user_full_config.get("github") or {}).get("token", "")

# 从列表/搜索跳转监控时，自动切到监控 Tab
if st.session_state.get('pending_tab3_monitor'):
    st.session_state.circleci_active_tab = TAB_MONITOR

if st.session_state.circleci_active_tab not in TAB_OPTIONS:
    st.session_state.circleci_active_tab = TAB_TRIGGER

active_tab = st.segmented_control(
    "功能导航",
    options=TAB_OPTIONS,
    key="circleci_active_tab",
    label_visibility="collapsed",
    required=True,
    width="stretch"
)

st.markdown("---")

if active_tab == TAB_TRIGGER:
    render_trigger_tab(
        project_root=project_root,
        vcs_type=VCS_TYPE,
        organization=ORGANIZATION,
        default_project=DEFAULT_PROJECT,
        default_branch=DEFAULT_BRANCH,
        api_token=CIRCLECI_API_TOKEN
    )
elif active_tab == TAB_LIST:
    render_pipeline_list_tab(
        project_root=project_root,
        vcs_type=VCS_TYPE,
        organization=ORGANIZATION,
        default_project=DEFAULT_PROJECT,
        api_token=CIRCLECI_API_TOKEN
    )
elif active_tab == TAB_MONITOR:
    render_monitor_tab(api_token=CIRCLECI_API_TOKEN)
elif active_tab == TAB_COMMIT:
    render_commit_search_tab(
        project_root=project_root,
        default_project=DEFAULT_PROJECT,
        vcs_type=VCS_TYPE,
        organization=ORGANIZATION,
        api_token=CIRCLECI_API_TOKEN
    )
elif active_tab == TAB_BATCH:
    render_batch_ops_tab(
        project_root=project_root,
        default_project=DEFAULT_PROJECT,
        vcs_type=VCS_TYPE,
        organization=ORGANIZATION,
        api_token=CIRCLECI_API_TOKEN
    )
elif active_tab == TAB_MERGE:
    render_branch_merge_tab(
        project_root=project_root,
        organization=ORGANIZATION,
        default_project=DEFAULT_PROJECT,
        github_token=GITHUB_TOKEN,
    )

# 底部功能说明
st.markdown("---")
st.markdown("""
### 💡 功能说明

#### 🎯 触发 Pipeline（Tab1）
1. 选择项目名称
2. 输入分支名称，或点击 **"🔍 查最新"** 查询该项目最近构建的分支
3. 从下拉列表选择分支，自动填入输入框
4. 点击 **"🚀 触发 Pipeline"** 按钮
5. 系统自动拼接完整路径：`github/your-org/项目名`
6. 触发成功后可一键跳转 Tab3 监控

#### 📋 Pipeline 列表（Tab2）
1. 选择项目名称，可选填写分支名称（留空查所有分支）
2. 选择显示条数（默认 10，可选 20 / 40 / 100），点击 **"🔍 查询 Pipelines"** 查看记录
3. 查看每个 Pipeline 的分支、触发者、提交信息
4. **分支** 可点击文本框选中后 Ctrl+C 复制
5. 点击 **"📊 监控"** 按钮，自动跳转 Tab3 并填入 Pipeline ID

#### 📊 监控 Pipeline（Tab3）
1. 输入 Pipeline ID（或从 Tab1/Tab2 自动带入）
2. 点击 **"🔍 查看状态"** 获取当前状态
3. 查看 Workflows / Jobs 统计面板（成功/失败/运行中/待审批）
4. **Preprod 审批项自动展开**，可直接在页面内完成审批
5. 无需切换 Tab，审批后自动刷新状态
6. 打开「🔄 刷新」旁的 **"🤖 自动刷新并审批 Preprod"** 开关：每 10 秒自动刷新，仅自动通过**当前 Pipeline 项目名**且名称含 `preprod` 的待审批 Job（如 `aca-new` 不会自动批 `lab-photos`），该项目 preprod **审批通过后**自动待机（不等待部署）

#### ✅ 审批面板（Tab3 内嵌）
- 待审批 Jobs 自动展示，Preprod 环境 Jobs 默认展开
- 填写 Pipeline ID 后自动查找所有 on_hold 状态的 Approval Job
- 点击 **"✅ 审批"** 按钮直接通过，无需跳转 CircleCI 页面

#### 🔍 Commit ID 搜索（Tab4）
1. 输入 Commit ID 前缀（至少4位，如 `8a688704`）
2. 默认搜索所有服务，也可取消勾选后手动选择特定服务
3. 点击 **"🔍 开始搜索"** 跨服务并发查询
4. 查看匹配的 Pipeline：服务名、分支、触发者、状态等
5. **Revision** 可点击复制完整 commit hash
6. 点击 **"📊 监控"** 按钮，自动跳转 Tab3 查看详情

#### 📦 批量操作（Tab5）
1. **快捷选择**: 点击「选择 ACA 服务组」一键选择20个服务
2. **同分支批量**: 在「🚀 同分支批量触发」子 Tab 选择多个服务，输入统一目标分支
2.5. **多分支批量**: 切换到「🔀 多分支批量触发」子 Tab，粘贴 `服务:分支` 键值对或使用表格逐行配置
3. 点击 **"🚀 开始批量触发"** 并发触发所有服务
4. 查看触发结果统计（成功/失败列表）
5. 点击 **"🔍 扫描待审批 Jobs"** 查找所有待审批的 Preprod Jobs
6. 点击 **"✅ 执行批量审批"** 一键审批所有待审批 Jobs
7. 支持单独审批每个 Job，或批量审批全部

#### 🔀 合分支（Tab6）
1. 选择服务（如 `aca-new`），确认已配置 GitHub Token（`users_config.json` → `github.token`，需 repo 权限）
2. 输入 2 个及以上分支名（第一个为基分支），支持换行/空格/逗号分隔
3. 预览目标合并分支名（如 `merge/SP-12345/SP-54321`，带 `merge/` 前缀避免与源分支冲突）
4. 默认以 **GitHub PR** 形式在远端顺序 Merge（不 clone 到本机）
5. 点击 **"🚀 开始远程合并"**；冲突时会自动创建冲突 PR，可在 GitHub 网页解决
6. 成功后可打开合并分支链接，或切到「触发 Pipeline」继续构建

#### 💡 简化输入说明
- ✅ **只需输入项目名**: `your-project`（不是完整路径）
- ✅ **自动拼接**: 系统自动组合为 `github/your-org/your-project`
- ✅ **配置预设**: VCS 类型和组织名已在配置中预设
- ✅ **分支查最新**: 无需记忆分支名，一键查询最近使用过的分支

#### ⚙️ 注意事项
- 确保在 `config/users_config.json` 中配置了正确的 API Token
- Tab2 默认显示 10 条 Pipeline，可选 20 / 40 / 100，按最新时间排序；条数越大越慢（含审批详情查询）
- Tab3 审批面板仅展示当前 Pipeline 的待审批 Jobs
- Tab4 搜索所有服务约需 10-15 秒，最多返回 100 条结果
- Tab5 批量触发使用5并发，约需 30-60 秒完成
- Tab6 合分支通过 GitHub API/PR 远程完成，不占用本机磁盘克隆；Token 需 repo 权限
- 可以在侧边栏查看最近 5 次触发的历史记录
""")