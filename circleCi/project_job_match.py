"""CircleCI Job 名与仓库项目名匹配

每个 Pipeline、每个环境仅有一个 approval（业务约定），匹配分两类：

1. **带服务名**：如 ``Do you want to deploy aca-new on preprod?`` — Job 名含
   仓库短名或 ``buildProjectCandidates`` 别名（``public-api-cloud`` → ``public-api``）。
2. **仅环境**：如 ``Do you want to deploy on Preprod?`` — 无服务名，对 ``*-cloud``
   单服务 EKS 仓库视为当前 Pipeline 项目的 preprod 审批。

不带 ``-cloud`` 的同名服务为旧 EC2/Jenkins 链路，不在 CircleCI 自动审批范围内。
"""
import re
from typing import List, Optional

from modules._services_approver_logic import buildProjectCandidates, matchesEnvironment

# CircleCI approval 待人工点击时的状态
PENDING_APPROVAL_STATUSES = frozenset({'on_hold', 'blocked'})

# 部分 pipeline 用 "on PP" 表示 preprod（避免裸匹配 "pp" 误伤 application 等）
_PREPROD_PP_PATTERN = re.compile(r'\bon\s+pp\b', re.IGNORECASE)
# ``deploy aca-new on preprod`` 含服务名；``deploy on Preprod`` 为 EKS 单服务 pipeline 常用文案
_DEPLOY_NAMED_SERVICE_ON_ENV = re.compile(r'deploy\s+\S+\s+on\s+', re.IGNORECASE)
_DEPLOY_ON_ENV_GENERIC = re.compile(r'deploy\s+on\s+', re.IGNORECASE)


def normalize_project_name(project_name: Optional[str]) -> Optional[str]:
    """从 project_slug 或项目名提取用于匹配 Job 名称的短名"""
    if not project_name:
        return None
    name = project_name.strip()
    if '/' in name:
        name = name.split('/')[-1]
    return name.lower() or None


def project_name_match_aliases(project_name: Optional[str]) -> List[str]:
    """生成用于匹配 CircleCI Job 名的项目别名（含 EKS *-cloud / *-service-cloud 短名）"""
    normalized = normalize_project_name(project_name)
    if not normalized:
        return []
    return buildProjectCandidates(normalized)


def job_name_matches_target_env(job_name: str, target_env: str = 'preprod') -> bool:
    """审批 Job 名称是否属于目标环境（与审批面板展开逻辑一致，支持 Preprod / on PP 等）"""
    if not job_name:
        return False
    env = (target_env or 'preprod').lower()
    if matchesEnvironment(job_name, env):
        return True
    if env == 'preprod' and _PREPROD_PP_PATTERN.search(job_name):
        return True
    return False


def is_generic_deploy_on_env_approval(
    job_name: str,
    target_env: str = 'preprod',
) -> bool:
    """是否为「仅按环境」审批（无服务名，如 deploy on Preprod）"""
    if not job_name:
        return False
    if not job_name_matches_target_env(job_name, target_env):
        return False
    if _DEPLOY_NAMED_SERVICE_ON_ENV.search(job_name):
        return False
    return bool(_DEPLOY_ON_ENV_GENERIC.search(job_name))


def job_matches_project(job_name: str, project_name: Optional[str]) -> bool:
    """Job 名称是否属于指定 CircleCI 仓库项目"""
    aliases = project_name_match_aliases(project_name)
    if not aliases:
        return True
    lower = (job_name or '').lower()
    if any(alias.lower() in lower for alias in aliases):
        return True
    normalized = normalize_project_name(project_name)
    if (
        normalized
        and normalized.endswith('-cloud')
        and is_generic_deploy_on_env_approval(job_name, 'preprod')
    ):
        return True
    return False
