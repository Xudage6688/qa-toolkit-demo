"""页面公共守卫：统一「当前用户检查 + 用户配置加载」样板。

各页面在 st.set_page_config 之后调用：
    current_user = require_current_user()
    cfg = require_user_config(current_user, "jira")

配置缺失时内部完成报错与 st.stop()，调用方拿到的必为有效值。
"""
import streamlit as st

# 配置类型 → (users_config 中的键名, 页面展示名)
_CONFIG_KINDS = {
    "jira": "JIRA",
    "circleci": "CircleCI",
    "jenkins": "Jenkins",
}


def require_current_user() -> str:
    """返回当前使用者；未选择时报错并终止页面。"""
    if 'current_user' not in st.session_state or not st.session_state.current_user:
        st.error("❌ 未选择使用者，请返回主页选择你的身份")
        st.stop()
    return st.session_state.current_user


def require_user_config(current_user: str, kind: str) -> dict:
    """按类型加载当前用户的配置；缺失时报错并终止页面。

    Args:
        current_user: 当前使用者（require_current_user 的返回值）
        kind: 配置类型，可选 "jira" / "circleci" / "jenkins"

    Returns:
        该用户对应配置的非空 dict
    """
    loader = {
        "jira": _get_jira_config,
        "circleci": _get_circleci_config,
        "jenkins": _get_jenkins_config,
    }[kind]
    label = _CONFIG_KINDS[kind]

    config = loader(current_user)
    if not config:
        st.error(f"❌ 未找到用户 {current_user} 的 {label} 配置")
        st.info("请联系管理员在 config/users_config.json 中配置你的信息")
        st.stop()
    return config


def _get_jira_config(username: str) -> dict:
    from modules.user_config_loader import get_jira_config
    return get_jira_config(username)


def _get_circleci_config(username: str) -> dict:
    from modules.user_config_loader import get_circleci_config
    return get_circleci_config(username)


def _get_jenkins_config(username: str) -> dict:
    from modules.user_config_loader import get_jenkins_config
    return get_jenkins_config(username)
