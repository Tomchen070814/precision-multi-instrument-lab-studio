from hp3458a_studio.i18n import function_name, tr
from hp3458a_studio.models import MeasurementFunction


def test_translator_switches_static_and_formatted_text():
    assert tr("zh", "停止全部") == "停止全部"
    assert tr("en", "停止全部") == "Stop all"
    assert (
        tr("en", "同步启动 {channels}", channels="A+B+C") == "Synchronized start A+B+C"
    )
    assert tr("en", "启动 {channels}", channels="C") == "Start C"
    assert tr("en", "导出诊断报告") == "Export diagnostic report"


def test_measurement_function_names_are_bilingual():
    function = MeasurementFunction.RESISTANCE_4W
    assert function_name("zh", function) == "四线电阻"
    assert function_name("en", function) == "4-wire resistance"
