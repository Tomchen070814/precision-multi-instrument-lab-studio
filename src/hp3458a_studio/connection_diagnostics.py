from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import Enum

from .models import InstrumentModel

logger = logging.getLogger(__name__)

try:
    import pyvisa
except ImportError:  # pragma: no cover - PyVISA is bundled in Windows builds
    pyvisa = None


class ConnectionIssueCode(str, Enum):
    OK = "ok"
    PYVISA_MISSING = "pyvisa_missing"
    VISA_RUNTIME_MISSING = "visa_runtime_missing"
    VISA_DISCOVERY_FAILED = "visa_discovery_failed"
    INVALID_RESOURCE = "invalid_resource"
    RESOURCE_NOT_ENUMERATED = "resource_not_enumerated"
    GPIB_INTERFACE_MISSING = "gpib_interface_missing"
    GPIB_ADDRESS_MISSING = "gpib_address_missing"
    GPIB_NOT_CONTROLLER = "gpib_not_controller"
    GPIB_NO_LISTENER = "gpib_no_listener"
    VISA_TIMEOUT = "visa_timeout"
    RESOURCE_BUSY = "resource_busy"
    CONNECTION_LOST = "connection_lost"
    IDENTITY_MISMATCH = "identity_mismatch"
    UNKNOWN_CONNECTION_ERROR = "unknown_connection_error"


@dataclass(frozen=True)
class DriverDownload:
    name: str
    vendor: str
    url: str
    purpose_zh: str
    purpose_en: str


OFFICIAL_DRIVER_DOWNLOADS: tuple[DriverDownload, ...] = (
    DriverDownload(
        name="NI-VISA",
        vendor="NI",
        url="https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html",
        purpose_zh="NI 的 64 位 VISA 运行库；支持 GPIB、USB、LAN 和串口。",
        purpose_en=("NI 64-bit VISA runtime for GPIB, USB, LAN and serial resources."),
    ),
    DriverDownload(
        name="NI-488.2",
        vendor="NI",
        url="https://www.ni.com/en/support/downloads/drivers/download.ni-488-2.html",
        purpose_zh="NI GPIB-USB-HS/HS+ 等 NI GPIB 控制器的必需驱动。",
        purpose_en=(
            "Required hardware driver for NI GPIB controllers such as GPIB-USB-HS/HS+."
        ),
    ),
    DriverDownload(
        name="Keysight IO Libraries Suite",
        vendor="Keysight",
        url=(
            "https://www.keysight.com/us/en/lib/software-detail/"
            "computer-software/io-libraries-suite-downloads-2175637.html"
        ),
        purpose_zh=("Keysight VISA、Connection Expert 以及 82357A/B 等接口驱动。"),
        purpose_en=(
            "Keysight VISA, Connection Expert and drivers for interfaces "
            "including the 82357A/B."
        ),
    ),
    DriverDownload(
        name="R&S VISA",
        vendor="Rohde & Schwarz",
        url=(
            "https://www.rohde-schwarz.com/us/driver-pages/"
            "remote-control/3-visa-and-tools_231388.html"
        ),
        purpose_zh="Rohde & Schwarz 官方 VISA；适合 R&S USB/LAN 仪表。",
        purpose_en=("Official Rohde & Schwarz VISA for R&S USB/LAN instruments."),
    ),
    DriverDownload(
        name="TekVISA",
        vendor="Tektronix / Keithley",
        url=(
            "https://www.tek.com/en/support/software/driver/"
            "tekvisa-connectivity-software-v5111"
        ),
        purpose_zh="Tektronix/Keithley 官方 VISA；属于可选 VISA 后端。",
        purpose_en=("Official Tektronix/Keithley VISA; an optional VISA backend."),
    ),
)


@dataclass(frozen=True)
class ConnectionDiagnostic:
    code: ConnectionIssueCode
    category: str
    resource: str
    model: str
    blocking: bool
    title_zh: str
    title_en: str
    summary_zh: str
    summary_en: str
    steps_zh: tuple[str, ...] = ()
    steps_en: tuple[str, ...] = ()
    visa_backend: str = ""
    discovered_resources: tuple[str, ...] = ()
    raw_error: str = ""

    @property
    def ok(self) -> bool:
        return self.code is ConnectionIssueCode.OK

    def title(self, language: str) -> str:
        return self.title_en if language == "en" else self.title_zh

    def summary(self, language: str) -> str:
        return self.summary_en if language == "en" else self.summary_zh

    def steps(self, language: str) -> tuple[str, ...]:
        return self.steps_en if language == "en" else self.steps_zh

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["code"] = self.code.value
        return payload


class ConnectionPreflightError(RuntimeError):
    def __init__(self, diagnostic: ConnectionDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.summary_zh)


def _backend_description(manager) -> str:
    visa_library = getattr(manager, "visalib", None)
    library_path = getattr(visa_library, "library_path", "")
    if library_path:
        return str(library_path)
    return type(visa_library).__name__ if visa_library is not None else ""


def _list_all_resources(manager) -> tuple[tuple[str, ...], tuple[str, ...]]:
    instrument_resources = tuple(str(item) for item in manager.list_resources())
    try:
        all_resources = tuple(str(item) for item in manager.list_resources("?*"))
    except (TypeError, ValueError):
        all_resources = instrument_resources
    return instrument_resources, tuple(
        dict.fromkeys((*all_resources, *instrument_resources))
    )


def _diagnostic(
    code: ConnectionIssueCode,
    category: str,
    resource: str,
    model: InstrumentModel,
    *,
    blocking: bool,
    title_zh: str,
    title_en: str,
    summary_zh: str,
    summary_en: str,
    steps_zh: tuple[str, ...] = (),
    steps_en: tuple[str, ...] = (),
    visa_backend: str = "",
    discovered_resources: tuple[str, ...] = (),
    raw_error: str = "",
) -> ConnectionDiagnostic:
    return ConnectionDiagnostic(
        code=code,
        category=category,
        resource=resource,
        model=model.display_name,
        blocking=blocking,
        title_zh=title_zh,
        title_en=title_en,
        summary_zh=summary_zh,
        summary_en=summary_en,
        steps_zh=steps_zh,
        steps_en=steps_en,
        visa_backend=visa_backend,
        discovered_resources=discovered_resources,
        raw_error=raw_error,
    )


def _driver_missing_diagnostic(
    resource: str,
    model: InstrumentModel,
    raw_error: str,
    *,
    pyvisa_package_missing: bool = False,
) -> ConnectionDiagnostic:
    return _diagnostic(
        (
            ConnectionIssueCode.PYVISA_MISSING
            if pyvisa_package_missing
            else ConnectionIssueCode.VISA_RUNTIME_MISSING
        ),
        "driver",
        resource,
        model,
        blocking=True,
        title_zh="驱动问题：未找到可用的 VISA 运行库",
        title_en="Driver problem: no usable VISA runtime",
        summary_zh=(
            "软件无法加载 64 位 VISA。请只选择并安装一个主要 VISA "
            "运行库；若使用 NI GPIB 控制器，还必须安装 NI-488.2。"
        ),
        summary_en=(
            "The application cannot load a 64-bit VISA runtime. Install one "
            "primary VISA implementation. NI GPIB hardware also requires "
            "NI-488.2."
        ),
        steps_zh=(
            "确认 Windows 和本软件均为 64 位。",
            "NI GPIB-USB-HS/HS+：安装 NI-VISA 与 NI-488.2。",
            "Keysight 82357A/B：安装 Keysight IO Libraries Suite。",
            "安装或修复驱动后重启电脑，再运行连接自检。",
        ),
        steps_en=(
            "Confirm that Windows and the application are both 64-bit.",
            "NI GPIB-USB-HS/HS+: install NI-VISA and NI-488.2.",
            "Keysight 82357A/B: install Keysight IO Libraries Suite.",
            (
                "Restart Windows after installing or repairing drivers, then "
                "run the connection self-check again."
            ),
        ),
        raw_error=raw_error,
    )


def inspect_visa_environment(
    resource: str,
    model: InstrumentModel,
    *,
    manager_factory: Callable[[], object] | None = None,
) -> ConnectionDiagnostic:
    """Inspect VISA and GPIB enumeration without opening the instrument."""
    normalized = resource.strip().upper()
    if model.requires_gpib and not (
        normalized.startswith("GPIB") and normalized.endswith("::INSTR")
    ):
        return _diagnostic(
            ConnectionIssueCode.INVALID_RESOURCE,
            "address",
            resource,
            model,
            blocking=True,
            title_zh="地址问题：该仪表必须使用 GPIB 仪表地址",
            title_en="Address problem: this instrument requires GPIB",
            summary_zh=(
                f"{model.display_name} 不能使用 {resource!r}。应选择类似 "
                "GPIB0::22::INSTR 的资源。"
            ),
            summary_en=(
                f"{model.display_name} cannot use {resource!r}. Select a "
                "resource such as GPIB0::22::INSTR."
            ),
        )
    if pyvisa is None and manager_factory is None:
        return _driver_missing_diagnostic(
            resource,
            model,
            "PyVISA package is not installed",
            pyvisa_package_missing=True,
        )
    factory = manager_factory
    if factory is None:
        factory = lambda: pyvisa.ResourceManager("")  # type: ignore[union-attr]
    manager = None
    try:
        manager = factory()
        backend = _backend_description(manager)
        instrument_resources, all_resources = _list_all_resources(manager)
    except Exception as exc:  # noqa: BLE001 - vendor VISA exceptions vary
        error_text = str(exc)
        normalized_error = error_text.upper()
        if any(
            token in normalized_error
            for token in (
                "COULD NOT LOCATE A VISA IMPLEMENTATION",
                "VI_ERROR_LIBRARY_NFOUND",
                "VISA32.DLL",
                "VISA64.DLL",
                "LIBVISA",
                "NO VISA",
            )
        ):
            return _driver_missing_diagnostic(resource, model, error_text)
        return _diagnostic(
            ConnectionIssueCode.VISA_DISCOVERY_FAILED,
            "driver",
            resource,
            model,
            blocking=True,
            title_zh="驱动问题：VISA 扫描失败",
            title_en="Driver problem: VISA discovery failed",
            summary_zh=(
                "VISA 已被调用，但资源管理器无法完成扫描。常见原因是多个 "
                "VISA 安装损坏、位数不一致或驱动服务未启动。"
            ),
            summary_en=(
                "VISA was found, but its resource manager could not complete "
                "discovery. Typical causes are a damaged multi-VISA install, "
                "bitness mismatch, or a stopped driver service."
            ),
            steps_zh=(
                "关闭 NI MAX、Connection Expert 和其他仪表软件。",
                "在 Windows“应用”中修复主要 VISA，再重启电脑。",
                "不要同时把多个厂商 VISA 都设为 Primary。",
            ),
            steps_en=(
                "Close NI MAX, Connection Expert and other instrument apps.",
                (
                    "Repair the primary VISA installation in Windows Apps, "
                    "then restart Windows."
                ),
                ("Do not configure multiple vendor VISA implementations as Primary."),
            ),
            raw_error=error_text,
        )
    finally:
        if manager is not None:
            try:
                manager.close()
            except Exception:  # noqa: BLE001
                logger.warning("VISA self-check manager close failed")

    discovered = tuple(dict.fromkeys((*all_resources, *instrument_resources)))
    if model.requires_gpib:
        interface = normalized.split("::", 1)[0]
        gpib_resources = tuple(
            item for item in discovered if item.strip().upper().startswith("GPIB")
        )
        same_interface = tuple(
            item
            for item in gpib_resources
            if item.strip().upper().startswith(f"{interface}::")
        )
        target_seen = any(
            item.strip().upper() == normalized for item in instrument_resources
        )
        if not gpib_resources:
            return _diagnostic(
                ConnectionIssueCode.GPIB_INTERFACE_MISSING,
                "gpib",
                resource,
                model,
                blocking=True,
                title_zh="GPIB 问题：未发现 GPIB 控制器",
                title_en="GPIB problem: no GPIB controller detected",
                summary_zh=(
                    "VISA 可以运行，但没有枚举到任何 GPIB 接口。问题位于 "
                    "USB-GPIB 控制器、其驱动、USB 连接或供电，不是万用表"
                    "测量设置。"
                ),
                summary_en=(
                    "VISA is working, but no GPIB interface is enumerated. "
                    "The fault is in the USB-GPIB controller, its driver, USB "
                    "connection or power—not the DMM measurement settings."
                ),
                steps_zh=(
                    "重新插拔 USB-GPIB 控制器，并更换 USB 端口或线缆。",
                    (
                        "NI 控制器在 NI MAX 中应出现；Keysight 控制器在 "
                        "Connection Expert 中应出现。"
                    ),
                    (
                        "按控制器品牌安装对应驱动：NI-488.2 或 Keysight "
                        "IO Libraries Suite。"
                    ),
                ),
                steps_en=(
                    (
                        "Reconnect the USB-GPIB controller and try another USB "
                        "port or cable."
                    ),
                    (
                        "NI hardware must appear in NI MAX; Keysight hardware "
                        "must appear in Connection Expert."
                    ),
                    (
                        "Install the matching controller driver: NI-488.2 or "
                        "Keysight IO Libraries Suite."
                    ),
                ),
                visa_backend=backend,
                discovered_resources=discovered,
            )
        if not target_seen:
            return _diagnostic(
                ConnectionIssueCode.GPIB_ADDRESS_MISSING,
                "gpib",
                resource,
                model,
                blocking=True,
                title_zh="GPIB 问题：指定地址没有仪表响应",
                title_en="GPIB problem: no instrument at the selected address",
                summary_zh=(
                    f"已发现 GPIB 接口，但没有枚举到 {resource}。请核对仪表"
                    "面板上的 GPIB 地址、线缆和终端连接。"
                ),
                summary_en=(
                    f"A GPIB interface was detected, but {resource} was not "
                    "enumerated. Check the front-panel GPIB address, cable and "
                    "bus connections."
                ),
                steps_zh=(
                    f"确认仪表地址与 {resource} 中的主地址一致。",
                    "确认仪表已开机，GPIB 线两端锁紧且没有重复地址。",
                    "在 NI MAX 或 Connection Expert 中重新扫描总线。",
                    (
                        f"当前 {interface} 可见资源："
                        + (", ".join(same_interface) if same_interface else "无")
                    ),
                ),
                steps_en=(
                    f"Match the instrument primary address to {resource}.",
                    (
                        "Confirm power, tighten both GPIB connectors and "
                        "remove duplicate addresses."
                    ),
                    "Rescan the bus in NI MAX or Connection Expert.",
                    (
                        f"Resources currently visible on {interface}: "
                        + (", ".join(same_interface) if same_interface else "none")
                    ),
                ),
                visa_backend=backend,
                discovered_resources=discovered,
            )
    elif normalized and not any(
        item.strip().upper() == normalized for item in instrument_resources
    ):
        return _diagnostic(
            ConnectionIssueCode.RESOURCE_NOT_ENUMERATED,
            "address",
            resource,
            model,
            blocking=False,
            title_zh="连接提示：手动地址未被 VISA 扫描列出",
            title_en="Connection note: VISA did not enumerate the manual address",
            summary_zh=(
                f"VISA 当前没有列出 {resource}。对于手动输入的 LAN/SOCKET "
                "地址仍可继续尝试连接；USB 地址则应先检查驱动和线缆。"
            ),
            summary_en=(
                f"VISA does not currently list {resource}. A manually entered "
                "LAN/SOCKET address can still be tried; a USB address should "
                "first be checked for driver and cable problems."
            ),
            visa_backend=backend,
            discovered_resources=discovered,
        )

    return _diagnostic(
        ConnectionIssueCode.OK,
        "ok",
        resource,
        model,
        blocking=False,
        title_zh="连接自检通过",
        title_en="Connection self-check passed",
        summary_zh=(
            f"VISA 运行库、接口枚举和地址检查通过：{resource}。下一步将"
            "由仪表身份查询确认具体型号。"
        ),
        summary_en=(
            f"VISA runtime, interface enumeration and address checks passed "
            f"for {resource}. The instrument identity query is the next check."
        ),
        visa_backend=backend,
        discovered_resources=discovered,
    )


def classify_connection_error(
    error: BaseException | str,
    resource: str,
    model: InstrumentModel,
) -> ConnectionDiagnostic:
    """Classify a connection/open/query failure into a user-actionable cause."""
    raw_error = str(error)
    normalized = raw_error.upper()
    base = {
        "resource": resource,
        "model": model,
        "blocking": True,
        "raw_error": raw_error,
    }
    if any(
        token in normalized
        for token in (
            "COULD NOT LOCATE A VISA IMPLEMENTATION",
            "VI_ERROR_LIBRARY_NFOUND",
            "VISA32.DLL",
            "VISA64.DLL",
            "LIBVISA",
            "缺少 PYVISA",
        )
    ):
        return _driver_missing_diagnostic(resource, model, raw_error)
    if "VI_ERROR_NCIC" in normalized or "-1073807264" in normalized:
        return _diagnostic(
            ConnectionIssueCode.GPIB_NOT_CONTROLLER,
            "gpib",
            **base,
            title_zh="GPIB 问题：接口没有总线控制权",
            title_en="GPIB problem: interface is not controller-in-charge",
            summary_zh=(
                "GPIB 接口没有取得 Controller-in-Charge/System Controller "
                "权限，无法发起通信。"
            ),
            summary_en=(
                "The GPIB interface is not Controller-in-Charge/System "
                "Controller and cannot initiate communication."
            ),
            steps_zh=(
                "关闭所有占用仪表的程序。",
                "在 NI MAX 或 Connection Expert 中启用 System Controller。",
                "断开同一总线上的其他 GPIB 控制器后重试。",
            ),
            steps_en=(
                "Close every program that may own the instrument.",
                "Enable System Controller in NI MAX or Connection Expert.",
                "Disconnect any second GPIB controller on the same bus.",
            ),
        )
    if "VI_ERROR_NLISTENERS" in normalized or "-1073807265" in normalized:
        return _diagnostic(
            ConnectionIssueCode.GPIB_NO_LISTENER,
            "gpib",
            **base,
            title_zh="GPIB 问题：该地址没有监听器",
            title_en="GPIB problem: no listener at this address",
            summary_zh=(
                f"{resource} 没有仪表响应。通常是地址不一致、仪表未开机、"
                "GPIB 线松动或总线中存在重复地址。"
            ),
            summary_en=(
                f"No instrument responded at {resource}. Typical causes are "
                "an address mismatch, instrument power, a loose GPIB cable or "
                "duplicate bus addresses."
            ),
            steps_zh=(
                "核对仪表前面板的 GPIB 主地址。",
                "锁紧 GPIB 连接器并在官方连接工具中重新扫描。",
                "确认同一总线上没有两台仪表使用相同地址。",
            ),
            steps_en=(
                "Check the GPIB primary address on the instrument front panel.",
                "Tighten the GPIB connectors and rescan in the vendor tool.",
                "Remove duplicate instrument addresses on the bus.",
            ),
        )
    if "VI_ERROR_TMO" in normalized or "-1073807339" in normalized:
        category = (
            "gpib" if resource.strip().upper().startswith("GPIB") else "instrument"
        )
        return _diagnostic(
            ConnectionIssueCode.VISA_TIMEOUT,
            category,
            **base,
            title_zh=(
                "GPIB 问题：通信超时"
                if category == "gpib"
                else "仪表连接问题：通信超时"
            ),
            title_en=(
                "GPIB problem: communication timeout"
                if category == "gpib"
                else "Instrument connection problem: communication timeout"
            ),
            summary_zh=("VISA 已打开资源，但仪表没有在超时时间内返回完整响应。"),
            summary_en=(
                "VISA opened the resource, but the instrument did not return a "
                "complete response before timeout."
            ),
            steps_zh=(
                "关闭 NI MAX/Connection Expert 的交互测试窗口。",
                "检查地址、终止符、线缆和仪表远程接口设置。",
                "断电重启仪表与接口后再次自检。",
            ),
            steps_en=(
                "Close interactive test panels in NI MAX/Connection Expert.",
                (
                    "Check the address, termination, cable and "
                    "remote-interface settings."
                ),
                "Power-cycle the instrument and interface, then rerun self-check.",
            ),
        )
    if any(
        token in normalized
        for token in ("VI_ERROR_RSRC_BUSY", "RESOURCE BUSY", "ACCESS DENIED")
    ):
        return _diagnostic(
            ConnectionIssueCode.RESOURCE_BUSY,
            "instrument",
            **base,
            title_zh="仪表连接问题：资源正被其他程序占用",
            title_en="Instrument connection problem: resource is busy",
            summary_zh=(
                "VISA 资源存在，但已被 NI MAX、Connection Expert、BenchVue "
                "或另一个采集程序独占。"
            ),
            summary_en=(
                "The VISA resource exists but is locked by NI MAX, Connection "
                "Expert, BenchVue or another acquisition program."
            ),
            steps_zh=("关闭其他仪表软件的会话后重试。",),
            steps_en=("Close other instrument sessions and try again.",),
        )
    if any(
        token in normalized
        for token in ("VI_ERROR_CONN_LOST", "CONNECTION LOST", "DEVICE DISCONNECTED")
    ):
        return _diagnostic(
            ConnectionIssueCode.CONNECTION_LOST,
            "gpib" if resource.strip().upper().startswith("GPIB") else "instrument",
            **base,
            title_zh="连接中断：仪表或接口已断开",
            title_en="Connection lost: instrument or interface disconnected",
            summary_zh="采集过程中连接消失；已采集数据仍保留在安全自动保存文件中。",
            summary_en=(
                "The connection disappeared during acquisition. Samples already "
                "received remain in the durable autosave file."
            ),
            steps_zh=("检查 USB/GPIB/LAN 连接和仪表供电后重新扫描。",),
            steps_en=("Check USB/GPIB/LAN cabling and power, then rescan.",),
        )
    if any(
        token in normalized
        for token in (
            "身份应包含",
            "不像 3458A",
            "当前通道选择的是",
            "IDENTITY",
        )
    ):
        return _diagnostic(
            ConnectionIssueCode.IDENTITY_MISMATCH,
            "instrument",
            **base,
            title_zh="型号问题：连接到的仪表与所选型号不一致",
            title_en="Model problem: connected instrument does not match",
            summary_zh=(
                "VISA 与通信链路正常，但身份查询返回了另一种型号。请修改"
                "通道的仪表型号或 VISA 地址。"
            ),
            summary_en=(
                "VISA and transport are working, but the identity query returned "
                "a different model. Change the channel model or VISA address."
            ),
        )
    return _diagnostic(
        ConnectionIssueCode.UNKNOWN_CONNECTION_ERROR,
        "instrument",
        **base,
        title_zh="仪表连接失败：需要查看诊断报告",
        title_en="Instrument connection failed: diagnostic report required",
        summary_zh=(
            "自检未能把错误可靠归入驱动、GPIB、地址或型号类别。请导出"
            "诊断报告，保留原始 VISA 错误代码。"
        ),
        summary_en=(
            "The self-check could not reliably classify this as a driver, GPIB, "
            "address or model fault. Export a diagnostic report so the original "
            "VISA error code is retained."
        ),
    )


def relevant_driver_downloads(
    diagnostic: ConnectionDiagnostic,
) -> tuple[DriverDownload, ...]:
    """Return only official downloads relevant to the diagnosed layer."""
    if diagnostic.category == "gpib":
        return tuple(
            item
            for item in OFFICIAL_DRIVER_DOWNLOADS
            if item.name in {"NI-488.2", "Keysight IO Libraries Suite", "NI-VISA"}
        )
    if diagnostic.category == "driver":
        return OFFICIAL_DRIVER_DOWNLOADS
    return ()
