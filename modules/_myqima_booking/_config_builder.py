from pathlib import Path
from typing import Literal, Optional
import json

BookingType = str

InspectionLocationType = Literal["yes", "no", "to_be_confirmed"]
DateCertaintyType = Literal["final_date_confirmed", "tentative_date"]

LOB_BOOKING_TYPES: dict[str, list[str]] = {
  "Inspection": ["PSI", "PEO", "CLC", "DUPRO", "SC", "PM", "IPC", "SR"],
  "Audit": ["EA", "MA", "DR", "CTPAT", "STRA", "ENVA"],
  "Qcore": ["STS", "WCP", "SAQ"],
  "Certis": ["SABER", "GMARK", "SASO"],
}

EA_VARIANTS = ["QIMA_ETHICAL", "SMETA", "ICS", "BSCI", "RJC", "HIGG_FSLM"]
ENVA_VARIANTS = ["QIMA", "ICS", "HIGG_FEM", "BEPI", "CUSTOMIZED", "MR", "FI"]

PPSSO_BASE_URL = "https://ppsso.example.com/back-office/v2/company-profile/customer"

DEFAULT_LONG_PRODUCT_NAME_CHARS = 400
DEFAULT_LONG_PO_CHARS = 200

MYQIMA_PRESET_CUSTOM_LABEL = "自定义（手动输入）"


def defaultMyqimaTestAccountsPath() -> Path:
  """Path to config/myqima_test_accounts.json (repo-relative presets)."""
  return Path(__file__).resolve().parents[2] / "config" / "myqima_test_accounts.json"


def loadMyqimaTestAccountPresets(cfgPath: Optional[str | Path] = None) -> list[dict]:
  """
  Load preset myQIMA test accounts for the booking UI dropdown.

  Each item has label, username, password; note is optional.
  """
  path = Path(cfgPath) if cfgPath else defaultMyqimaTestAccountsPath()
  if not path.is_file():
    return []
  try:
    with open(path, encoding="utf-8") as fh:
      raw = json.load(fh)
  except (OSError, json.JSONDecodeError):
    return []
  accounts = raw.get("accounts") if isinstance(raw, dict) else None
  if not isinstance(accounts, list):
    return []
  out: list[dict] = []
  for item in accounts:
    if not isinstance(item, dict):
      continue
    label = str(item.get("label", "") or "").strip()
    username = str(item.get("username", "") or "").strip()
    password = str(item.get("password", "") or "")
    if not label or not username:
      continue
    entry = {"label": label, "username": username, "password": password}
    note = str(item.get("note", "") or "").strip()
    if note:
      entry["note"] = note
    out.append(entry)
  return out


def myqimaTestAccountPresetOptions(presets: list[dict]) -> list[str]:
  """Dropdown options: custom entry first, then preset labels."""
  labels = [p["label"] for p in presets if p.get("label")]
  return [MYQIMA_PRESET_CUSTOM_LABEL] + labels


def resolveMyqimaPresetLabelForUsername(
  presets: list[dict],
  username: str,
) -> str:
  """Match saved username to a preset label, else custom."""
  u = (username or "").strip()
  if not u:
    return MYQIMA_PRESET_CUSTOM_LABEL
  for p in presets:
    if p.get("username", "").strip() == u:
      return p["label"]
  return MYQIMA_PRESET_CUSTOM_LABEL


def applyMyqimaTestAccountPreset(
  presetLabel: str,
  presets: list[dict],
  sessionState,
  userKey: str = "myqima_direct_user",
  pwdKey: str = "myqima_direct_pwd",
) -> None:
  """Fill session_state username/password when a preset is selected."""
  if presetLabel == MYQIMA_PRESET_CUSTOM_LABEL:
    return
  for p in presets:
    if p.get("label") == presetLabel:
      sessionState[userKey] = p.get("username", "")
      sessionState[pwdKey] = p.get("password", "")
      return


def build_ppsso_url(company_id: str) -> str:
  return f"{PPSSO_BASE_URL}/{company_id}"


def longTextFieldsDictForStorage(
  long_product_name: bool,
  long_purchase_order: bool,
  product_name_length: int = DEFAULT_LONG_PRODUCT_NAME_CHARS,
  purchase_order_length: int = DEFAULT_LONG_PO_CHARS,
) -> dict:
  """Shape stored under users_config.json → myqima.longTextFields."""
  return {
    "productName": long_product_name,
    "purchaseOrder": long_purchase_order,
    "productNameLength": max(1, int(product_name_length)),
    "purchaseOrderLength": max(1, int(purchase_order_length)),
  }


def factorySectionDictForStorage(
  enabled: bool,
  inspectionLocationType: InspectionLocationType,
  inspectionSiteFactoryName: str,
  dateCertaintyType: DateCertaintyType = "final_date_confirmed",
) -> dict:
  """Shape stored under users_config.json → myqima.factorySection."""
  certainty = dateCertaintyType if dateCertaintyType in (
    "final_date_confirmed",
    "tentative_date",
  ) else "final_date_confirmed"
  return {
    "enabled": enabled,
    "inspectionLocationType": inspectionLocationType,
    "inspectionSiteFactoryName": (inspectionSiteFactoryName or "").strip(),
    "dateCertaintyType": certainty,
  }


def persistMyqimaUserPrefs(
  cfgPath: str,
  username: str,
  playwrightProjectPath: Optional[str] = None,
  factorySection: Optional[dict] = None,
  longTextFields: Optional[dict] = None,
) -> None:
  """
  Merge myQIMA UI prefs into config/users_config.json for the given user.
  Does not write passwords; only path, factorySection, and longTextFields.
  """
  with open(cfgPath, encoding="utf-8") as fh:
    allCfg = json.load(fh)
  if "users" not in allCfg:
    allCfg["users"] = {}
  if username not in allCfg["users"]:
    allCfg["users"][username] = {}
  myqima = allCfg["users"][username].setdefault("myqima", {})
  if playwrightProjectPath:
    myqima["playwright_project_path"] = playwrightProjectPath
  if factorySection is not None:
    myqima["factorySection"] = factorySection
  if longTextFields is not None:
    myqima["longTextFields"] = longTextFields
  with open(cfgPath, "w", encoding="utf-8") as fh:
    json.dump(allCfg, fh, indent=2, ensure_ascii=False)


class BookingConfig:
  def __init__(
    self,
    login_type: str,
    booking_type: str,
    product_count: int = 1,
    dry_run: bool = False,
    direct_username: str = "",
    direct_password: str = "",
    company_id: str = "",
    ppsso_url: str = "",
    ppsso_username: str = "",
    ppsso_password: str = "",
    ea_variant: Optional[str] = None,
    enva_variant: Optional[str] = None,
    enable_factory_section: bool = False,
    inspection_location_type: Optional[InspectionLocationType] = None,
    inspection_site_factory_name: str = "",
    date_certainty_type: DateCertaintyType = "final_date_confirmed",
    long_text_product_name: bool = False,
    long_text_purchase_order: bool = False,
    long_product_name_length: int = DEFAULT_LONG_PRODUCT_NAME_CHARS,
    long_purchase_order_length: int = DEFAULT_LONG_PO_CHARS,
  ):
    self.login_type = login_type
    self.booking_type = booking_type
    self.product_count = product_count
    self.dry_run = dry_run
    self.direct_username = direct_username
    self.direct_password = direct_password
    self.company_id = company_id
    self.ppsso_url = ppsso_url or (build_ppsso_url(company_id) if company_id else "")
    self.ppsso_username = ppsso_username
    self.ppsso_password = ppsso_password
    self.ea_variant = ea_variant
    self.enva_variant = enva_variant
    self.enable_factory_section = enable_factory_section
    self.inspection_location_type = inspection_location_type or "yes"
    self.inspection_site_factory_name = inspection_site_factory_name
    self.date_certainty_type = (
      date_certainty_type
      if date_certainty_type in ("final_date_confirmed", "tentative_date")
      else "final_date_confirmed"
    )
    self.long_text_product_name = long_text_product_name
    self.long_text_purchase_order = long_text_purchase_order
    self.long_product_name_length = long_product_name_length
    self.long_purchase_order_length = long_purchase_order_length

  def to_dict(self) -> dict:
    config: dict = {
      "bookingType": self.booking_type,
      "productCount": self.product_count,
      "loginType": self.login_type,
      "dryRun": self.dry_run,
      "directAccount": {
        "username": self.direct_username,
        "password": self.direct_password,
      },
      "ppssoBackdoor": {
        "url": self.ppsso_url,
        "backofficeUsername": self.ppsso_username,
        "backofficePassword": self.ppsso_password,
      },
    }
    if self.company_id:
      config["companyId"] = self.company_id
    if self.ea_variant:
      config["eaVariant"] = self.ea_variant
    if self.enva_variant:
      config["envaVariant"] = self.enva_variant
    if self.enable_factory_section and self.booking_type in LOB_BOOKING_TYPES["Inspection"]:
      config["factorySection"] = {
        "enabled": True,
        "inspectionLocationType": self.inspection_location_type,
        "inspectionSiteFactoryName": self.inspection_site_factory_name,
        "dateCertaintyType": self.date_certainty_type,
      }
    if self.booking_type in LOB_BOOKING_TYPES["Inspection"]:
      if self.long_text_product_name or self.long_text_purchase_order:
        lt: dict = {}
        if self.long_text_product_name:
          lt["productName"] = True
          lt["productNameLength"] = max(1, int(self.long_product_name_length))
        if self.long_text_purchase_order:
          lt["purchaseOrder"] = True
          lt["purchaseOrderLength"] = max(1, int(self.long_purchase_order_length))
        config["longTextFields"] = lt
    return config

  def to_json(self) -> str:
    return json.dumps(self.to_dict(), indent=2)
