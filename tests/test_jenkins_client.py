"""
tests/test_jenkins_client.py
覆盖 modules/jenkins_client.py 核心路径（全部 mock HTTP，无外部依赖）
"""
import queue

import pytest
from unittest.mock import MagicMock, patch

from modules.jenkins_client import (
    buildJobUrl,
    buildJobUrl as _buildJobUrl,
    executeDeploy,
    fetchRecentBranches,
    getBuildNumber,
    isKeyConsoleLine,
    runConnectionTest,
    runDeployThread,
    runProdInspect,
    triggerBuild,
    waitForBuild,
)


def _mock_response(status_code=200, json_data=None, text="", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.headers = headers or {}
    return resp


class TestBuildJobUrl:
    def test_builds_folder_url(self):
        assert buildJobUrl("svc", "https://j.example.com/") == "https://j.example.com/job/PP/job/svc"

    def test_custom_folder(self):
        assert buildJobUrl("svc", "https://j.example.com", "Prod") == "https://j.example.com/job/Prod/job/svc"


class TestTriggerBuild:
    def test_success_returns_queue_url(self):
        resp = _mock_response(201, headers={"Location": "https://j/queue/item/1/"})
        with patch("modules.jenkins_client.requests.post", return_value=resp) as mock_post:
            result = triggerBuild("svc", "master", auth=None, jenkins_url="https://j")
        assert result == "https://j/queue/item/1/"
        args, kwargs = mock_post.call_args
        assert args[0] == "https://j/job/PP/job/svc/buildWithParameters"
        assert kwargs["params"] == {"BRANCH": "master"}

    def test_failure_status_returns_none(self):
        with patch("modules.jenkins_client.requests.post", return_value=_mock_response(403)):
            assert triggerBuild("svc", "master", auth=None, jenkins_url="https://j") is None

    def test_exception_returns_none(self):
        with patch("modules.jenkins_client.requests.post", side_effect=ConnectionError("down")):
            assert triggerBuild("svc", "master", auth=None, jenkins_url="https://j") is None


class TestGetBuildNumber:
    def test_returns_number_when_executable(self):
        resp = _mock_response(200, {"executable": {"number": 42}})
        with patch("modules.jenkins_client.requests.get", return_value=resp):
            assert getBuildNumber("https://j/queue/item/1/", auth=None, timeout=5) == 42

    def test_timeout_returns_none(self):
        # 一直 200 但无 executable → 超时返回 None
        resp = _mock_response(200, {})
        with patch("modules.jenkins_client.requests.get", return_value=resp), \
             patch("modules.jenkins_client.time.sleep"):
            assert getBuildNumber("https://j/queue/item/1/", auth=None, timeout=0) is None


class TestIsKeyConsoleLine:
    def test_keyword_line_is_key(self):
        assert isKeyConsoleLine("BUILD SUCCESS in 30s") is True
        assert isKeyConsoleLine("error: something failed") is True

    def test_noise_prefix_is_not_key(self):
        assert isKeyConsoleLine("Downloading 50% ...") is False
        assert isKeyConsoleLine("[debug] internal") is False

    def test_empty_is_not_key(self):
        assert isKeyConsoleLine("   ") is False


class TestWaitForBuild:
    def test_returns_true_on_success(self):
        # build 已结束 result=SUCCESS；consoleText 为空
        state = {"n": 0}

        def fake_get(url, **kwargs):
            if url.endswith("api/json"):
                return _mock_response(200, {"building": False, "result": "SUCCESS"})
            return _mock_response(200, text="")

        with patch("modules.jenkins_client.requests.get", side_effect=fake_get), \
             patch("modules.jenkins_client.time.sleep"):
            ok = waitForBuild("svc", 7, auth=None, jenkins_url="https://j", log_cb=lambda m: None)
        assert ok is True

    def test_returns_false_on_failure_result(self):
        def fake_get(url, **kwargs):
            if url.endswith("api/json"):
                return _mock_response(200, {"building": False, "result": "FAILURE"})
            return _mock_response(200, text="")

        with patch("modules.jenkins_client.requests.get", side_effect=fake_get):
            ok = waitForBuild("svc", 7, auth=None, jenkins_url="https://j", log_cb=lambda m: None)
        assert ok is False


class TestExecuteDeploy:
    def test_happy_path(self):
        queue_resp = _mock_response(201, headers={"Location": "https://j/queue/item/1/"})
        number_resp = _mock_response(200, {"executable": {"number": 9}})
        done_resp = _mock_response(200, {"building": False, "result": "SUCCESS"})
        console_resp = _mock_response(200, text="")

        def fake_post(url, **kwargs):
            return queue_resp

        def fake_get(url, **kwargs):
            if "queue/item" in url:
                return number_resp
            if url.endswith("consoleText"):
                return console_resp
            return done_resp

        logs = []
        with patch("modules.jenkins_client.requests.post", side_effect=fake_post), \
             patch("modules.jenkins_client.requests.get", side_effect=fake_get), \
             patch("modules.jenkins_client.time.sleep"):
            ok = executeDeploy("svc", "master", auth=None, jenkins_url="https://j", log_cb=logs.append)
        assert ok is True
        assert any("触发构建" in m for m in logs)
        assert any("成功" in m for m in logs)

    def test_trigger_failure_short_circuits(self):
        with patch("modules.jenkins_client.requests.post", return_value=_mock_response(403)):
            logs = []
            ok = executeDeploy("svc", "master", auth=None, jenkins_url="https://j", log_cb=logs.append)
        assert ok is False
        assert any("触发失败" in m for m in logs)


class TestFetchRecentBranches:
    def test_filters_success_builds_and_extracts_branch(self):
        builds = {
            "builds": [
                {
                    "number": 10,
                    "result": "SUCCESS",
                    "displayName": "prod #10",
                    "timestamp": 1700000000000,
                    "actions": [{"parameters": [{"name": "BRANCH", "value": "release/1.2"}]}],
                },
                {"number": 9, "result": "FAILURE", "timestamp": 1700000000000, "actions": []},
            ]
        }
        with patch("modules.jenkins_client.requests.get", return_value=_mock_response(200, builds)):
            results = fetchRecentBranches("svc", auth=None, jenkins_url="https://j")
        assert len(results) == 1
        assert results[0]["branch"] == "release/1.2"
        assert results[0]["number"] == 10

    def test_non_200_returns_empty(self):
        with patch("modules.jenkins_client.requests.get", return_value=_mock_response(500)):
            assert fetchRecentBranches("svc", auth=None, jenkins_url="https://j") == []

    def test_max_count_limits_results(self):
        builds = {
            "builds": [
                {"number": i, "result": "SUCCESS", "timestamp": 1700000000000, "actions": []}
                for i in range(10)
            ]
        }
        with patch("modules.jenkins_client.requests.get", return_value=_mock_response(200, builds)):
            results = fetchRecentBranches("svc", auth=None, jenkins_url="https://j", max_count=3)
        assert len(results) == 3


class TestRunDeployThread:
    def test_sequential_deploy_reports_done(self):
        queue_resp = _mock_response(201, headers={"Location": "https://j/queue/item/1/"})
        number_resp = _mock_response(200, {"executable": {"number": 9}})
        done_resp = _mock_response(200, {"building": False, "result": "SUCCESS"})

        def fake_get(url, **kwargs):
            if "queue/item" in url:
                return number_resp
            return done_resp

        log_q = queue.Queue()
        with patch("modules.jenkins_client.requests.post", return_value=queue_resp), \
             patch("modules.jenkins_client.requests.get", side_effect=fake_get), \
             patch("modules.jenkins_client.time.sleep"):
            runDeployThread({"svc-a": "master", "svc-b": "dev"}, auth=None,
                            jenkins_url="https://j", is_concurrent=False, log_q=log_q)

        msgs = list(log_q.queue)
        done = [m for m in msgs if isinstance(m, tuple) and m[0] == "__DONE__"]
        assert len(done) == 1
        assert done[0][1] == {"svc-a": True, "svc-b": True}
        assert any("2/2 成功" in str(m) for m in msgs if isinstance(m, str))


class TestRunConnectionTest:
    def test_auth_failure_reports_test_done_false(self):
        log_q = queue.Queue()
        with patch("modules.jenkins_client.requests.get", return_value=_mock_response(401, {"x": 1})):
            runConnectionTest("user", "token", "https://j", log_q)
        done = [m for m in list(log_q.queue) if isinstance(m, tuple)]
        assert done == [("__TEST_DONE__", False)]

    def test_full_pass_reports_test_done_true(self):
        log_q = queue.Queue()

        def fake_get(url, **kwargs):
            if url.endswith("/me/api/json"):
                return _mock_response(200, {"fullName": "QA", "id": "qa"})
            return _mock_response(200, {"jobs": [{"name": "a"}]})

        with patch("modules.jenkins_client.requests.get", side_effect=fake_get):
            runConnectionTest("user", "token", "https://j", log_q)
        done = [m for m in list(log_q.queue) if isinstance(m, tuple)]
        assert done == [("__TEST_DONE__", True)]
        text_logs = [m for m in list(log_q.queue) if isinstance(m, str)]
        assert any("Full Name: QA" in m for m in text_logs)


class TestRunProdInspect:
    def test_readonly_inspect_reports_done(self):
        log_q = queue.Queue()

        def fake_get(url, **kwargs):
            # Prod 文件夹存在
            if url.endswith("/job/Prod/api/json"):
                return _mock_response(200, {"jobs": [{"name": "prod-svc-a"}]})
            # 服务详情
            return _mock_response(200, {
                "buildable": True, "description": "svc",
                "lastBuild": {"number": 3},
                "lastSuccessfulBuild": {"number": 2},
            })

        with patch("modules.jenkins_client.requests.get", side_effect=fake_get):
            runProdInspect("user", "token", "https://j", log_q, ["prod-svc-a", "prod-svc-b"])

        msgs = [m for m in list(log_q.queue) if isinstance(m, str)]
        done = [m for m in list(log_q.queue) if isinstance(m, tuple)]
        assert done == [("__INSPECT_DONE__", None)]
        assert any("prod-svc-a" in m and "存在" in m for m in msgs)
        assert any("prod-svc-b" in m and "未找到" in m for m in msgs)
