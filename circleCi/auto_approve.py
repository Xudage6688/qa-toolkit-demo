"""监控 Tab 自动审批 Preprod 纯逻辑

从 monitor_view 中抽出的可测试逻辑：筛选 preprod 待审批 Job、批量审批、
判断 Pipeline 是否仍有活动 Workflow（决定自动轮询是否继续）。
"""
from typing import Callable, Dict, List, Optional, Tuple

from circleCi.pipeline_data import approve_job
from circleCi.project_job_match import (
    PENDING_APPROVAL_STATUSES,
    job_matches_project,
    job_name_matches_target_env,
)

# 处于这些状态的 workflow 视为「未结束」，自动轮询继续
ACTIVE_WORKFLOW_STATUSES = {'running', 'queued', 'on_hold', 'failing'}

# Preprod 部署 Job 名称子串（如 deploy-docker-image-on-preprod-aca-new）
PREPROD_DEPLOY_JOB_SUBSTR = 'deploy-docker-image-on-preprod'

# preprod 自动模式状态（get_preprod_auto_mode_status 返回值）
PREPROD_AUTO_POLLING = 'polling'
PREPROD_AUTO_APPROVAL_SUCCESS = 'approval_success'
PREPROD_AUTO_DEPLOY_SUCCESS = 'deploy_success'
PREPROD_AUTO_DEPLOY_FAILED = 'deploy_failed'
PREPROD_AUTO_IDLE = 'idle'


def find_pending_preprod_approvals(
    workflows: Optional[List[Dict]],
    wf_jobs_map: Dict[str, List[Dict]],
    target_env: str = 'preprod',
    project_name: Optional[str] = None,
) -> List[Dict]:
    """从 workflows + jobs 映射中筛选目标环境的待审批 approval Job

    命中的 job 会被原地附加 `_workflow_id` / `_workflow_name`（与
    monitor_view._refresh_workflows 中 pending 列表的结构一致）。

    Args:
        workflows: workflow 列表（每项含 id/name/status）
        wf_jobs_map: workflow_id -> jobs 列表
        target_env: 目标环境关键字（小写子串匹配 job 名）
        project_name: 可选；带服务名的 Job 须匹配该项目；``*-cloud`` 还支持无服务名的
            按环境审批（如 deploy on Preprod）。多服务管道用服务名区分（如 aca-new / lab-photos）

    Returns:
        待审批 job 列表
    """
    pending = []
    for wf in (workflows or []):
        wf_id = wf.get('id')
        for job in wf_jobs_map.get(wf_id, []):
            if not _is_scoped_preprod_approval_pending(
                job, project_name=project_name, target_env=target_env
            ):
                continue
            job['_workflow_id'] = wf_id
            job['_workflow_name'] = wf.get('name')
            pending.append(job)
    return pending


def _is_scoped_preprod_approval_pending(
    job: Dict,
    project_name: Optional[str] = None,
    target_env: str = 'preprod',
) -> bool:
    """是否为当前项目、目标环境下待审批的 approval Job"""
    if job.get('type') != 'approval':
        return False
    if job.get('status') not in PENDING_APPROVAL_STATUSES:
        return False
    job_name = job.get('name', '')
    if not job_name_matches_target_env(job_name, target_env):
        return False
    return job_matches_project(job_name, project_name)


def auto_approve_jobs(
    pending: List[Dict],
    api_token: str,
    approve_fn: Callable = approve_job,
) -> Tuple[List[Dict], List[Dict]]:
    """逐个审批 pending 列表中的 Job

    Args:
        pending: find_pending_preprod_approvals 返回的 job 列表
            （每项需含 `_workflow_id` 和 `approval_request_id`）
        api_token: CircleCI API Token
        approve_fn: 审批函数，默认 pipeline_data.approve_job；测试时注入 mock

    Returns:
        (approved, failed)；失败的 job 原地附加 `_approve_error`
    """
    approved: List[Dict] = []
    failed: List[Dict] = []
    for job in pending:
        try:
            res = approve_fn(
                job.get('_workflow_id'),
                job.get('approval_request_id'),
                api_token=api_token,
            )
        except Exception as e:
            res = {'success': False, 'error': str(e)}
        if res.get('success'):
            approved.append(job)
        else:
            job['_approve_error'] = res.get('error', '未知错误')
            failed.append(job)
    return approved, failed


def has_active_workflows(workflows: Optional[List[Dict]]) -> bool:
    """是否仍有未结束的 Workflow（用于决定是否继续自动轮询）"""
    return any(
        w.get('status') in ACTIVE_WORKFLOW_STATUSES for w in (workflows or [])
    )


def _is_preprod_approval_job(job: Dict, project_name: Optional[str] = None) -> bool:
    """是否为 preprod 环境的 approval Job"""
    job_name = job.get('name', '')
    if job.get('type') != 'approval':
        return False
    if not job_name_matches_target_env(job_name, 'preprod'):
        return False
    return job_matches_project(job_name, project_name)


def _iter_scoped_preprod_approval_jobs(
    workflows: Optional[List[Dict]],
    wf_jobs_map: Dict[str, List[Dict]],
    project_name: Optional[str] = None,
) -> List[Dict]:
    """收集与 project 筛选条件匹配的 preprod approval Job"""
    jobs: List[Dict] = []
    for wf in (workflows or []):
        wf_id = wf.get('id')
        for job in wf_jobs_map.get(wf_id, []):
            if _is_preprod_approval_job(job, project_name):
                jobs.append(job)
    return jobs


def get_preprod_auto_mode_status(
    workflows: Optional[List[Dict]],
    wf_jobs_map: Dict[str, List[Dict]],
    project_name: Optional[str] = None,
) -> str:
    """preprod 自动模式应处的状态

    返回:
        polling — 继续 10 秒轮询（等待 preprod 审批出现或待审批）
        approval_success — 当前范围内 preprod 审批已通过，停止轮询
        idle — Pipeline 已结束且未出现相关 preprod 审批

    停止策略:
        - 匹配的 preprod approval Job 为 success 后即停止，不等待部署 Job
        - 限定项目名时仅看该项目的 preprod 审批（如 aca-new 不受 lab-photos 影响）
    """
    approvals = _iter_scoped_preprod_approval_jobs(
        workflows, wf_jobs_map, project_name
    )

    if any(job.get('status') in PENDING_APPROVAL_STATUSES for job in approvals):
        return PREPROD_AUTO_POLLING

    if any(job.get('status') == 'success' for job in approvals):
        return PREPROD_AUTO_APPROVAL_SUCCESS

    if has_active_workflows(workflows):
        return PREPROD_AUTO_POLLING

    return PREPROD_AUTO_IDLE


def has_pending_preprod_work(
    workflows: Optional[List[Dict]],
    wf_jobs_map: Dict[str, List[Dict]],
    project_name: Optional[str] = None,
) -> bool:
    """是否仍有 preprod 审批/部署相关的未完成工作（需继续自动轮询）"""
    return (
        get_preprod_auto_mode_status(workflows, wf_jobs_map, project_name)
        == PREPROD_AUTO_POLLING
    )
