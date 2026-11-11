"""Tests for myQIMA booking config builder."""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock


from modules._myqima_booking._config_builder import (
  BookingConfig,
  MYQIMA_PRESET_CUSTOM_LABEL,
  applyMyqimaTestAccountPreset,
  build_ppsso_url,
  loadMyqimaTestAccountPresets,
  myqimaTestAccountPresetOptions,
  resolveMyqimaPresetLabelForUsername,
  LOB_BOOKING_TYPES,
  BookingType,
)
from modules._myqima_booking._booking_runner import (
  parse_log_line,
  BookingResult,
  BookingRunner,
  playwrightOutputIndicatesRunFinished,
  sanitizeStdoutLine,
  formatBookingLogText,
)


def test_build_ppsso_url():
  url = build_ppsso_url("74CA94F460EC470499DCDADC7CB7C001")
  assert url == "https://ppsso.example.com/back-office/v2/company-profile/customer/74CA94F460EC470499DCDADC7CB7C001"


def test_load_myqima_test_account_presets_from_repo_file():
  presets = loadMyqimaTestAccountPresets()
  assert len(presets) >= 1
  labels = {p["label"] for p in presets}
  assert "test_qa" in labels


def test_myqima_test_account_preset_helpers():
  presets = [
    {"label": "a", "username": "user_a", "password": "pass_a"},
  ]
  assert myqimaTestAccountPresetOptions(presets)[0] == MYQIMA_PRESET_CUSTOM_LABEL
  assert resolveMyqimaPresetLabelForUsername(presets, "user_a") == "a"
  assert resolveMyqimaPresetLabelForUsername(presets, "other") == MYQIMA_PRESET_CUSTOM_LABEL

  class _FakeState(dict):
    pass

  state = _FakeState(myqima_direct_user="", myqima_direct_pwd="")
  applyMyqimaTestAccountPreset("a", presets, state)
  assert state["myqima_direct_user"] == "user_a"
  assert state["myqima_direct_pwd"] == "pass_a"
  applyMyqimaTestAccountPreset(MYQIMA_PRESET_CUSTOM_LABEL, presets, state)
  assert state["myqima_direct_user"] == "user_a"


def test_config_builder_myqima():
  config = BookingConfig(
      login_type="myqima",
      booking_type="PSI",
      product_count=2,
      direct_username="test_user",
      direct_password="test_pass",
  )
  d = config.to_dict()
  assert d["loginType"] == "myqima"
  assert d["bookingType"] == "PSI"
  assert d["productCount"] == 2
  assert d["dryRun"] is False
  assert d["directAccount"]["username"] == "test_user"
  assert d["directAccount"]["password"] == "test_pass"


def test_config_builder_ppsso():
  config = BookingConfig(
      login_type="ppsso",
      booking_type="EA",
      company_id="TESTCID123",
      ppsso_username="back_user",
      ppsso_password="back_pass",
  )
  d = config.to_dict()
  assert d["loginType"] == "ppsso"
  assert d["bookingType"] == "EA"
  assert d["companyId"] == "TESTCID123"
  assert d["ppssoBackdoor"]["backofficeUsername"] == "back_user"
  assert d["ppssoBackdoor"]["backofficePassword"] == "back_pass"
  assert "ppsso.example.com" in d["ppssoBackdoor"]["url"]


def test_config_builder_dry_run():
  config = BookingConfig(
      login_type="myqima", booking_type="PSI",
      dry_run=True,
  )
  assert config.to_dict()["dryRun"] is True


def test_config_builder_ea_variant():
  config = BookingConfig(
      login_type="myqima", booking_type="EA",
      ea_variant="SMETA",
  )
  assert config.to_dict()["eaVariant"] == "SMETA"


def test_config_builder_enva_variant():
  config = BookingConfig(
      login_type="myqima", booking_type="ENVA",
      enva_variant="HIGG_FEM",
  )
  assert config.to_dict()["envaVariant"] == "HIGG_FEM"


def test_config_builder_factory_section_psi():
  config = BookingConfig(
    login_type="myqima",
    booking_type="PSI",
    enable_factory_section=True,
    inspection_location_type="no",
    inspection_site_factory_name="demo-factory",
  )
  d = config.to_dict()
  assert d["factorySection"]["enabled"] is True
  assert d["factorySection"]["inspectionLocationType"] == "no"
  assert d["factorySection"]["inspectionSiteFactoryName"] == "demo-factory"
  assert d["factorySection"]["dateCertaintyType"] == "final_date_confirmed"


def test_config_builder_factory_section_date_certainty_tentative():
  config = BookingConfig(
    login_type="myqima",
    booking_type="PSI",
    enable_factory_section=True,
    inspection_location_type="yes",
    date_certainty_type="tentative_date",
  )
  assert config.to_dict()["factorySection"]["dateCertaintyType"] == "tentative_date"


def test_persist_myqima_user_prefs_factory_section():
  import tempfile
  from modules._myqima_booking._config_builder import (
    persistMyqimaUserPrefs,
    factorySectionDictForStorage,
  )

  with tempfile.TemporaryDirectory() as tmp:
    cfg_path = os.path.join(tmp, "users_config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
      json.dump({"users": {"Daisy": {"myqima": {}}}}, fh)

    persistMyqimaUserPrefs(
      cfg_path,
      "Daisy",
      playwrightProjectPath="C:\\playwright",
      factorySection=factorySectionDictForStorage(True, "no", "demo-factory"),
    )

    with open(cfg_path, encoding="utf-8") as fh:
      data = json.load(fh)
    myqima = data["users"]["Daisy"]["myqima"]
    assert myqima["playwright_project_path"] == "C:\\playwright"
    assert myqima["factorySection"]["enabled"] is True
    assert myqima["factorySection"]["inspectionLocationType"] == "no"
    assert myqima["factorySection"]["inspectionSiteFactoryName"] == "demo-factory"
    assert myqima["factorySection"]["dateCertaintyType"] == "final_date_confirmed"


def test_config_builder_factory_section_for_inspection_clc():
  config = BookingConfig(
    login_type="myqima",
    booking_type="CLC",
    enable_factory_section=True,
    inspection_location_type="yes",
  )
  assert config.to_dict()["factorySection"]["enabled"] is True


def test_config_builder_factory_section_ignored_for_audit():
  config = BookingConfig(
    login_type="myqima",
    booking_type="EA",
    enable_factory_section=True,
    inspection_location_type="yes",
  )
  assert "factorySection" not in config.to_dict()


def test_config_builder_long_text_fields_inspection():
  config = BookingConfig(
    login_type="myqima",
    booking_type="PSI",
    long_text_product_name=True,
    long_text_purchase_order=True,
    long_product_name_length=1200,
    long_purchase_order_length=600,
  )
  lt = config.to_dict()["longTextFields"]
  assert lt["productName"] is True
  assert lt["productNameLength"] == 1200
  assert lt["purchaseOrder"] is True
  assert lt["purchaseOrderLength"] == 600


def test_config_builder_long_text_fields_ignored_for_audit():
  config = BookingConfig(
    login_type="myqima",
    booking_type="EA",
    long_text_product_name=True,
  )
  assert "longTextFields" not in config.to_dict()


def test_persist_myqima_user_prefs_long_text_fields():
  import tempfile
  from modules._myqima_booking._config_builder import (
    persistMyqimaUserPrefs,
    longTextFieldsDictForStorage,
  )

  with tempfile.TemporaryDirectory() as tmp:
    cfg_path = os.path.join(tmp, "users_config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
      json.dump({"users": {"Daisy": {"myqima": {}}}}, fh)

    persistMyqimaUserPrefs(
      cfg_path,
      "Daisy",
      longTextFields=longTextFieldsDictForStorage(True, False, 400, 200),
    )

    with open(cfg_path, encoding="utf-8") as fh:
      data = json.load(fh)
    lt = data["users"]["Daisy"]["myqima"]["longTextFields"]
    assert lt["productName"] is True
    assert lt["purchaseOrder"] is False
    assert lt["productNameLength"] == 400


def test_lob_booking_types_structure():
  assert "Inspection" in LOB_BOOKING_TYPES
  assert "Audit" in LOB_BOOKING_TYPES
  assert "Qcore" in LOB_BOOKING_TYPES
  assert "Certis" in LOB_BOOKING_TYPES
  assert "PSI" in LOB_BOOKING_TYPES["Inspection"]
  assert "EA" in LOB_BOOKING_TYPES["Audit"]
  assert "SABER" in LOB_BOOKING_TYPES["Certis"]


def test_ea_variants():
  from modules._myqima_booking._config_builder import EA_VARIANTS
  assert "QIMA_ETHICAL" in EA_VARIANTS
  assert "BSCI" in EA_VARIANTS


def test_enva_variants():
  from modules._myqima_booking._config_builder import ENVA_VARIANTS
  assert "QIMA" in ENVA_VARIANTS
  assert "HIGG_FEM" in ENVA_VARIANTS


def test_booking_type_enum_values():
  assert BookingType("PSI") == "PSI"
  assert BookingType("EA") == "EA"




def test_sanitize_stdout_line_filters_blanks():
  assert sanitizeStdoutLine("  \r\n") is None
  assert sanitizeStdoutLine("\x1b[31m[17:31:54] ok\x1b[0m") == "[17:31:54] ok"


def test_format_booking_log_text_skips_empty_rows():
  text = formatBookingLogText(["line1", "", "  ", "line2"], tail=10)
  assert text == "line1\nline2"


def test_playwright_output_indicates_run_finished():
  assert playwrightOutputIndicatesRunFinished("  1 passed (1.7m)")
  assert playwrightOutputIndicatesRunFinished("[16:56:26] 下单完成，共 1 个产品")
  assert not playwrightOutputIndicatesRunFinished("[16:56:26] 登录 — 开始")


def test_parse_log_line_order_id():
  result = BookingResult()
  parse_log_line("[12:30:01] Order ID: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", result)
  assert result.order_id == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def test_parse_log_line_qima_ref():
  result = BookingResult()
  parse_log_line("[12:30:01] QIMA Ref: Q2026061201-AB", result)
  assert result.qima_ref == "Q2026061201-AB"


def test_parse_log_line_both():
  result = BookingResult()
  parse_log_line("[12:30:01] Order ID: abc123def456abc123def456abc123de", result)
  assert result.order_id == "abc123def456abc123def456abc123de"
  parse_log_line("[12:30:02] QIMA Ref: Q2026061201-XY", result)
  assert result.qima_ref == "Q2026061201-XY"


def test_parse_log_line_no_match():
  result = BookingResult()
  parse_log_line("[12:30:01] Login successful", result)
  assert result.order_id == ""
  assert result.qima_ref == ""


def test_booking_result_defaults():
  r = BookingResult()
  assert r.order_id == ""
  assert r.qima_ref == ""
  assert r.success is False
  assert r.error == ""
  assert r.logs == []


def test_runner_path_not_exists():
  runner = BookingRunner(r"D:\nonexistent_path_xyz")
  result = runner.run({"bookingType": "PSI"})
  assert result.success is False
  assert "不存在" in result.error


def test_runner_stream_yields_lines_then_result():
  with tempfile.TemporaryDirectory() as tmpdir:
    with patch("modules._myqima_booking._booking_runner.shutil.which", return_value="npx.cmd"):
      with patch("modules._myqima_booking._booking_runner.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = [
          "[12:30:01] Login successful\n",
          "[12:30:02] Booking completed\n",
          "[12:30:03] Order ID: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6\n",
          "[12:30:04] QIMA Ref: Q2026061201-AB\n",
          "",
        ]
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        runner = BookingRunner(tmpdir)
        items = list(runner.stream({"bookingType": "PSI"}))
        log_lines = [i for i in items if isinstance(i, str)]
        result = [i for i in items if isinstance(i, BookingResult)][0]

        assert len(log_lines) == 4
        assert "Login successful" in log_lines[0]
        assert "Order ID" in log_lines[2]
        assert result.success is True
        assert result.order_id == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        assert result.qima_ref == "Q2026061201-AB"
