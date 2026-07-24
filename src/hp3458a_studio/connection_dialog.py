from __future__ import annotations

import html

from PySide6 import QtCore, QtWidgets

from .connection_diagnostics import (
    ConnectionDiagnostic,
    relevant_driver_downloads,
)


class ConnectionDiagnosticDialog(QtWidgets.QDialog):
    """Readable, link-enabled presentation of one connection diagnosis."""

    def __init__(
        self,
        diagnostic: ConnectionDiagnostic,
        language: str,
        parent=None,
    ):
        super().__init__(parent)
        self.diagnostic = diagnostic
        self.language = "en" if language == "en" else "zh"
        self.setWindowTitle(diagnostic.title(self.language))
        self.setModal(True)
        self.resize(690, 560)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QtWidgets.QLabel(diagnostic.title(self.language))
        title.setObjectName("section")
        title.setWordWrap(True)
        layout.addWidget(title)

        summary = QtWidgets.QLabel(diagnostic.summary(self.language))
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(summary)

        details = QtWidgets.QTextBrowser()
        details.setOpenExternalLinks(True)
        details.setHtml(self._details_html())
        layout.addWidget(details, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _details_html(self) -> str:
        diagnostic = self.diagnostic
        steps = diagnostic.steps(self.language)
        links = relevant_driver_downloads(diagnostic)
        resource_label = "Resource" if self.language == "en" else "资源"
        backend_label = (
            "Detected VISA backend" if self.language == "en" else "检测到的 VISA 后端"
        )
        resources_label = (
            "Enumerated resources" if self.language == "en" else "已枚举资源"
        )
        steps_label = "Checks / actions" if self.language == "en" else "检查与处理"
        downloads_label = (
            "Official driver downloads" if self.language == "en" else "官方驱动下载"
        )
        raw_label = "Original error" if self.language == "en" else "原始错误"
        install_note = (
            "Install the driver matching the interface hardware. Do not set "
            "several vendor VISA implementations as Primary at the same time."
            if self.language == "en"
            else "按接口硬件品牌选择驱动；不要同时把多个厂商 VISA 设为 Primary。"
        )
        blocks = [
            (
                f"<p><b>{html.escape(resource_label)}:</b> "
                f"<code>{html.escape(diagnostic.resource)}</code><br>"
                f"<b>{html.escape(backend_label)}:</b> "
                "<code>"
                f"{html.escape(diagnostic.visa_backend or '(unknown)')}"
                "</code></p>"
            )
        ]
        if steps:
            blocks.append(
                f"<h3>{html.escape(steps_label)}</h3><ol>"
                + "".join(f"<li>{html.escape(step)}</li>" for step in steps)
                + "</ol>"
            )
        if diagnostic.discovered_resources:
            blocks.append(
                f"<h3>{html.escape(resources_label)}</h3><p><code>"
                + "<br>".join(
                    html.escape(item) for item in diagnostic.discovered_resources
                )
                + "</code></p>"
            )
        if links:
            blocks.append(f"<h3>{html.escape(downloads_label)}</h3>")
            blocks.append(f"<p>{html.escape(install_note)}</p><ul>")
            for item in links:
                purpose = item.purpose_en if self.language == "en" else item.purpose_zh
                blocks.append(
                    "<li>"
                    f"<a href='{html.escape(item.url, quote=True)}'>"
                    f"{html.escape(item.name)}</a> — "
                    f"{html.escape(purpose)}</li>"
                )
            blocks.append("</ul>")
        if diagnostic.raw_error:
            blocks.append(
                f"<h3>{html.escape(raw_label)}</h3><pre>"
                f"{html.escape(diagnostic.raw_error)}</pre>"
            )
        return "".join(blocks)
