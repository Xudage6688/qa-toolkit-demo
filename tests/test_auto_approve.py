"""监控 Tab 自动审批 Preprod 逻辑单元测试"""
from circleCi.auto_approve import (
    ACTIVE_WORKFLOW_STATUSES,
    PREPROD_DEPLOY_JOB_SUBSTR,
    PREPROD_AUTO_POLLING,
    PREPROD_AUTO_APPROVAL_SUCCESS,
    PREPROD_AUTO_IDLE,
    find_pending_preprod_approvals,
    auto_approve_jobs,
    has_active_workflows,
    has_pending_preprod_work,
    get_preprod_auto_mode_status,
    _is_scoped_preprod_approval_pending,
)
from circleCi.project_job_match import job_matches_project


def _wf(wf_id, name='build-and-deploy', status='on_hold'):
    return {'id': wf_id, 'name': name, 'status': status}


def _job(job_id, name, job_type='approval', status='on_hold', req_id=None):
    return {
        'id': job_id,
        'name': name,
        'type': job_type,
        'status': status,
        'approval_request_id': req_id or f'req-{job_id}',
    }


class TestFindPendingPreprodApprovals:
    """测试 find_pending_preprod_approvals"""

    def test_matches_preprod_on_hold_approval(self):
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', 'approve-deploy-preprod')]}
        result = find_pending_preprod_approvals(workflows, jobs_map)
        assert len(result) == 1
        assert result[0]['id'] == 'j1'

    def test_attaches_workflow_info(self):
        workflows = [_wf('wf1', name='deploy-workflow')]
        jobs_map = {'wf1': [_job('j1', 'approve-preprod')]}
        result = find_pending_preprod_approvals(workflows, jobs_map)
        assert result[0]['_workflow_id'] == 'wf1'
        assert result[0]['_workflow_name'] == 'deploy-workflow'

    def test_excludes_non_preprod_jobs(self):
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', 'approve-deploy-prod')]}
        assert find_pending_preprod_approvals(workflows, jobs_map) == []

    def test_excludes_approved_jobs(self):
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', 'approve-preprod', status='success')]}
        assert find_pending_preprod_approvals(workflows, jobs_map) == []

    def test_excludes_build_type_jobs(self):
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', 'deploy-preprod', job_type='build', status='on_hold')]}
        assert find_pending_preprod_approvals(workflows, jobs_map) == []

    def test_matches_case_insensitive(self):
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', 'Approve-PreProd-CN')]}
        assert len(find_pending_preprod_approvals(workflows, jobs_map)) == 1

    def test_multiple_workflows(self):
        workflows = [_wf('wf1'), _wf('wf2')]
        jobs_map = {
            'wf1': [_job('j1', 'approve-preprod')],
            'wf2': [_job('j2', 'approve-preprod-2'), _job('j3', 'approve-prod')],
        }
        result = find_pending_preprod_approvals(workflows, jobs_map)
        assert [j['id'] for j in result] == ['j1', 'j2']

    def test_empty_inputs(self):
        assert find_pending_preprod_approvals([], {}) == []
        assert find_pending_preprod_approvals(None, {}) == []

    def test_project_name_excludes_other_services_in_monorepo(self):
        """aca-new 管道中 lab-photos 的 preprod 审批不应被自动选中"""
        aca_approval = (
            'Do you want to deploy aca-new on preprod? — new-commit-build-test-and-maybe-deploy'
        )
        lab_photos_approval = (
            'Do you want to deploy lab-photos on preprod? — new-commit-build-test-and-maybe-deploy'
        )
        workflows = [_wf('wf1')]
        jobs_map = {
            'wf1': [
                _job('j1', aca_approval),
                _job('j2', lab_photos_approval),
            ],
        }
        result = find_pending_preprod_approvals(
            workflows, jobs_map, project_name='aca-new'
        )
        assert [j['id'] for j in result] == ['j1']

    def test_project_name_from_slug(self):
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', 'Do you want to deploy aca-new on preprod?')]}
        result = find_pending_preprod_approvals(
            workflows,
            jobs_map,
            project_name='github/your-org/aca-new',
        )
        assert len(result) == 1

    def test_public_api_cloud_matches_short_service_name_in_job(self):
        job_name = (
            'Do you want to deploy public-api on preprod? — new-commit-build-test-and-maybe-deploy'
        )
        assert job_matches_project(job_name, 'public-api-cloud') is True
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [_job('j1', job_name)]}
        result = find_pending_preprod_approvals(
            workflows, jobs_map, project_name='public-api-cloud'
        )
        assert len(result) == 1

    def test_public_api_cloud_does_not_match_unrelated_service(self):
        job_name = 'Do you want to deploy lab-photos on preprod? — wf'
        assert job_matches_project(job_name, 'public-api-cloud') is False

    def test_psi_service_cloud_matches_short_name_in_job(self):
        job_name = 'Do you want to deploy psi-service on preprod? — wf'
        assert job_matches_project(job_name, 'psi-service-cloud') is True

    def test_blocked_approval_status_counts_as_pending(self):
        job = _job('j1', 'Do you want to deploy public-api on preprod?', status='blocked')
        assert _is_scoped_preprod_approval_pending(
            job, project_name='public-api-cloud'
        )

    def test_pp_wording_matches_preprod(self):
        job = _job('j1', 'Do you want to deploy public-api on PP?', status='on_hold')
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [job]}
        result = find_pending_preprod_approvals(
            workflows, jobs_map, project_name='public-api-cloud'
        )
        assert len(result) == 1

    def test_generic_deploy_on_preprod_for_cloud_repo(self):
        job = _job('j1', 'Do you want to deploy on Preprod?', status='on_hold')
        workflows = [_wf('wf1')]
        jobs_map = {'wf1': [job]}
        result = find_pending_preprod_approvals(
            workflows, jobs_map, project_name='public-api-cloud'
        )
        assert len(result) == 1


class TestAutoApproveJobs:
    """测试 auto_approve_jobs"""

    def test_approves_each_pending_job(self):
        calls = []

        def fake_approve(wf_id, req_id, api_token=None):
            calls.append((wf_id, req_id, api_token))
            return {'success': True}

        pending = [
            _job('j1', 'approve-preprod', req_id='r1'),
            _job('j2', 'approve-preprod-2', req_id='r2'),
        ]
        pending[0]['_workflow_id'] = 'wf1'
        pending[1]['_workflow_id'] = 'wf1'

        approved, failed = auto_approve_jobs(pending, api_token='tok', approve_fn=fake_approve)

        assert [j['id'] for j in approved] == ['j1', 'j2']
        assert failed == []
        assert calls == [('wf1', 'r1', 'tok'), ('wf1', 'r2', 'tok')]

    def test_collects_failures_with_error(self):
        def fake_approve(wf_id, req_id, api_token=None):
            if req_id == 'r2':
                return {'success': False, 'error': 'permission denied'}
            return {'success': True}

        pending = [
            _job('j1', 'approve-preprod', req_id='r1'),
            _job('j2', 'approve-preprod-2', req_id='r2'),
        ]
        for j in pending:
            j['_workflow_id'] = 'wf1'

        approved, failed = auto_approve_jobs(pending, api_token='tok', approve_fn=fake_approve)

        assert [j['id'] for j in approved] == ['j1']
        assert [j['id'] for j in failed] == ['j2']
        assert failed[0]['_approve_error'] == 'permission denied'

    def test_approve_fn_exception_becomes_failure(self):
        def exploding(wf_id, req_id, api_token=None):
            raise RuntimeError('network down')

        pending = [_job('j1', 'approve-preprod', req_id='r1')]
        pending[0]['_workflow_id'] = 'wf1'

        approved, failed = auto_approve_jobs(pending, api_token='tok', approve_fn=exploding)

        assert approved == []
        assert len(failed) == 1
        assert 'network down' in failed[0]['_approve_error']


class TestHasActiveWorkflows:
    """测试 has_active_workflows"""

    def test_running_is_active(self):
        assert has_active_workflows([_wf('wf1', status='running')]) is True

    def test_on_hold_is_active(self):
        assert has_active_workflows([_wf('wf1', status='on_hold')]) is True

    def test_queued_and_failing_are_active(self):
        assert has_active_workflows([_wf('wf1', status='queued')]) is True
        assert has_active_workflows([_wf('wf1', status='failing')]) is True

    def test_all_terminal_is_inactive(self):
        workflows = [
            _wf('wf1', status='success'),
            _wf('wf2', status='failed'),
            _wf('wf3', status='canceled'),
        ]
        assert has_active_workflows(workflows) is False

    def test_mixed_active_and_terminal(self):
        workflows = [_wf('wf1', status='success'), _wf('wf2', status='running')]
        assert has_active_workflows(workflows) is True

    def test_empty_or_none(self):
        assert has_active_workflows([]) is False
        assert has_active_workflows(None) is False

    def test_active_statuses_constant(self):
        assert ACTIVE_WORKFLOW_STATUSES == {'running', 'queued', 'on_hold', 'failing'}


class TestHasPendingPreprodWork:
    """测试 has_pending_preprod_work（自动轮询停止条件）"""

    def test_pending_preprod_approval(self):
        workflows = [_wf('wf1', status='on_hold')]
        jobs_map = {'wf1': [_job('j1', 'approve-preprod')]}
        assert has_pending_preprod_work(workflows, jobs_map) is True

    def test_deploy_running_stops_after_approval_success(self):
        workflows = [_wf('wf1', status='running')]
        jobs_map = {
            'wf1': [
                _job('j1', 'approve-preprod', status='success'),
                _job('j2', 'deploy-docker-image-on-preprod-aca-new', job_type='build', status='running'),
            ],
        }
        assert has_pending_preprod_work(workflows, jobs_map) is False

    def test_approval_success_stops_even_if_workflow_active(self):
        workflows = [_wf('wf1', status='on_hold')]
        jobs_map = {
            'wf1': [
                _job('j1', 'approve-preprod', status='success'),
                _job('j2', 'deploy-docker-image-on-preprod-aca-new', job_type='build', status='success'),
                _job('j3', 'approve-staging', status='on_hold'),
            ],
        }
        assert has_pending_preprod_work(workflows, jobs_map) is False

    def test_approval_done_does_not_wait_for_deploy(self):
        workflows = [_wf('wf1', status='running')]
        jobs_map = {'wf1': [_job('j1', 'approve-preprod', status='success')]}
        assert has_pending_preprod_work(workflows, jobs_map) is False

    def test_wait_for_preprod_jobs_while_pipeline_active(self):
        workflows = [_wf('wf1', status='running')]
        jobs_map = {'wf1': [_job('j1', 'build', job_type='build', status='running')]}
        assert has_pending_preprod_work(workflows, jobs_map) is True

    def test_pipeline_done_no_preprod(self):
        workflows = [_wf('wf1', status='success')]
        jobs_map = {'wf1': [_job('j1', 'build', job_type='build', status='success')]}
        assert has_pending_preprod_work(workflows, jobs_map) is False

    def test_deploy_failed_still_stops_after_approval_success(self):
        workflows = [_wf('wf1', status='failed')]
        jobs_map = {
            'wf1': [
                _job('j1', 'approve-preprod', status='success'),
                _job('j2', 'deploy-docker-image-on-preprod-svc', job_type='build', status='failed'),
            ],
        }
        assert has_pending_preprod_work(workflows, jobs_map) is False
        assert get_preprod_auto_mode_status(workflows, jobs_map) == PREPROD_AUTO_APPROVAL_SUCCESS

    def test_approval_success_status(self):
        workflows = [_wf('wf1', status='on_hold')]
        jobs_map = {
            'wf1': [
                _job('j1', 'approve-preprod', status='success'),
                _job('j2', 'deploy-docker-image-on-preprod-aca-new', job_type='build', status='success'),
            ],
        }
        assert get_preprod_auto_mode_status(workflows, jobs_map) == PREPROD_AUTO_APPROVAL_SUCCESS

    def test_scoped_project_stops_after_approval_while_workflow_running(self):
        workflows = [_wf('wf1', status='running')]
        jobs_map = {
            'wf1': [
                _job('j1', 'Do you want to deploy aca-new on preprod?', status='success'),
                _job(
                    'j2',
                    'deploy-docker-image-on-preprod-aca-new',
                    job_type='build',
                    status='running',
                ),
                _job('j3', 'build-lab-photos', job_type='build', status='running'),
            ],
        }
        assert (
            get_preprod_auto_mode_status(workflows, jobs_map, project_name='aca-new')
            == PREPROD_AUTO_APPROVAL_SUCCESS
        )

    def test_pipeline_done_no_preprod_is_idle(self):
        workflows = [_wf('wf1', status='success')]
        jobs_map = {'wf1': [_job('j1', 'build', job_type='build', status='success')]}
        assert get_preprod_auto_mode_status(workflows, jobs_map) == PREPROD_AUTO_IDLE

    def test_pending_approval_keeps_polling_with_blocked_deploy(self):
        workflows = [_wf('wf1', status='on_hold')]
        jobs_map = {
            'wf1': [
                _job('j1', 'approve-preprod'),
                _job(
                    'j2',
                    'deploy-docker-image-on-preprod-aca-new',
                    job_type='build',
                    status='blocked',
                ),
            ],
        }
        assert get_preprod_auto_mode_status(workflows, jobs_map) == PREPROD_AUTO_POLLING

    def test_no_approval_yet_keeps_polling_while_workflow_active(self):
        workflows = [_wf('wf1', status='running')]
        jobs_map = {
            'wf1': [
                _job(
                    'j2',
                    'deploy-docker-image-on-preprod-svc',
                    job_type='build',
                    status='not_running',
                ),
            ],
        }
        assert get_preprod_auto_mode_status(workflows, jobs_map) == PREPROD_AUTO_POLLING

    def test_preprod_deploy_substr_constant(self):
        assert PREPROD_DEPLOY_JOB_SUBSTR == 'deploy-docker-image-on-preprod'

    def test_lab_photos_pending_does_not_block_auto_stop_for_aca_new(self):
        """aca-new 审批已过后待机，不因 lab-photos 待审批继续轮询"""
        workflows = [_wf('wf1', status='on_hold')]
        jobs_map = {
            'wf1': [
                _job('j1', 'Do you want to deploy aca-new on preprod?', status='success'),
                _job(
                    'j2',
                    'deploy-docker-image-on-preprod-aca-new',
                    job_type='build',
                    status='running',
                ),
                _job(
                    'j3',
                    'Do you want to deploy lab-photos on preprod? — wf',
                    status='on_hold',
                ),
            ],
        }
        assert (
            get_preprod_auto_mode_status(workflows, jobs_map, project_name='aca-new')
            == PREPROD_AUTO_APPROVAL_SUCCESS
        )
