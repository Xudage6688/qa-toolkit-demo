"""
Test Tools - 测试工具集页面
将测试小工具集成到 Streamlit 界面
"""

import streamlit as st
import sys
import os
import json
import logging
import time
import webbrowser
from pathlib import Path
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules._test_tools._api_perf_test import (
  APIPerformanceTester, TestConfig, parse_curl_command,
)
from modules._test_tools._clean_download import clean_download_files, format_size
from modules._test_tools._create_aca_account import create_aca_account, AccountInfo
from modules._test_tools._create_prefilled_link import PaymentLinkGenerator, DEFAULT_INVOICE_URL
from modules._test_tools._generate_pdf import generate_minimal_pdf
from modules._test_tools._generate_photo import generate_random_photos, generate_number_photos
from modules._test_tools._get_photo_from_url import TESLA_MODEL_MAP, download_tesla_images
from modules._test_tools._python_auto_gui import MouseMover
from modules._test_tools._shein_order import SheinOrderFlow
from modules._test_tools._prod_login_runner import (
  ProdLoginResult,
  ProdLoginRunner,
  casesToRows,
  parseProdLoginCases,
  resolvePlaywrightProjectPath,
)
from modules._test_tools._playwright_flow_runner import PlaywrightFlowRunner
from modules._test_tools._cypress_weekly_runner import (
  ALLOWED_BROWSERS,
  DEFAULT_SPEC,
  CypressWeeklyError,
  defaultCypressStateDir,
  loadCypressWeeklyPrefs,
  readEditableCypressEnv,
  readCypressWeeklyLog,
  refreshCypressWeeklyRun,
  startCypressWeeklyRun,
  stopCypressWeeklyRun,
)
from modules._myqima_booking._booking_runner import formatBookingLogText
import importlib
from modules._myqima_booking import _config_builder as _myqima_config_builder

importlib.reload(_myqima_config_builder)
LOB_BOOKING_TYPES = _myqima_config_builder.LOB_BOOKING_TYPES
EA_VARIANTS = _myqima_config_builder.EA_VARIANTS
ENVA_VARIANTS = _myqima_config_builder.ENVA_VARIANTS
DEFAULT_LONG_PO_CHARS = _myqima_config_builder.DEFAULT_LONG_PO_CHARS
DEFAULT_LONG_PRODUCT_NAME_CHARS = _myqima_config_builder.DEFAULT_LONG_PRODUCT_NAME_CHARS
factorySectionDictForStorage = _myqima_config_builder.factorySectionDictForStorage
longTextFieldsDictForStorage = _myqima_config_builder.longTextFieldsDictForStorage
persistMyqimaUserPrefs = _myqima_config_builder.persistMyqimaUserPrefs
BookingConfig = _myqima_config_builder.BookingConfig
build_ppsso_url = _myqima_config_builder.build_ppsso_url
loadMyqimaTestAccountPresets = _myqima_config_builder.loadMyqimaTestAccountPresets
myqimaTestAccountPresetOptions = _myqima_config_builder.myqimaTestAccountPresetOptions
resolveMyqimaPresetLabelForUsername = _myqima_config_builder.resolveMyqimaPresetLabelForUsername
applyMyqimaTestAccountPreset = _myqima_config_builder.applyMyqimaTestAccountPreset
MYQIMA_PRESET_CUSTOM_LABEL = _myqima_config_builder.MYQIMA_PRESET_CUSTOM_LABEL

st.set_page_config(page_title="Test Tools", page_icon="🧪", layout="wide")

st.title("🧪 Test Tools")
st.markdown("日常测试辅助工具集合，全部在本地运行。")

# Initialize session_state
if "mouse_mover" not in st.session_state:
  st.session_state.mouse_mover = MouseMover()

if "shein_logs" not in st.session_state:
  st.session_state.shein_logs = []

if "myqima_regression_summary" not in st.session_state:
  st.session_state.myqima_regression_summary = None
if "myqima_regression_running" not in st.session_state:
  st.session_state.myqima_regression_running = False
if "prefilled_last_request_id" not in st.session_state:
  st.session_state.prefilled_last_request_id = ""
if "prefilled_last_env" not in st.session_state:
  st.session_state.prefilled_last_env = "PP"
if "prefilled_last_link_result" not in st.session_state:
  st.session_state.prefilled_last_link_result = None
if "prefilled_last_invoice_result" not in st.session_state:
  st.session_state.prefilled_last_invoice_result = None
if "prod_login_running" not in st.session_state:
  st.session_state.prod_login_running = False
if "prod_login_last_result" not in st.session_state:
  st.session_state.prod_login_last_result = None
if "pr_url_open_result" not in st.session_state:
  st.session_state.pr_url_open_result = None


# ── 0. Prod 快速验证 ──
with st.expander("⚡ Prod 快速验证", expanded=False):
  st.markdown(
    "运行 Playwright `prod-login.spec.ts` 整套生产环境冒烟用例，"
    "实时输出日志与通过/失败汇总。"
  )
  st.caption("运行中请勿刷新页面，否则可能导致浏览器进程残留。")

  _prod_cfg = {}
  _prod_curr_user = st.session_state.get("current_user")
  _prod_cfg_path = os.path.join(
    os.path.dirname(__file__), "..", "config", "users_config.json"
  )
  if _prod_curr_user:
    try:
      with open(_prod_cfg_path, encoding="utf-8") as _fh:
        _prod_all_cfg = json.load(_fh)
      _prod_cfg = (
        _prod_all_cfg.get("users", {})
        .get(_prod_curr_user, {})
        .get("myqima", {})
      )
    except Exception:
      pass

  _webtools_root = Path(__file__).resolve().parents[1]
  _prod_default_path = _prod_cfg.get("playwright_project_path", "") or ""
  try:
    _prod_resolved = resolvePlaywrightProjectPath(
      _prod_default_path, _webtools_root
    )
    _prod_path_value = str(_prod_resolved)
  except FileNotFoundError:
    _prod_path_value = _prod_default_path

  _prod_playwright_path = st.text_input(
    "Playwright 项目路径",
    value=_prod_path_value,
    key="prod_login_playwright_path",
    help="优先使用 users_config 中 myqima.playwright_project_path；"
    "为空时自动探测与 webtools 同级的 playwright 目录",
  )
  _prod_headed = st.checkbox(
    "显示浏览器（headed）",
    value=False,
    key="prod_login_headed",
    help="默认无头运行；勾选后弹出 Chromium 便于目视排查",
  )

  _prod_col_run, _prod_col_clear = st.columns(2)
  with _prod_col_run:
    _btn_prod = st.button(
      "▶️ 开始 Prod 验证",
      use_container_width=True,
      key="btn_prod_login",
      disabled=st.session_state.prod_login_running,
    )
  with _prod_col_clear:
    if st.button(
      "🗑️ 清空结果", use_container_width=True, key="btn_prod_login_clear"
    ):
      st.session_state.prod_login_last_result = None
      st.rerun()

  if _btn_prod:
    if not _prod_playwright_path or not _prod_playwright_path.strip():
      st.error("请配置 Playwright 项目路径")
    else:
      try:
        _prod_proj = resolvePlaywrightProjectPath(
          _prod_playwright_path.strip(), _webtools_root
        )
      except FileNotFoundError as _prod_path_err:
        st.error(str(_prod_path_err))
        _prod_proj = None

      if _prod_proj is not None:
        if _prod_curr_user:
          try:
            with open(_prod_cfg_path, encoding="utf-8") as _fh:
              _prod_all_cfg = json.load(_fh)
            if "users" not in _prod_all_cfg:
              _prod_all_cfg["users"] = {}
            if _prod_curr_user not in _prod_all_cfg["users"]:
              _prod_all_cfg["users"][_prod_curr_user] = {}
            if "myqima" not in _prod_all_cfg["users"][_prod_curr_user]:
              _prod_all_cfg["users"][_prod_curr_user]["myqima"] = {}
            _prod_all_cfg["users"][_prod_curr_user]["myqima"][
              "playwright_project_path"
            ] = str(_prod_proj)
            with open(_prod_cfg_path, "w", encoding="utf-8") as _fh:
              json.dump(_prod_all_cfg, _fh, indent=2, ensure_ascii=False)
          except Exception as _prod_save_ex:
            logging.warning("保存 playwright_project_path 失败: %s", _prod_save_ex)

        st.session_state.prod_login_running = True
        _prod_case_box = st.empty()
        _prod_log_box = st.empty()
        _prod_log_lines: list[str] = []
        _prod_run_result: ProdLoginResult | None = None
        _prod_log_keep = 500
        try:
          _prod_runner = ProdLoginRunner(_prod_proj)
          with st.spinner("正在执行 Prod 快速验证（整套 prod-login）..."):
            for _prod_item in _prod_runner.stream(headed=_prod_headed):
              if isinstance(_prod_item, str):
                _prod_log_lines.append(_prod_item)
                _prod_live_cases = parseProdLoginCases(_prod_log_lines)
                if _prod_live_cases:
                  _prod_case_box.dataframe(
                    casesToRows(_prod_live_cases),
                    use_container_width=True,
                    hide_index=True,
                  )
                if len(_prod_log_lines) % 2 == 0:
                  _prod_log_box.code(
                    "\n".join(_prod_log_lines[-80:]), language="text"
                  )
              else:
                _prod_run_result = _prod_item

          _prod_final_cases = (
            _prod_run_result.cases
            if _prod_run_result and _prod_run_result.cases
            else parseProdLoginCases(_prod_log_lines)
          )
          if _prod_final_cases:
            _prod_case_box.dataframe(
              casesToRows(_prod_final_cases),
              use_container_width=True,
              hide_index=True,
            )
          _prod_log_box.code("\n".join(_prod_log_lines[-120:]), language="text")
          st.session_state.prod_login_last_result = {
            "success": bool(_prod_run_result and _prod_run_result.success),
            "passed": _prod_run_result.passed if _prod_run_result else 0,
            "failed": _prod_run_result.failed if _prod_run_result else 0,
            "skipped": _prod_run_result.skipped if _prod_run_result else 0,
            "exit_code": (
              _prod_run_result.exit_code if _prod_run_result else None
            ),
            "error": _prod_run_result.error if _prod_run_result else "",
            "logs": _prod_log_lines[-_prod_log_keep:],
            "cases": casesToRows(_prod_final_cases),
            "project_path": str(_prod_proj),
            "headed": _prod_headed,
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          }
        except Exception as _prod_ex:
          st.error(f"执行异常: {_prod_ex}")
          _prod_err_cases = parseProdLoginCases(_prod_log_lines)
          st.session_state.prod_login_last_result = {
            "success": False,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "exit_code": None,
            "error": str(_prod_ex),
            "logs": _prod_log_lines[-_prod_log_keep:],
            "cases": casesToRows(_prod_err_cases),
            "project_path": str(_prod_proj),
            "headed": _prod_headed,
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          }
        finally:
          st.session_state.prod_login_running = False
          st.rerun()

  _prod_prev = st.session_state.prod_login_last_result
  if _prod_prev:
    st.markdown("#### 📊 最近一次结果")
    st.caption(
      f"完成时间: {_prod_prev.get('finished_at', '-')} | "
      f"路径: {_prod_prev.get('project_path', '-')} | "
      f"headed: {_prod_prev.get('headed', False)}"
    )
    _pm1, _pm2, _pm3, _pm4 = st.columns(4)
    _pm1.metric("状态", "✅ 通过" if _prod_prev.get("success") else "❌ 失败")
    _pm2.metric("Passed", _prod_prev.get("passed", 0))
    _pm3.metric("Failed", _prod_prev.get("failed", 0))
    _pm4.metric("Skipped", _prod_prev.get("skipped", 0))
    if _prod_prev.get("error") and not _prod_prev.get("success"):
      st.error(_prod_prev["error"])
    _prod_case_rows = _prod_prev.get("cases") or []
    if _prod_case_rows:
      st.markdown("##### 用例明细")
      st.dataframe(
        _prod_case_rows, use_container_width=True, hide_index=True
      )
    with st.expander("📋 完整日志", expanded=False):
      st.code("\n".join(_prod_prev.get("logs") or []), language="text")


# ── 0b. PR URL 批量访问 ──
with st.expander("🌐 PR URL 批量访问", expanded=False):
  st.markdown("输入多个 PR URL（每行一个），点击按钮即可在系统默认浏览器中批量打开。")

  pr_url_input = st.text_area(
    "请输入 PR URL（每行一个）",
    value="",
    placeholder="例如：\nhttps://github.com/example/pr1\nhttps://github.com/example/pr2",
    key="pr_url_input",
    height=200,
  )

  if not pr_url_input:
    st.session_state.pr_url_open_result = None

  if st.session_state.pr_url_open_result:
    st.caption(st.session_state.pr_url_open_result)

  if st.button("Open URL", use_container_width=True, type="primary", key="btn_open_pr_url"):
    if not pr_url_input:
      st.session_state.pr_url_open_result = None
      st.warning("⚠️ 请输入有效的 PR URL")
    else:
      urls = []
      for url in pr_url_input.split("\n"):
        url = url.strip().replace('"', "").replace("'", "")
        if url:
          urls.append(url)

      if not urls:
        st.session_state.pr_url_open_result = None
        st.warning("⚠️ 请输入有效的 PR URL（已过滤空行和无效 URL）")
      else:
        try:
          browser = webbrowser.get()
          opened_count = 0
          for i, url in enumerate(urls):
            try:
              browser.open(url)
              opened_count += 1
              if i < len(urls) - 1:
                time.sleep(0.3)
            except Exception as e:
              st.warning(f"⚠️ 无法打开: {url} - {e}")
          st.session_state.pr_url_open_result = (
            f"成功打开 {opened_count} 个 URL / 共输入 {len(urls)} 个 URL"
          )
          st.rerun()
        except Exception as e:
          logging.error("打开 PR URL 失败: %s", e)
          st.error(f"打开 URL 失败: {e}")


# ── 1. API 性能测试 ──
with st.expander("🚀 API 性能测试", expanded=False):
  st.markdown("对目标 API 进行并发压力测试，生成响应时间分布和吞吐量报告。")

  col1, col2 = st.columns(2)
  with col1:
    api_url = st.text_input("API URL", placeholder="https://api.example.com/data")
    api_method = st.selectbox("HTTP Method", ["GET", "POST"])
  with col2:
    concurrent_users = st.number_input("并发用户数", min_value=1, value=10, step=1)
    test_mode_api = st.selectbox("测试模式", ["按请求数", "按持续时间"], key="test_mode_api")
    if test_mode_api == "按请求数":
      total_requests = st.number_input("总请求数", min_value=1, value=100, step=10)
    else:
      duration_seconds = st.number_input("持续时间(秒)", min_value=5, value=60, step=5)

  api_headers = st.text_area("Headers (JSON)", height=80, placeholder='{"Authorization": "Bearer xxx"}')
  api_params = st.text_area("Params (JSON)", height=80, placeholder='{"page": "1", "size": "10"}')

  col1, col2 = st.columns([1, 1])
  with col1:
    api_curl = st.text_area("或直接粘贴 curl 命令", height=100, placeholder="curl --location 'https://...' --header '...'")
  with col2:
    st.markdown("#####  ")
    if st.button("🚀 开始测试", use_container_width=True, key="btn_api_test"):
      if not api_url and not api_curl:
        st.error("请输入 API URL 或 curl 命令")
      else:
        try:
          if api_curl:
            config = parse_curl_command(api_curl)
          else:
            config = TestConfig(
              url=api_url, method=api_method,
              headers=json.loads(api_headers) if api_headers else None,
              params=json.loads(api_params) if api_params else {},
            )
          config.concurrent_users = concurrent_users
          if test_mode_api == "按持续时间":
            config.test_mode = "duration"
            config.duration_seconds = duration_seconds
          else:
            config.total_requests = total_requests
          tester = APIPerformanceTester(config)
          with st.spinner("正在执行测试..."):
            if config.test_mode == "duration":
              results = tester.run_duration_test()
            else:
              results = tester.run_sync_test()
          report = tester.generate_report(results)
          fig = tester.create_charts(results, report)

          st.markdown("### 📊 测试报告")
          m1, m2, m3, m4 = st.columns(4)
          m1.metric("成功率", f"{report.success_rate:.1f}%")
          m2.metric("平均响应时间", f"{report.average_response_time * 1000:.1f}ms")
          m3.metric("P95", f"{report.p95_response_time * 1000:.1f}ms")
          m4.metric("吞吐量", f"{report.requests_per_second:.1f} RPS")

          c1, c2, c3 = st.columns(3)
          c1.metric("成功/总计", f"{report.successful_requests}/{report.total_requests}")
          c2.metric("测试耗时", f"{report.test_duration:.2f}s")
          c3.metric("并发用户", f"{report.concurrent_users}")

          colStat1, colStat2 = st.columns(2)
          with colStat1:
            st.metric("P75", f"{report.p75_response_time * 1000:.1f}ms")
            st.metric("P90", f"{report.p90_response_time * 1000:.1f}ms")
            st.metric("P99", f"{report.p99_response_time * 1000:.1f}ms")
            st.metric("标准差", f"{report.std_dev_response_time * 1000:.2f}ms")
          with colStat2:
            st.metric("数据量", f"{report.total_data_transferred / 1024:.1f}KB")
            st.metric("最小响应", f"{report.min_response_time * 1000:.1f}ms")
            st.metric("最大响应", f"{report.max_response_time * 1000:.1f}ms")
            st.metric("失败数", f"{report.failed_requests}")

          st.pyplot(fig)

          with st.expander("📋 详细报告"):
            scDist = {str(k): v for k, v in sorted((report.status_code_distribution or {}).items())}
            st.json({
              "total_requests": report.total_requests,
              "successful": report.successful_requests,
              "failed": report.failed_requests,
              "success_rate": f"{report.success_rate:.2f}%",
              "avg_ms": round(report.average_response_time * 1000, 2),
              "median_ms": round(report.median_response_time * 1000, 2),
              "p75_ms": round(report.p75_response_time * 1000, 2),
              "p90_ms": round(report.p90_response_time * 1000, 2),
              "p95_ms": round(report.p95_response_time * 1000, 2),
              "p99_ms": round(report.p99_response_time * 1000, 2),
              "std_dev_ms": round(report.std_dev_response_time * 1000, 2),
              "min_ms": round(report.min_response_time * 1000, 2),
              "max_ms": round(report.max_response_time * 1000, 2),
              "rps": round(report.requests_per_second, 2),
              "duration_sec": round(report.test_duration, 2),
              "concurrent_users": report.concurrent_users,
              "data_transferred_kb": round(report.total_data_transferred / 1024, 2),
              "status_code_distribution": scDist,
              "error_distribution": report.error_distribution or {},
            })
        except Exception as e:
          st.error(f"测试失败: {e}")


# ── 2. 下载目录清理 ──
with st.expander("🗑️ 下载目录清理", expanded=False):
  st.markdown("清理指定目录中的特定类型文件。")

  clean_path = st.text_input("目标目录", value=os.path.expanduser("~/Downloads"), key="clean_path")
  clean_exts = st.text_input("文件扩展名（逗号分隔）", value="exe, zip, jpg, png", key="clean_exts")

  if st.button("🔍 扫描并清理", use_container_width=True, key="btn_clean_scan"):
    exts = [e.strip() for e in clean_exts.split(",") if e.strip()]
    result = clean_download_files(clean_path, exts)
    if result["deleted_count"] > 0 or result["failed_count"] > 0:
      st.success(f"已删除 {result['deleted_count']} 个文件（{format_size(result['total_size'])}），失败 {result['failed_count']} 个")
      if result["deleted_files"]:
        with st.expander("已删除文件列表"):
          for f in result["deleted_files"]:
            st.text(f)
      if result["failed_files"]:
        with st.expander("失败详情"):
          for f in result["failed_files"]:
            st.error(f"{f['file']}: {f['error']}")
    else:
      st.info("未找到匹配的文件")


# ── 3. ACA 账号创建 ──
with st.expander("🏢 ACA 账号创建", expanded=False):
  st.markdown("在 DEV/PP 环境快速创建测试公司账号。")

  col1, col2 = st.columns(2)
  with col1:
    aca_login = st.text_input("登录名", key="aca_login")
    aca_email = st.text_input("邮箱", key="aca_email")
  with col2:
    aca_password = st.text_input("密码", type="password", key="aca_password")
    aca_company = st.text_input("公司名称", key="aca_company")
  aca_env = st.selectbox("环境", ["PP", "DEV"], key="aca_env")

  if st.button("创建账号", use_container_width=True, key="btn_aca"):
    if not all([aca_login, aca_email, aca_password, aca_company]):
      st.error("请填写所有必填字段")
    else:
      info = AccountInfo(login=aca_login, emails=aca_email, password=aca_password, company_name=aca_company)
      result = create_aca_account(info, aca_env)
      if result["success"]:
        st.success("✅ 账号创建成功")
        if "account_info" in result:
          st.json(result["account_info"])
        if "data" in result:
          st.json(result["data"])
      else:
        st.error(f"❌ 创建失败: {result.get('error', '未知错误')}")


# ── 4. Prefilled Link 生成 ──
with st.expander("🔗 Prefilled Link 生成", expanded=False):
  st.markdown("生成预填充支付链接（两步流程，自动获取 sign）。")

  link_mode = st.selectbox("模式", ["正常", "随机金额", "分钟精度", "已过期", "待生效"], key="link_mode")

  c1, c2, c3 = st.columns(3)
  with c1:
    link_amount = st.number_input("金额", min_value=0.01, value=250.0, step=10.0, key="link_amount")
  with c2:
    link_env = st.selectbox("环境", ["PP", "DEV", "PROD"], key="link_env")
  with c3:
    link_bu = st.selectbox("BU", ["qima", "qimawqs", "qimacertis", "qimawqsmexico"], key="link_bu")

  c1, c2, c3 = st.columns(3)
  with c1:
    link_currency = st.selectbox("币种", ["USD", "EUR", "MXN"], key="link_currency")
  with c2:
    link_discount_pct = st.number_input("折扣比例", min_value=0.0, max_value=1.0, value=0.05, step=0.01, format="%.2f", key="link_discount_pct")
  with c3:
    link_customer_id = st.text_input("客户ID", value="5C9B1F313EE14F95B79372F950F88165", key="link_customer_id")

  # 根据模式动态展示有效期字段
  link_days_val = 2
  link_minutes_val = 30
  link_pending_val = 10
  link_duration_val = 60

  if link_mode in ("正常", "随机金额"):
    link_days_val = st.number_input("有效期（天）", min_value=0, value=2, key="link_days")
  elif link_mode == "分钟精度":
    link_minutes_val = st.number_input("有效期（分钟）", min_value=1, value=30, key="link_minutes")
  elif link_mode == "已过期":
    link_minutes_val = st.number_input("已过期（分钟）", min_value=1, value=5, key="link_minutes",
                                       help="结束时间在当前时间之前多少分钟")
  elif link_mode == "待生效":
    pc1, pc2 = st.columns(2)
    with pc1:
      link_pending_val = st.number_input("开始前等待（分钟）", min_value=1, value=10, key="link_pending",
                                         help="折扣开始时间在当前时间之后多少分钟")
    with pc2:
      link_duration_val = st.number_input("折扣持续（分钟）", min_value=1, value=60, key="link_duration")

  col1, col2 = st.columns([1, 3])
  with col1:
    if st.button("生成 Link", use_container_width=True, key="btn_link"):
      if not link_amount:
        st.error("请输入金额")
      else:
        try:
          import modules._test_tools._create_prefilled_link as _cpl
          _cpl.DEFAULT_FIELDS["bu"] = link_bu
          _cpl.DEFAULT_FIELDS["currency"] = link_currency
          _cpl.DEFAULT_FIELDS["percentDiscount"] = link_discount_pct
          _cpl.DEFAULT_FIELDS["customerId"] = link_customer_id

          generator = PaymentLinkGenerator(environment=link_env)
          with st.spinner("正在生成..."):
            if link_mode == "随机金额":
              result = generator.generate_random_link(discount_days=link_days_val)
            elif link_mode == "分钟精度":
              result = generator.generate_link_by_minutes(amount=link_amount, discount_minutes=link_minutes_val)
            elif link_mode == "已过期":
              result = generator.generate_expired_link(amount=link_amount, expired_minutes=link_minutes_val)
            elif link_mode == "待生效":
              result = generator.generate_pending_link(amount=link_amount, pending_minutes=link_pending_val, discount_duration_minutes=link_duration_val)
            else:
              result = generator.generate_link(amount=link_amount, discount_days=link_days_val)
          if result.success:
            _rid = ""
            if result.request_data:
              _rid = result.request_data.get("requestId", "") or ""
            if _rid:
              st.session_state.prefilled_last_request_id = _rid
              st.session_state.prefilled_last_env = link_env
              st.session_state.invoice_original_request_id = _rid
              st.session_state.invoice_env = link_env
            st.session_state.prefilled_last_link_result = {
              "success": True,
              "link_url": result.link_url,
              "sign": result.sign,
              "request_id": _rid,
              "request_data": result.request_data,
              "error_message": None,
            }
          else:
            st.session_state.prefilled_last_link_result = {
              "success": False,
              "link_url": None,
              "sign": None,
              "request_id": "",
              "request_data": None,
              "error_message": result.error_message,
            }
        except Exception as e:
          st.session_state.prefilled_last_link_result = {
            "success": False,
            "link_url": None,
            "sign": None,
            "request_id": "",
            "request_data": None,
            "error_message": str(e),
          }

  _last_link = st.session_state.prefilled_last_link_result
  if _last_link:
    if _last_link.get("success"):
      st.success("✅ 生成成功")
      if _last_link.get("link_url"):
        st.code(_last_link["link_url"], language="text")
      else:
        st.info("响应已返回但未包含 linkUrl，可查看下方详细数据")
      if _last_link.get("sign"):
        st.text(f"Sign: {_last_link['sign']}")
      if _last_link.get("request_id"):
        st.text(f"RequestId: {_last_link['request_id']}")
      if _last_link.get("request_data"):
        with st.expander("请求数据", expanded=False):
          st.json(_last_link["request_data"])
    else:
      st.error(f"生成失败: {_last_link.get('error_message')}")

  st.markdown("---")
  st.markdown("##### 📄 推送 Invoice")
  st.caption(
    "两步流程自动获取 sign。"
    "生成 Link 成功后会自动带入 originalRequestId；也可手动填写单独推送。"
  )

  _last_rid = st.session_state.prefilled_last_request_id or ""
  _default_invoice_env = st.session_state.prefilled_last_env or link_env

  inv_c1, inv_c2 = st.columns(2)
  with inv_c1:
    invoice_original_id = st.text_input(
      "originalRequestId",
      value=_last_rid,
      key="invoice_original_request_id",
      help="第一次生成 Link 时的 requestId；生成成功后会自动填入，也可手动修改",
    )
  with inv_c2:
    invoice_env = st.selectbox(
      "推送环境",
      ["PP", "DEV", "PROD"],
      index=["PP", "DEV", "PROD"].index(_default_invoice_env)
      if _default_invoice_env in ("PP", "DEV", "PROD") else 0,
      key="invoice_env",
    )

  invoice_url = st.text_input(
    "附件 URL (invoiceUrl)",
    value=DEFAULT_INVOICE_URL,
    key="invoice_url",
  )

  if _last_rid:
    st.info(f"最近一次生成的 RequestId: `{_last_rid}`（环境: {st.session_state.prefilled_last_env}）")

  inv_btn1, inv_btn2 = st.columns([1, 3])
  with inv_btn1:
    if st.button("推送 Invoice", use_container_width=True, key="btn_push_invoice"):
      if not invoice_original_id or not invoice_original_id.strip():
        st.error("请填写 originalRequestId（可先生成 Link，或手动输入）")
      elif not invoice_url or not invoice_url.strip():
        st.error("请填写附件 URL")
      else:
        try:
          inv_gen = PaymentLinkGenerator(environment=invoice_env)
          with st.spinner("正在推送 Invoice（两步获取 sign）..."):
            inv_result = inv_gen.push_invoice(
              original_request_id=invoice_original_id.strip(),
              invoice_url=invoice_url.strip(),
            )
          st.session_state.prefilled_last_invoice_result = {
            "success": inv_result.success,
            "request_id": inv_result.request_id,
            "original_request_id": inv_result.original_request_id,
            "sign": inv_result.sign,
            "error_message": inv_result.error_message,
            "response_data": inv_result.response_data,
          }
        except Exception as e:
          st.session_state.prefilled_last_invoice_result = {
            "success": False,
            "request_id": None,
            "original_request_id": invoice_original_id.strip(),
            "sign": None,
            "error_message": str(e),
            "response_data": None,
          }

  _last_invoice = st.session_state.prefilled_last_invoice_result
  if _last_invoice:
    if _last_invoice.get("success"):
      st.success("✅ Invoice 推送成功")
      st.text(f"requestId: {_last_invoice.get('request_id')}")
      st.text(f"originalRequestId: {_last_invoice.get('original_request_id')}")
      if _last_invoice.get("sign"):
        st.text(f"Sign: {_last_invoice['sign']}")
      if _last_invoice.get("response_data") is not None:
        with st.expander("响应数据"):
          if isinstance(_last_invoice["response_data"], dict):
            st.json(_last_invoice["response_data"])
          else:
            st.code(str(_last_invoice["response_data"]), language="text")
    else:
      st.error(f"推送失败: {_last_invoice.get('error_message')}")
      if _last_invoice.get("response_data") is not None:
        with st.expander("失败响应"):
          if isinstance(_last_invoice["response_data"], dict):
            st.json(_last_invoice["response_data"])
          else:
            st.code(str(_last_invoice["response_data"]), language="text")


# ── 5. PDF 生成 ──
with st.expander("📄 PDF 文件生成", expanded=False):
  st.markdown("生成指定大小的有效 PDF 文件，用于测试上传/下载功能。")

  col1, col2 = st.columns(2)
  with col1:
    pdf_size = st.number_input("目标大小 (MB)", min_value=1, value=5, key="pdf_size")
  with col2:
    pdf_count = st.number_input("文件数量", min_value=1, value=3, key="pdf_count")

  pdf_output_dir = os.path.join(os.getcwd(), "results", "generated_pdf")
  st.caption(f"保存路径: {pdf_output_dir}")

  if st.button("生成 PDF", use_container_width=True, key="btn_pdf"):
    with st.spinner("正在生成 PDF 文件..."):
      try:
        files = generate_minimal_pdf(target_size_mb=pdf_size, file_count=pdf_count, output_dir=pdf_output_dir)
        st.success(f"✅ 成功生成 {len(files)} 个 PDF 文件")
        for f in files:
          size = os.path.getsize(f) / (1024 * 1024)
          st.text(f"📄 {os.path.basename(f)} — {size:.1f} MB")
          with open(f, "rb") as fh:
            st.download_button(f"⬇️ 下载 {os.path.basename(f)}", data=fh, file_name=os.path.basename(f), key=f"dl_pdf_{os.path.basename(f)}")
      except Exception as e:
        st.error(f"生成失败: {e}")


# ── 6. 图片生成 ──
with st.expander("🖼️ 图片生成", expanded=False):
  st.markdown("生成随机像素图或带数字的测试图片。")

  col1, col2, col3 = st.columns(3)
  with col1:
    photo_type = st.selectbox("类型", ["随机像素", "带数字"], key="photo_type")
  with col2:
    photo_count = st.number_input("数量", min_value=1, value=5, key="photo_count")
  with col3:
    photo_width = st.number_input("宽度", min_value=10, value=200, step=10, key="photo_width")
    photo_height = st.number_input("高度", min_value=10, value=200, step=10, key="photo_height")

  photo_output_dir = os.path.join(os.getcwd(), "results", "generated_photos")
  st.caption(f"保存路径: {photo_output_dir}")

  if st.button("生成图片", use_container_width=True, key="btn_photo"):
    with st.spinner("正在生成图片..."):
      try:
        if photo_type == "随机像素":
          files = generate_random_photos(num_photos=photo_count, width=photo_width, height=photo_height, output_dir=photo_output_dir)
        else:
          files = generate_number_photos(num_photos=photo_count, width=photo_width, height=photo_height, output_dir=photo_output_dir)
        st.success(f"✅ 生成 {len(files)} 张图片")
        cols = st.columns(min(5, len(files)))
        for i, f in enumerate(files):
          if i < 5:
            with cols[i]:
              st.image(f, caption=os.path.basename(f), use_container_width=True)
      except Exception as e:
        st.error(f"生成失败: {e}")


# ── 7. Tesla 图片下载 ──
with st.expander("📸 Tesla 车型图片下载", expanded=False):
  st.markdown("从 Tesla 官方图库下载指定车型图片。")

  col1, col2 = st.columns(2)
  with col1:
    tesla_model = st.selectbox("车型", list(TESLA_MODEL_MAP.keys()), key="tesla_model")
  with col2:
    tesla_count = st.number_input("下载数量", min_value=1, max_value=50, value=10, key="tesla_count")

  tesla_output_dir = os.path.join(os.getcwd(), "results", "tesla_photos")
  st.caption(f"保存路径: {tesla_output_dir}")

  if st.button("下载图片", use_container_width=True, key="btn_tesla"):
    try:
      with st.spinner("正在从 Tesla 下载图片..."):
        files = download_tesla_images(tesla_model, tesla_output_dir, target_count=tesla_count)
      st.success(f"✅ 下载 {len(files)} 张图片")
      cols = st.columns(min(5, len(files)))
      for i, f in enumerate(files):
        if i < 5:
          with cols[i]:
            st.image(f, caption=os.path.basename(f), use_container_width=True)
    except Exception as e:
      st.error(f"下载失败: {e}")


# ── 8. 鼠标自动移动 ──
with st.expander("🖱️ 鼠标自动移动", expanded=False):
  st.markdown("自动随机移动鼠标并点击，防止屏幕保护或模拟操作。")

  mover = st.session_state.mouse_mover
  interval = st.number_input("移动间隔（秒）", min_value=5, value=int(mover.interval), step=5, key="mouse_interval")

  col1, col2, col3 = st.columns([1, 1, 2])
  with col1:
    if st.button("▶️ 启动", use_container_width=True, key="btn_mouse_start"):
      mover.interval = interval
      mover.start()
      st.rerun()
  with col2:
    if st.button("⏹️ 停止", use_container_width=True, key="btn_mouse_stop"):
      mover.stop()
      st.rerun()
  with col3:
    status = "🟢 运行中" if mover.is_running else "🔴 已停止"
    st.markdown(f"### 状态: {status}")


# ── 9. SHEIN 订单测试 ──
with st.expander("📋 SHEIN 订单流程测试", expanded=False):
  st.markdown("模拟 SHEIN 订单请求到 QIMA 的完整流程（串行执行，后一步依赖前一步成功）。")

  col1, col2 = st.columns([1, 2])
  with col1:
    if st.button("▶️ 执行全部步骤", use_container_width=True, key="btn_shein"):
      st.session_state.shein_logs = []
      flow = SheinOrderFlow()
      st.session_state.shein_logs.append(flow.log("开始 SHEIN 订单流程测试"))

      with st.spinner("步骤1: 模拟 SHEIN 发送订单请求..."):
        step1_ok = flow.step1_2_mock_shein_booking_request()
      if step1_ok:
        st.session_state.shein_logs.append(flow.log("✅ 步骤1完成: 订单模拟请求发送成功"))

        with st.spinner("步骤2: 处理订单并创建 LT 订单..."):
          step2_ok = flow.step3_4_process_booking_request()
        if step2_ok:
          st.session_state.shein_logs.append(flow.log(f"✅ 步骤2完成: AIMS订单号 {flow.lt_ref_num}"))
          st.session_state.shein_logs.append(flow.log("🎉 流程全部完成"))
        else:
          st.session_state.shein_logs.append(flow.log("❌ 步骤2失败，流程中断"))
      else:
        st.session_state.shein_logs.append(flow.log("❌ 步骤1失败，流程中断"))
      st.rerun()

    if st.button("🗑️ 清空日志", use_container_width=True, key="btn_shein_clear"):
      st.session_state.shein_logs = []
      st.rerun()

  with col2:
    for log in st.session_state.shein_logs:
      st.text(log)


# ── 10. myQIMA 自动下单 ──
with st.expander("🏪 myQIMA 自动下单", expanded=False):
  st.markdown("通过 Playwright 自动执行 myQIMA 业务线下单流程。")
  st.markdown(
    '<style>[data-testid="stCode"] pre { line-height: 1.45 !important; }</style>',
    unsafe_allow_html=True,
  )

  # 读取当前用户配置
  _myqima_cfg = {}
  _curr_user = st.session_state.get("current_user")
  _cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "users_config.json")
  if _curr_user:
    try:
      with open(_cfg_path, encoding="utf-8") as _fh:
        _all_cfg = json.load(_fh)
      _myqima_cfg = _all_cfg.get("users", {}).get(_curr_user, {}).get("myqima", {})
    except Exception:
      pass

  _default_direct = _myqima_cfg.get("directAccount", {})
  _default_ppsso = _myqima_cfg.get("ppssoBackdoor", {})
  _default_path = _myqima_cfg.get("playwright_project_path", "")

  # 先声明变量默认值，防止 Streamlit 条件渲染导致 NameError
  _direct_user = ""
  _direct_pwd = ""
  _ppsso_cid_val = ""
  _ppsso_user_val = ""
  _ppsso_pwd_val = ""

  # 登录方式
  _login_method = st.radio(
    "登录方式", ["myQIMA 账号", "PPSO CompanyId"],
    horizontal=True, key="myqima_login_method",
  )

  if _login_method == "myQIMA 账号":
    _test_account_presets = loadMyqimaTestAccountPresets()
    _preset_options = myqimaTestAccountPresetOptions(_test_account_presets)
    if "myqima_direct_user" not in st.session_state:
      st.session_state.myqima_direct_user = _default_direct.get("username", "") or ""
    if "myqima_direct_pwd" not in st.session_state:
      st.session_state.myqima_direct_pwd = _default_direct.get("password", "") or ""
    if "myqima_test_account_preset" not in st.session_state:
      st.session_state.myqima_test_account_preset = resolveMyqimaPresetLabelForUsername(
        _test_account_presets,
        st.session_state.myqima_direct_user,
      )

    def _onMyqimaTestAccountPresetChange() -> None:
      applyMyqimaTestAccountPreset(
        st.session_state.myqima_test_account_preset,
        _test_account_presets,
        st.session_state,
      )

    def _formatMyqimaPresetLabel(lbl: str) -> str:
      if lbl == MYQIMA_PRESET_CUSTOM_LABEL:
        return lbl
      for _p in _test_account_presets:
        if _p.get("label") == lbl:
          _note = (_p.get("note") or "").strip()
          return f"{lbl} — {_note}" if _note else lbl
      return lbl

    _preset_index = (
      _preset_options.index(st.session_state.myqima_test_account_preset)
      if st.session_state.myqima_test_account_preset in _preset_options
      else 0
    )
    st.selectbox(
      "测试账号（预置）",
      _preset_options,
      index=_preset_index,
      key="myqima_test_account_preset",
      on_change=_onMyqimaTestAccountPresetChange,
      help="选择预置账号会自动填入下方账号/密码；选「自定义」可手动输入任意账号",
      format_func=_formatMyqimaPresetLabel,
    )
    st.caption(
      f"预置列表来自 `config/myqima_test_accounts.json`（共 {len(_test_account_presets)} 个账号）"
    )
    col1, col2 = st.columns(2)
    with col1:
      _direct_user = st.text_input(
        "myQIMA 账号",
        key="myqima_direct_user",
      )
    with col2:
      _direct_pwd = st.text_input(
        "myQIMA 密码", type="password",
        key="myqima_direct_pwd",
      )
  else:
    col1, col2 = st.columns(2)
    with col1:
      _ppsso_cid_val = st.text_input(
        "Company ID", value=_myqima_cfg.get("companyId", ""),
        key="myqima_ppsso_cid",
      )
    with col2:
      st.text_input(
        "PPSO URL",
        value=_default_ppsso.get("url", ""),
        disabled=True, key="myqima_ppsso_url",
      )
    col1, col2 = st.columns(2)
    with col1:
      _ppsso_user_val = st.text_input(
        "Backoffice 账号", value=_default_ppsso.get("backofficeUsername", ""),
        key="myqima_ppsso_user",
      )
    with col2:
      _ppsso_pwd_val = st.text_input(
        "Backoffice 密码", type="password",
        value=_default_ppsso.get("backofficePassword", ""),
        key="myqima_ppsso_pwd",
      )

  # LOB + Booking 类型
  col1, col2 = st.columns(2)
  with col1:
    _lob = st.selectbox(
      "业务线", list(LOB_BOOKING_TYPES.keys()),
      key="myqima_lob",
    )
  with col2:
    _bt_list = LOB_BOOKING_TYPES[_lob]
    _booking_type = st.selectbox("下单类型", _bt_list, key="myqima_bt")

  # EA / ENVA 子标准
  _ea_variant = None
  _enva_variant = None
  if _booking_type == "EA":
    _ea_variant = st.selectbox(
      "EA 子标准", EA_VARIANTS, key="myqima_ea",
    )
  elif _booking_type == "ENVA":
    _enva_variant = st.selectbox(
      "ENVA Audit Guidelines", ENVA_VARIANTS, key="myqima_enva",
    )

  col1, col2, col3 = st.columns(3)
  with col1:
    _product_count = st.number_input(
      "产品数量", min_value=1, max_value=10, value=1,
      key="myqima_product_count",
    )
  with col2:
    _dry_run = st.checkbox("Dry Run (不提交)", key="myqima_dry_run")
  with col3:
    _myqima_headed = st.checkbox(
      "Headed（显示浏览器）",
      value=True,
      key="myqima_headed",
      help="开启后弹出 Chromium，便于观察卡在哪一步",
    )

  _default_factory = _myqima_cfg.get("factorySection", {})
  _enable_factory_section = False
  _inspection_location_type = "yes"
  _date_certainty_type = "final_date_confirmed"
  _inspection_site_factory_name = _default_factory.get(
    "inspectionSiteFactoryName", "demo-factory",
  )
  if _booking_type in LOB_BOOKING_TYPES["Inspection"]:
    _enable_factory_section = st.checkbox(
      'Enable "factory" section in the booking form',
      value=bool(_default_factory.get("enabled", False)),
      key="myqima_enable_factory_section",
      help="客户配置开启后，选完 Supplier 需处理 Inspection Location",
    )
    if _enable_factory_section:
      _loc_labels = {
        "yes": "Yes — 在 supplier 地址验货",
        "no": "No — 其他地点（需选 Inspection site factory）",
        "to_be_confirmed": "To be confirmed",
      }
      _loc_keys = list(_loc_labels.keys())
      _saved_loc = _default_factory.get("inspectionLocationType", "yes")
      _loc_index = _loc_keys.index(_saved_loc) if _saved_loc in _loc_keys else 0
      _inspection_location_type = st.radio(
        "Will the inspection take place at the supplier's address?",
        _loc_keys,
        index=_loc_index,
        format_func=lambda k: _loc_labels[k],
        key="myqima_inspection_location",
        horizontal=False,
      )
      if _inspection_location_type == "no":
        _inspection_site_factory_name = st.text_input(
          "Inspection site factory 名称（弹窗内匹配）",
          value=_inspection_site_factory_name,
          key="myqima_inspection_site_factory",
          help="例如测试账号下的 demo-factory",
        )
      _date_labels = {
        "final_date_confirmed": "Final Date — Confirmed",
        "tentative_date": "Tentative Date — Please Confirm",
      }
      _date_keys = list(_date_labels.keys())
      _saved_date_certainty = _default_factory.get("dateCertaintyType", "final_date_confirmed")
      _date_index = (
        _date_keys.index(_saved_date_certainty)
        if _saved_date_certainty in _date_keys
        else 0
      )
      _date_certainty_type = st.radio(
        "Is the date confirmed?",
        _date_keys,
        index=_date_index,
        format_func=lambda k: _date_labels[k],
        key="myqima_date_certainty",
        horizontal=False,
      )

  _default_long_text = _myqima_cfg.get("longTextFields", {})
  _long_text_product_name = False
  _long_text_purchase_order = False
  _long_product_name_length = int(
    _default_long_text.get("productNameLength", DEFAULT_LONG_PRODUCT_NAME_CHARS),
  )
  _long_purchase_order_length = int(
    _default_long_text.get("purchaseOrderLength", DEFAULT_LONG_PO_CHARS),
  )
  if _booking_type in LOB_BOOKING_TYPES["Inspection"]:
    with st.expander("长文本字段测试", expanded=False):
      st.caption("开启后自动填入较长 Product name / Purchase Order，便于 maxlength 等 UI 测试。")
      _long_text_product_name = st.checkbox(
        "长文本 Product name",
        value=bool(_default_long_text.get("productName", False)),
        key="myqima_long_product_name",
      )
      if _long_text_product_name:
        _long_product_name_length = st.number_input(
          "Product name 字符数",
          min_value=50,
          max_value=5000,
          value=_long_product_name_length,
          step=50,
          key="myqima_long_product_name_len",
        )
      _long_text_purchase_order = st.checkbox(
        "长文本 Purchase Order (PO)",
        value=bool(_default_long_text.get("purchaseOrder", False)),
        key="myqima_long_po",
      )
      if _long_text_purchase_order:
        _long_purchase_order_length = st.number_input(
          "PO 字符数",
          min_value=50,
          max_value=5000,
          value=_long_purchase_order_length,
          step=50,
          key="myqima_long_po_len",
        )

  # 高级设置
  with st.expander("⚙️ 高级设置"):
    _playwright_path = st.text_input(
      "Playwright 项目路径",
      value=_default_path or "D:\\pythonProject\\playwright",
      key="myqima_playwright_path",
      help="myQIMA booking-flow Playwright 项目的根目录路径",
    )

  st.markdown("---")
  st.subheader("🔄 四业务线回归测试")
  st.caption(
    "对 Inspection / Audit / Qcore / Certis 四条业务线各执行一次下单。"
    "复用上方 myQIMA 账号、产品数量、Dry Run 与 Playwright 路径。"
  )

  _reg_mode = st.radio(
    "下单类型",
    ["随机", "指定"],
    horizontal=True,
    key="myqima_reg_mode",
    help="随机：每条业务线从可选类型中随机选一个；指定：为每条业务线手动选择",
  )

  _reg_specified: dict[str, str] = {}
  if _reg_mode == "指定":
    _reg_cols = st.columns(2)
    for _i, _reg_lob in enumerate(["Inspection", "Audit", "Qcore", "Certis"]):
      with _reg_cols[_i % 2]:
        _reg_specified[_reg_lob] = st.selectbox(
          f"{_reg_lob}",
          LOB_BOOKING_TYPES[_reg_lob],
          key=f"myqima_reg_bt_{_reg_lob}",
        )

  _reg_stop_on_fail = st.checkbox(
    "遇错即停",
    value=False,
    key="myqima_reg_stop_on_fail",
    help="勾选后，任一条业务线失败则不再继续后续业务线",
  )

  _reg_col_run, _reg_col_clear = st.columns(2)
  with _reg_col_run:
    _btn_reg = st.button(
      "🔄 开始回归测试",
      use_container_width=True,
      key="btn_myqima_regression",
      disabled=st.session_state.myqima_regression_running,
    )
  with _reg_col_clear:
    if st.button("🗑️ 清空回归结果", use_container_width=True, key="btn_myqima_reg_clear"):
      st.session_state.myqima_regression_summary = None
      st.rerun()

  if _btn_reg:
    from modules._myqima_booking._regression_logic import build_regression_cases
    from modules._myqima_booking._regression_runner import (
      MyqimaRegressionRunner,
      RegressionCaseResult,
      RegressionRunSummary,
    )
    from modules._myqima_booking._booking_runner import formatBookingLogText

    if _login_method != "myQIMA 账号":
      st.error("回归测试仅支持 myQIMA 账号登录，请切换登录方式")
    elif not _direct_user or not _direct_pwd:
      st.error("请输入 myQIMA 账号和密码")
    elif not _playwright_path:
      st.error("请配置 Playwright 项目路径")
    else:
      if _curr_user:
        try:
          persistMyqimaUserPrefs(
            _cfg_path,
            _curr_user,
            playwrightProjectPath=_playwright_path,
            factorySection=factorySectionDictForStorage(
              _enable_factory_section,
              _inspection_location_type,
              _inspection_site_factory_name,
              _date_certainty_type,
            ),
            longTextFields=longTextFieldsDictForStorage(
              _long_text_product_name,
              _long_text_purchase_order,
              _long_product_name_length,
              _long_purchase_order_length,
            ),
          )
        except Exception as _reg_save_ex:
          logging.warning("保存 myQIMA factory 配置失败: %s", _reg_save_ex)

      st.session_state.myqima_regression_running = True
      try:
        _reg_mode_key = "random" if _reg_mode == "随机" else "specified"
        _cases = build_regression_cases(
          mode=_reg_mode_key,
          specified=_reg_specified if _reg_mode_key == "specified" else None,
        )

        _base_cfg = BookingConfig(
          login_type="myqima",
          booking_type="PSI",
          product_count=_product_count,
          dry_run=_dry_run,
          direct_username=_direct_user,
          direct_password=_direct_pwd,
          enable_factory_section=_enable_factory_section,
          inspection_location_type=_inspection_location_type,
          inspection_site_factory_name=_inspection_site_factory_name,
          date_certainty_type=_date_certainty_type,
          long_text_product_name=_long_text_product_name,
          long_text_purchase_order=_long_text_purchase_order,
          long_product_name_length=_long_product_name_length,
          long_purchase_order_length=_long_purchase_order_length,
        )

        _reg_runner = MyqimaRegressionRunner(_playwright_path)
        _reg_log_box = st.empty()
        _reg_log_lines: list[str] = []
        _reg_summary = None

        with st.spinner("正在执行四业务线回归测试..."):
          for _evt in _reg_runner.stream(
            _cases,
            _base_cfg,
            stop_on_fail=_reg_stop_on_fail,
            headed=_myqima_headed,
          ):
            if isinstance(_evt, str):
              _reg_log_lines.append(_evt)
              _reg_log_box.code(formatBookingLogText(_reg_log_lines, 120), language="text")
            elif isinstance(_evt, RegressionCaseResult):
              _reg_log_lines.append(
                f"--- {_evt.case.lob}/{_evt.case.booking_type}: "
                f"{'PASS' if _evt.result.success else 'FAIL'} ---"
              )
            elif isinstance(_evt, RegressionRunSummary):
              _reg_summary = _evt

        st.session_state.myqima_regression_summary = {
          "summary": _reg_summary,
          "logs": _reg_log_lines,
          "cases_plan": [
            {"lob": c.lob, "booking_type": c.booking_type} for c in _cases
          ],
        }
      except Exception as _reg_ex:
        st.error(f"回归测试异常: {_reg_ex}")
      finally:
        st.session_state.myqima_regression_running = False
        st.rerun()

  _prev = st.session_state.myqima_regression_summary
  if _prev and _prev.get("summary"):
    _s = _prev["summary"]
    st.markdown("#### 📊 回归结果汇总")
    _m1, _m2, _m3 = st.columns(3)
    _m1.metric("通过", f"{_s.passed_count}/{len(_s.case_results)}")
    _m2.metric("失败", _s.failed_count)
    _m3.metric("耗时", f"{_s.duration_seconds:.1f}s")

    _rows = []
    for _cr in _s.case_results:
      _rows.append({
        "业务线": _cr.case.lob,
        "下单类型": _cr.case.booking_type,
        "状态": "✅" if _cr.result.success else "❌",
        "Order ID": _cr.result.order_id or "-",
        "QIMA Ref": _cr.result.qima_ref or "-",
        "错误": _cr.result.error or "-",
      })
    st.dataframe(_rows, use_container_width=True, hide_index=True)

    with st.expander("📋 回归日志"):
      from modules._myqima_booking._booking_runner import formatBookingLogText
      st.code(formatBookingLogText(_prev.get("logs", []), 200), language="text")

  if st.button("▶️ 开始下单", use_container_width=True, key="btn_myqima"):
    from modules._myqima_booking._booking_runner import BookingRunner

    _errors = []
    if _login_method == "myQIMA 账号":
      if not _direct_user or not _direct_pwd:
        _errors.append("请输入 myQIMA 账号和密码")
      _login_type = "myqima"
    else:
      if not _ppsso_cid_val:
        _errors.append("请输入 Company ID")
      if not _ppsso_user_val or not _ppsso_pwd_val:
        _errors.append("请输入 Backoffice 账号和密码")
      _login_type = "ppsso"

    if _errors:
      for _e in _errors:
        st.error(_e)
    else:
      if _curr_user and _playwright_path:
        try:
          _factory_to_save = None
          if _booking_type in LOB_BOOKING_TYPES["Inspection"]:
            _factory_to_save = factorySectionDictForStorage(
              _enable_factory_section,
              _inspection_location_type,
              _inspection_site_factory_name,
              _date_certainty_type,
            )
          persistMyqimaUserPrefs(
            _cfg_path,
            _curr_user,
            playwrightProjectPath=_playwright_path,
            factorySection=_factory_to_save,
            longTextFields=longTextFieldsDictForStorage(
              _long_text_product_name,
              _long_text_purchase_order,
              _long_product_name_length,
              _long_purchase_order_length,
            ),
          )
        except Exception as _ex:
          logging.warning("保存 myQIMA 配置失败: %s", _ex)

      _ppsso_url = ""
      if _login_type == "ppsso":
        _ppsso_url = _default_ppsso.get("url", "") or build_ppsso_url(_ppsso_cid_val)

      _config = BookingConfig(
        login_type=_login_type,
        booking_type=_booking_type,
        product_count=_product_count,
        dry_run=_dry_run,
        direct_username=_direct_user if _login_method == "myQIMA 账号" else "",
        direct_password=_direct_pwd if _login_method == "myQIMA 账号" else "",
        company_id=_ppsso_cid_val if _login_method != "myQIMA 账号" else "",
        ppsso_url=_ppsso_url,
        ppsso_username=_ppsso_user_val if _login_method != "myQIMA 账号" else "",
        ppsso_password=_ppsso_pwd_val if _login_method != "myQIMA 账号" else "",
        ea_variant=_ea_variant,
        enva_variant=_enva_variant,
        enable_factory_section=_enable_factory_section,
        inspection_location_type=_inspection_location_type,
        inspection_site_factory_name=_inspection_site_factory_name,
        date_certainty_type=_date_certainty_type,
        long_text_product_name=_long_text_product_name,
        long_text_purchase_order=_long_text_purchase_order,
        long_product_name_length=_long_product_name_length,
        long_purchase_order_length=_long_purchase_order_length,
      )

      if _enable_factory_section and _inspection_location_type == "no":
        if not (_inspection_site_factory_name or "").strip():
          st.error("选择 No 时请填写 Inspection site factory 名称")
          st.stop()

      _log_box = st.empty()
      _log_lines = []
      _run_result = None

      try:
        _runner = BookingRunner(_playwright_path)
        for _item in _runner.stream(_config.to_dict(), headed=_myqima_headed):
          if isinstance(_item, str):
            _log_lines.append(_item)
            _log_box.code(formatBookingLogText(_log_lines, 120), language="text")
          else:
            _run_result = _item

        _log_box.code(formatBookingLogText(_log_lines, 150), language="text")

        if _run_result and _run_result.success:
          st.success("✅ 下单流程执行完成")
          if _run_result.order_id:
            col_a, col_b, col_c, _ = st.columns(4)
            with col_a:
              st.metric("Order ID", _run_result.order_id)
            with col_b:
              st.metric("QIMA Ref", _run_result.qima_ref)
            with col_c:
              st.metric("Total Amount", _run_result.total_amount if _run_result.total_amount else "N/A")
          with st.expander("📋 完整日志"):
            st.code(formatBookingLogText(_log_lines, 5000), language="text")
        elif _run_result:
          st.error(f"❌ 执行失败: {_run_result.error}")
          with st.expander("📋 错误日志"):
            st.code(formatBookingLogText(_log_lines, 80), language="text")
      except Exception as _ex:
        st.error(f"❌ 执行异常: {_ex}")
        if _log_lines:
          with st.expander("📋 日志"):
            st.code(formatBookingLogText(_log_lines, 5000), language="text")


_LIFE_SCIENCE_SPECS: list[tuple[str, str]] = [
  ("tests/life-science-flow/study-chain.spec.ts", "Study CRU 链 (study-chain)"),
  (
    "tests/life-science-flow/journey/journey-a-smoke-create.spec.ts",
    "Journey A — Smoke & Create",
  ),
  (
    "tests/life-science-flow/journey/journey-b-list-detail.spec.ts",
    "Journey B — List & Detail",
  ),
  (
    "tests/life-science-flow/journey/journey-c-status-reports.spec.ts",
    "Journey C — Status & Reports",
  ),
  (
    "tests/life-science-flow/journey/journey-d-audit-myqima.spec.ts",
    "Journey D — Audit myQIMA",
  ),
  (
    "tests/life-science-flow/journey/journey-e-report-deliverables.spec.ts",
    "Journey E — Report Deliverables",
  ),
]

_QIMAONE_SCENARIOS: list[tuple[str, str]] = [
  ("v1-psi-order", "V1 — PSI 单产品"),
  ("v2-aql-per-inspection", "V2 — AQL per inspection"),
  ("v3-aql-per-product", "V3 — AQL per product"),
  ("textile-measurement", "Textile measurement"),
]


def _playwright_path_from_user_config() -> tuple[str, str, str]:
  """Return (cfg_path, current_user, default_playwright_path)."""
  curr = st.session_state.get("current_user") or ""
  cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "users_config.json")
  default_path = ""
  if curr:
    try:
      with open(cfg_path, encoding="utf-8") as fh:
        all_cfg = json.load(fh)
      default_path = (
        all_cfg.get("users", {}).get(curr, {}).get("myqima", {}).get(
          "playwright_project_path", ""
        )
        or ""
      )
    except Exception:
      pass
  try:
    default_path = str(resolvePlaywrightProjectPath(default_path or None))
  except FileNotFoundError:
    if not default_path:
      default_path = ""
  return cfg_path, curr, default_path


# ── 10b. Life Science Flow ──
with st.expander("🧬 Life Science Flow (Playwright)", expanded=False):
  st.markdown(
    "运行 `playwright/tests/life-science-flow` 下的 E2E（Auth2 登录与 Study 流程）。"
    "需在本机配置好 Playwright 项目与环境变量。"
  )
  _ls_cfg_path, _ls_user, _ls_default_path = _playwright_path_from_user_config()
  _ls_path = st.text_input(
    "Playwright 项目路径",
    value=_ls_default_path,
    key="ls_playwright_path",
  )
  _ls_spec_labels = [label for _, label in _LIFE_SCIENCE_SPECS]
  _ls_spec_map = {label: rel for rel, label in _LIFE_SCIENCE_SPECS}
  _ls_choice = st.selectbox("测试入口", _ls_spec_labels, key="ls_spec_choice")
  _ls_spec = _ls_spec_map[_ls_choice]
  _ls_headed = st.checkbox("Headed（显示浏览器）", value=True, key="ls_headed")
  _ls_timeout = st.number_input(
    "超时（秒）", min_value=300, max_value=7200, value=3600, step=60, key="ls_timeout",
  )

  if st.button("▶️ 运行 Life Science", use_container_width=True, key="btn_life_science_run"):
    if not (_ls_path or "").strip():
      st.error("请填写 Playwright 项目路径")
    else:
      if _ls_user:
        try:
          persistMyqimaUserPrefs(_ls_cfg_path, _ls_user, playwrightProjectPath=_ls_path.strip())
        except Exception as _ls_save_ex:
          logging.warning("保存 Playwright 路径失败: %s", _ls_save_ex)
      _ls_log_box = st.empty()
      _ls_log_lines: list[str] = []
      _ls_result = None
      try:
        _ls_runner = PlaywrightFlowRunner(_ls_path.strip())
        with st.spinner(f"正在运行 {_ls_choice}..."):
          for _ls_item in _ls_runner.stream(
            _ls_spec, headed=_ls_headed, timeout=int(_ls_timeout),
          ):
            if isinstance(_ls_item, str):
              _ls_log_lines.append(_ls_item)
              _ls_log_box.code(formatBookingLogText(_ls_log_lines, 120), language="text")
            else:
              _ls_result = _ls_item
        _ls_log_box.code(formatBookingLogText(_ls_log_lines, 150), language="text")
        if _ls_result and _ls_result.success:
          st.success("✅ Life Science 测试通过")
        elif _ls_result:
          st.error(f"❌ 执行失败: {_ls_result.error or '见日志'}")
      except Exception as _ls_ex:
        st.error(f"❌ 执行异常: {_ls_ex}")
        if _ls_log_lines:
          st.code(formatBookingLogText(_ls_log_lines, 80), language="text")


# ── 10c. QIMAone Report Flow ──
with st.expander("📋 QIMAone Report Flow (Playwright)", expanded=False):
  st.markdown(
    "运行 `playwright/tests/qimaone-report-flow/scenario-chain.spec.ts`"
    "（Phase 1–5 全流程，由 SCENARIO 环境变量选择场景）。"
  )
  _qo_cfg_path, _qo_user, _qo_default_path = _playwright_path_from_user_config()
  _qo_path = st.text_input(
    "Playwright 项目路径",
    value=_qo_default_path,
    key="qo_playwright_path",
  )
  _qo_scenario_labels = [label for _, label in _QIMAONE_SCENARIOS]
  _qo_scenario_map = {label: sid for sid, label in _QIMAONE_SCENARIOS}
  _qo_choice = st.selectbox("场景 (SCENARIO)", _qo_scenario_labels, key="qo_scenario")
  _qo_scenario_id = _qo_scenario_map[_qo_choice]
  _qo_headed = st.checkbox("Headed（显示浏览器）", value=True, key="qo_headed")
  _qo_timeout = st.number_input(
    "超时（秒）", min_value=600, max_value=7200, value=1800, step=60, key="qo_timeout",
  )

  if st.button("▶️ 运行 QIMAone 场景链", use_container_width=True, key="btn_qimaone_run"):
    if not (_qo_path or "").strip():
      st.error("请填写 Playwright 项目路径")
    else:
      if _qo_user:
        try:
          persistMyqimaUserPrefs(_qo_cfg_path, _qo_user, playwrightProjectPath=_qo_path.strip())
        except Exception as _qo_save_ex:
          logging.warning("保存 Playwright 路径失败: %s", _qo_save_ex)
      _qo_log_box = st.empty()
      _qo_log_lines: list[str] = []
      _qo_result = None
      try:
        _qo_runner = PlaywrightFlowRunner(_qo_path.strip())
        _qo_spec = "tests/qimaone-report-flow/scenario-chain.spec.ts"
        with st.spinner(f"正在运行场景 {_qo_scenario_id}..."):
          for _qo_item in _qo_runner.stream(
            _qo_spec,
            env_extra={"SCENARIO": _qo_scenario_id},
            headed=_qo_headed,
            timeout=int(_qo_timeout),
          ):
            if isinstance(_qo_item, str):
              _qo_log_lines.append(_qo_item)
              _qo_log_box.code(formatBookingLogText(_qo_log_lines, 120), language="text")
            else:
              _qo_result = _qo_item
        _qo_log_box.code(formatBookingLogText(_qo_log_lines, 150), language="text")
        if _qo_result and _qo_result.success:
          st.success("✅ QIMAone 场景链执行通过")
        elif _qo_result:
          st.error(f"❌ 执行失败: {_qo_result.error or '见日志'}")
      except Exception as _qo_ex:
        st.error(f"❌ 执行异常: {_qo_ex}")
        if _qo_log_lines:
          st.code(formatBookingLogText(_qo_log_lines, 80), language="text")


# ── Cypress 周跑 ──
with st.expander("🌲 Cypress 周跑 (myQIMA)", expanded=False):
  st.markdown(
    "后台运行 Cypress `my-qima` 用例，日志写入 `results/cypress_weekly/`。"
    "切换 Streamlit 页面不会中断进程；说明见 `docs/cypress-weekly-runner.md`。"
  )
  st.caption(
    "开启 Xray 集成时，启动前会从当前用户的 config/users_config.json（xray.client_id / "
    "client_secret）或环境变量 XRAY_CLIENT_ID / XRAY_CLIENT_SECRET 写入 cypress.env.json，"
    "界面不显示密钥。"
  )
  _cy_state_dir = defaultCypressStateDir()
  _cy_prefs = loadCypressWeeklyPrefs(_cy_state_dir)

  _cy_project_default = str(_cy_prefs.get("projectPath", "") or "")
  _cy_spec_default = str(_cy_prefs.get("spec", "") or DEFAULT_SPEC)
  _cy_browser_default = str(_cy_prefs.get("browser", "chrome") or "chrome")
  if _cy_browser_default not in ALLOWED_BROWSERS:
    _cy_browser_default = "chrome"
  _cy_headless_default = bool(_cy_prefs.get("headless", True))

  def _applyCypressEnvToWidgets(env: dict[str, object]) -> None:
    st.session_state.cypress_weekly_xray = bool(
      env.get("xray_jira_integration_enabled", False)
    )
    st.session_state.cypress_weekly_te_key = str(
      env.get("test_execution_key", "") or ""
    )
    st.session_state.cypress_weekly_sprint = int(env.get("sprint", 1) or 1)
    st.session_state.cypress_weekly_week = int(env.get("week", 1) or 1)

  if "cypress_weekly_project_path" not in st.session_state:
    st.session_state.cypress_weekly_project_path = _cy_project_default
  if "cypress_weekly_spec" not in st.session_state:
    st.session_state.cypress_weekly_spec = _cy_spec_default
  if "cypress_weekly_browser" not in st.session_state:
    st.session_state.cypress_weekly_browser = _cy_browser_default
  if "cypress_weekly_headless" not in st.session_state:
    st.session_state.cypress_weekly_headless = _cy_headless_default
  if "cy_env_cache_path" not in st.session_state:
    st.session_state.cy_env_cache_path = ""

  _cy_path_for_env = str(st.session_state.cypress_weekly_project_path or "").strip()
  if _cy_path_for_env and st.session_state.cy_env_cache_path != _cy_path_for_env:
    try:
      _applyCypressEnvToWidgets(readEditableCypressEnv(_cy_path_for_env))
      st.session_state.cy_env_cache_path = _cy_path_for_env
    except CypressWeeklyError:
      st.session_state.cy_env_cache_path = _cy_path_for_env

  if "cypress_weekly_xray" not in st.session_state:
    _applyCypressEnvToWidgets({
      "xray_jira_integration_enabled": False,
      "test_execution_key": "",
      "sprint": 1,
      "week": 1,
    })

  _cy_project = st.text_input(
    "Cypress 项目路径",
    key="cypress_weekly_project_path",
    help="含 cypress.env.json 的 Cypress 项目根目录（首次使用必填，会记住上次路径）",
  )
  _cy_spec = st.text_input("Spec 通配", key="cypress_weekly_spec")
  _cy_browser = st.selectbox(
    "浏览器",
    options=list(ALLOWED_BROWSERS),
    key="cypress_weekly_browser",
  )
  _cy_headless = st.checkbox("Headless", key="cypress_weekly_headless")

  if st.button("从 cypress.env.json 重新读取", key="cypress_weekly_reload_env"):
    try:
      _cy_env = readEditableCypressEnv(_cy_project.strip())
      st.session_state.cy_env_cache_path = _cy_project.strip()
      _applyCypressEnvToWidgets(_cy_env)
      st.success("已读取 cypress.env.json（未改动密钥字段）")
      st.rerun()
    except CypressWeeklyError as _cy_env_ex:
      st.error(str(_cy_env_ex))

  _cy_xray = st.checkbox("Xray Jira 集成", key="cypress_weekly_xray")
  _cy_te_key = st.text_input(
    "Test Execution Key",
    key="cypress_weekly_te_key",
    placeholder="例如 SP-37670",
  )
  _cy_sprint = st.number_input(
    "Sprint",
    min_value=1,
    step=1,
    key="cypress_weekly_sprint",
  )
  _cy_week = st.number_input(
    "Week",
    min_value=1,
    max_value=53,
    step=1,
    key="cypress_weekly_week",
  )

  _cy_btn_start, _cy_btn_stop, _cy_btn_refresh = st.columns(3)
  with _cy_btn_start:
    _cy_start = st.button("▶ 启动周跑", key="cypress_weekly_start", type="primary")
  with _cy_btn_stop:
    _cy_stop = st.button("⏹ 停止", key="cypress_weekly_stop")
  with _cy_btn_refresh:
    _cy_refresh = st.button("🔄 刷新状态", key="cypress_weekly_refresh")

  if _cy_start:
    try:
      _cy_start_path = _cy_project.strip()
      if not _cy_start_path:
        raise CypressWeeklyError("请填写 Cypress 项目路径")
      _cy_xray_start = _cy_xray
      _cy_te_start = _cy_te_key.strip()
      _cy_sprint_start = int(_cy_sprint)
      _cy_week_start = int(_cy_week)
      if _cy_start_path != st.session_state.get("cy_env_cache_path", ""):
        _cy_env_start = readEditableCypressEnv(_cy_start_path)
        _cy_xray_start = bool(_cy_env_start.get("xray_jira_integration_enabled", False))
        _cy_te_start = str(_cy_env_start.get("test_execution_key", "") or "").strip()
        _cy_sprint_start = int(_cy_env_start.get("sprint", 1) or 1)
        _cy_week_start = int(_cy_env_start.get("week", 1) or 1)
        st.session_state.cy_env_cache_path = _cy_start_path
        _applyCypressEnvToWidgets(_cy_env_start)
      startCypressWeeklyRun(
        projectPath=_cy_start_path,
        spec=_cy_spec.strip(),
        browser=_cy_browser,
        headless=_cy_headless,
        xrayEnabled=_cy_xray_start,
        testExecutionKey=_cy_te_start,
        sprint=_cy_sprint_start,
        week=_cy_week_start,
        stateDir=_cy_state_dir,
        configUsername=st.session_state.get("current_user"),
      )
      st.success("Cypress 已在后台启动")
      st.rerun()
    except CypressWeeklyError as _cy_start_ex:
      st.error(str(_cy_start_ex))

  if _cy_stop:
    stopCypressWeeklyRun(_cy_state_dir)
    st.info("已发送停止信号")
    st.rerun()

  if _cy_refresh:
    refreshCypressWeeklyRun(_cy_state_dir)
    st.rerun()

  _cy_run = refreshCypressWeeklyRun(_cy_state_dir)
  if _cy_run:
    _cy_status = _cy_run.state
    if _cy_status == "running":
      st.warning(f"运行中 — PID {_cy_run.pid}，开始于 {_cy_run.startedAt}")
      st.caption("运行中请点「刷新状态」以更新汇总与日志。")
    elif _cy_status == "finished":
      st.success(
        f"已完成 — exit {_cy_run.exitCode}，{_cy_run.summary or '见日志'}"
      )
    elif _cy_status == "failed":
      st.error(
        f"失败 — exit {_cy_run.exitCode}，{_cy_run.summary or '见日志'}"
      )
    elif _cy_status == "stopped":
      st.info(f"已停止 — PID {_cy_run.pid}")
    st.caption(
      f"命令: {_cy_run.command} | spec: {_cy_run.spec} | browser: {_cy_run.browser}"
    )
  else:
    st.caption("当前无后台任务")

  _cy_log = readCypressWeeklyLog(_cy_state_dir, maxLines=200)
  if _cy_log.strip():
    st.markdown("**日志（末尾 200 行，已脱敏）**")
    st.code(_cy_log, language="text")


# ── 页脚 ──
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666;">
  <p>🧪 Test Tools v1.0 | 全部工具在本地运行</p>
</div>
""", unsafe_allow_html=True)
