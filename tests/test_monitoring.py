"""CircleCI monitoring 模块单元测试

取数函数已收编到 pipeline_api.call_circleci_api，测试统一 mock 该边界，
并断言实际请求的 endpoint 与 api_token 透传。
"""
import pytest
from unittest.mock import Mock, patch

from circleCi.monitoring import (
    get_pipeline_status,
    get_pipeline_workflows,
    get_workflow_status,
    format_status,
    get_pipeline_id_by_number,
)


class TestFormatStatus:
    """测试 format_status 函数"""

    def test_format_running(self):
        display_text, emoji = format_status('running')
        assert display_text == 'Running'
        assert emoji == '🔄'

    def test_format_success(self):
        display_text, emoji = format_status('success')
        assert display_text == 'Success'
        assert emoji == '✅'

    def test_format_failing(self):
        """failing 在当前配置中代表成功"""
        display_text, emoji = format_status('failing')
        assert display_text == 'Success'
        assert emoji == '✅'

    def test_format_failed(self):
        display_text, emoji = format_status('failed')
        assert display_text == 'Failed'
        assert emoji == '❌'

    def test_format_error(self):
        display_text, emoji = format_status('error')
        assert display_text == 'Error'
        assert emoji == '❌'

    def test_format_canceled(self):
        display_text, emoji = format_status('canceled')
        assert display_text == 'Canceled'
        assert emoji == '⏹️'

    def test_format_on_hold(self):
        display_text, emoji = format_status('on_hold')
        assert display_text == 'On Hold'
        assert emoji == '⏸️'

    def test_format_not_run(self):
        display_text, emoji = format_status('not_run')
        assert display_text == 'Not Run'
        assert emoji == '⚪'

    def test_format_queued(self):
        display_text, emoji = format_status('queued')
        assert display_text == 'Queued'
        assert emoji == '⏳'

    def test_format_created(self):
        display_text, emoji = format_status('created')
        assert display_text == 'Created'
        assert emoji == '📝'

    def test_format_unknown_status(self):
        display_text, emoji = format_status('unknown_status')
        assert display_text == 'unknown_status'
        assert emoji == '❓'

    def test_format_case_insensitive(self):
        display_text, emoji = format_status('SUCCESS')
        assert display_text == 'Success'
        assert emoji == '✅'


def _ok_response(json_data):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = json_data
    return resp


class TestGetPipelineStatus:
    """测试 get_pipeline_status 函数"""

    @patch('circleCi.monitoring.call_circleci_api')
    def test_success_returns_parsed_json_and_forwards_token(self, mock_api):
        mock_api.return_value = (_ok_response({
            'id': 'pipeline-123', 'number': 100, 'state': 'running',
        }), None)

        result = get_pipeline_status('pipeline-123', api_token='test-token')

        assert result['id'] == 'pipeline-123'
        assert result['number'] == 100
        assert result['state'] == 'running'
        mock_api.assert_called_once_with('pipeline/pipeline-123', api_token='test-token')

    @pytest.mark.parametrize("status_code", [404, 401, 403, 500])
    @patch('circleCi.monitoring.call_circleci_api')
    def test_error_status_returns_none(self, mock_api, status_code):
        mock_api.return_value = (None, {'status_code': status_code, 'error': 'x'})

        assert get_pipeline_status('pipeline-123', silent=True) is None

    @patch('circleCi.monitoring.call_circleci_api')
    def test_network_error_returns_none(self, mock_api):
        mock_api.return_value = (None, {'error': 'connection refused'})

        assert get_pipeline_status('pipeline-123', silent=True) is None


class TestGetPipelineWorkflows:
    """测试 get_pipeline_workflows 函数"""

    @patch('circleCi.monitoring.call_circleci_api')
    def test_success_returns_items_and_forwards_token(self, mock_api):
        mock_api.return_value = (_ok_response({
            'items': [
                {'id': 'wf-1', 'name': 'build', 'status': 'success'},
                {'id': 'wf-2', 'name': 'deploy', 'status': 'running'},
            ]
        }), None)

        result = get_pipeline_workflows('pipeline-123', api_token='test-token')

        assert len(result) == 2
        assert result[0]['id'] == 'wf-1'
        assert result[1]['status'] == 'running'
        mock_api.assert_called_once_with(
            'pipeline/pipeline-123/workflow', api_token='test-token'
        )

    @patch('circleCi.monitoring.call_circleci_api')
    def test_empty_items(self, mock_api):
        mock_api.return_value = (_ok_response({'items': []}), None)
        assert get_pipeline_workflows('pipeline-123', api_token='t') == []

    @patch('circleCi.monitoring.call_circleci_api')
    def test_missing_items_key(self, mock_api):
        mock_api.return_value = (_ok_response({}), None)
        assert get_pipeline_workflows('pipeline-123', api_token='t') == []

    @pytest.mark.parametrize("status_code", [404, 401, 403, 500])
    @patch('circleCi.monitoring.call_circleci_api')
    def test_error_status_returns_none(self, mock_api, status_code):
        mock_api.return_value = (None, {'status_code': status_code, 'error': 'x'})

        assert get_pipeline_workflows('pipeline-123', silent=True) is None

    @patch('circleCi.monitoring.call_circleci_api')
    def test_network_error_returns_none(self, mock_api):
        mock_api.return_value = (None, {'error': 'timeout'})

        assert get_pipeline_workflows('pipeline-123', silent=True) is None


class TestGetWorkflowStatus:
    """测试 get_workflow_status 函数"""

    @patch('circleCi.monitoring.get_pipeline_workflows')
    def test_running_wins(self, mock_get_workflows):
        mock_get_workflows.return_value = [
            {'id': 'wf-1', 'status': 'success'},
            {'id': 'wf-2', 'status': 'running'},
            {'id': 'wf-3', 'status': 'failed'}
        ]
        assert get_workflow_status('pipeline-123', silent=True) == 'running'

    @patch('circleCi.monitoring.get_pipeline_workflows')
    def test_on_hold_when_no_running(self, mock_get_workflows):
        mock_get_workflows.return_value = [
            {'id': 'wf-1', 'status': 'success'},
            {'id': 'wf-2', 'status': 'on_hold'}
        ]
        assert get_workflow_status('pipeline-123', silent=True) == 'on_hold'

    @patch('circleCi.monitoring.get_pipeline_workflows')
    def test_all_complete_returns_last(self, mock_get_workflows):
        mock_get_workflows.return_value = [
            {'id': 'wf-1', 'status': 'success'},
            {'id': 'wf-2', 'status': 'failed'}
        ]
        assert get_workflow_status('pipeline-123', silent=True) == 'failed'

    @patch('circleCi.monitoring.get_pipeline_workflows')
    def test_empty_workflows(self, mock_get_workflows):
        mock_get_workflows.return_value = []
        assert get_workflow_status('pipeline-123', silent=True) is None

    @patch('circleCi.monitoring.get_pipeline_workflows')
    def test_none_workflows(self, mock_get_workflows):
        mock_get_workflows.return_value = None
        assert get_workflow_status('pipeline-123', silent=True) is None

    @patch('circleCi.monitoring.get_pipeline_workflows')
    def test_missing_status_key_defaults_unknown(self, mock_get_workflows):
        mock_get_workflows.return_value = [{'id': 'wf-1'}, {'id': 'wf-2'}]
        assert get_workflow_status('pipeline-123', silent=True) == 'unknown'


class TestGetPipelineIdByNumber:
    """测试 get_pipeline_id_by_number 函数"""

    @patch('circleCi.monitoring.call_circleci_api')
    def test_found_returns_matching_id(self, mock_api):
        mock_api.return_value = (_ok_response({
            'items': [
                {'id': 'pipeline-1', 'number': 100},
                {'id': 'pipeline-2', 'number': 101},
                {'id': 'pipeline-3', 'number': 102},
            ]
        }), None)

        result = get_pipeline_id_by_number('github/org/repo', 101, api_token='test-token')

        assert result == 'pipeline-2'
        mock_api.assert_called_once_with(
            'project/github/org/repo/pipeline', api_token='test-token'
        )

    @patch('circleCi.monitoring.call_circleci_api')
    def test_not_found_in_items(self, mock_api):
        mock_api.return_value = (_ok_response({
            'items': [{'id': 'pipeline-1', 'number': 100}]
        }), None)

        assert get_pipeline_id_by_number('github/org/repo', 999, api_token='t') is None

    @patch('circleCi.monitoring.call_circleci_api')
    def test_empty_items(self, mock_api):
        mock_api.return_value = (_ok_response({'items': []}), None)

        assert get_pipeline_id_by_number('github/org/repo', 100, api_token='t') is None

    @patch('circleCi.monitoring.call_circleci_api')
    def test_http_error_returns_none(self, mock_api):
        mock_api.return_value = (None, {'status_code': 404, 'error': 'x'})

        assert get_pipeline_id_by_number('github/org/repo', 100, api_token='t') is None

    @patch('circleCi.monitoring.call_circleci_api')
    def test_network_error_returns_none(self, mock_api):
        mock_api.return_value = (None, {'error': 'boom'})

        assert get_pipeline_id_by_number('github/org/repo', 100, api_token='t') is None
