from __future__ import annotations

COLORS = {
    "background": "#0A0D12",
    "panel": "#10151C",
    "card": "#141A22",
    "card_alt": "#171E28",
    "border": "#252D38",
    "border_active": "#3D4A59",
    "text": "#F2F5F7",
    "muted": "#8995A3",
    "cyan": "#65B5FF",
    "cyan_dim": "#183149",
    "green": "#63D7A4",
    "yellow": "#E2B85B",
    "red": "#F27682",
    "purple": "#A997F4",
    "grid": "#202B37",
}


APP_STYLE = f"""
* {{
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
    color: {COLORS["text"]};
}}
QMainWindow, QWidget#root {{
    background: {COLORS["background"]};
}}
QWidget#sidebar, QWidget#inspector {{
    background: {COLORS["panel"]};
    border: 1px solid {COLORS["border"]};
}}
QFrame#card, QFrame#metricCard, QFrame#readoutCard, QFrame#channelReadout,
QFrame#analysisBanner {{
    background: {COLORS["card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
}}
QFrame#analysisBanner {{
    background: #161D26;
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
}}
QFrame#analysisDivider {{
    color: {COLORS["border_active"]};
    background: {COLORS["border_active"]};
    border: none;
    max-width: 1px;
}}
QFrame#readoutCard {{
    background: {COLORS["card_alt"]};
    border: 1px solid {COLORS["border"]};
}}
QFrame#channelReadout {{
    background: {COLORS["card_alt"]};
    border: 1px solid {COLORS["border"]};
}}
QLabel#brand {{
    color: {COLORS["cyan"]};
    font-size: 17px;
    font-weight: 750;
    letter-spacing: 1.4px;
}}
QLabel#brandSub {{
    color: {COLORS["muted"]};
    font-size: 10px;
    font-weight: 550;
    letter-spacing: .8px;
}}
QLabel#section {{
    color: {COLORS["muted"]};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .9px;
    padding: 4px 0 2px 0;
}}
QLabel#readout {{
    color: {COLORS["text"]};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 46px;
    font-weight: 600;
}}
QLabel#readoutUnit {{
    color: {COLORS["cyan"]};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#channelReadoutValue {{
    color: {COLORS["text"]};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 30px;
    font-weight: 600;
}}
QLabel#channelTagA {{
    color: {COLORS["cyan"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#channelTagB {{
    color: {COLORS["purple"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#channelTagC {{
    color: {COLORS["green"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#analysisChannelA, QLabel#analysisChannelB, QLabel#analysisChannelC,
QLabel#analysisChannelAB {{
    font-size: 15px;
    font-weight: 900;
    letter-spacing: 1px;
}}
QLabel#analysisChannelA {{
    color: {COLORS["cyan"]};
}}
QLabel#analysisChannelB {{
    color: {COLORS["purple"]};
}}
QLabel#analysisChannelC {{
    color: {COLORS["green"]};
}}
QLabel#analysisChannelAB {{
    color: {COLORS["text"]};
}}
QLabel#analysisResource {{
    color: {COLORS["text"]};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 13px;
    font-weight: 700;
}}
QLabel#analysisMeta {{
    color: {COLORS["muted"]};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#analysisCardTitle {{
    color: {COLORS["cyan"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#analysisCardTitleA {{
    color: {COLORS["cyan"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#analysisCardTitleB {{
    color: {COLORS["purple"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#analysisCardTitleC {{
    color: {COLORS["green"]};
    font-size: 12px;
    font-weight: 800;
}}
QLabel#readoutMode {{
    color: {COLORS["muted"]};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#metricValue {{
    color: {COLORS["text"]};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 17px;
    font-weight: 600;
}}
QLabel#metricTitle {{
    color: {COLORS["muted"]};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#hint {{
    color: {COLORS["muted"]};
    font-size: 11px;
}}
QLabel#statusGood {{
    color: {COLORS["green"]};
    background: #142B24;
    border: 1px solid #285041;
    border-radius: 8px;
    padding: 4px 10px;
    font-weight: 650;
}}
QLabel#statusIdle {{
    color: {COLORS["muted"]};
    background: #171D25;
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 4px 10px;
    font-weight: 650;
}}
QLabel#statusBad {{
    color: {COLORS["red"]};
    background: #2B181E;
    border: 1px solid #56313B;
    border-radius: 8px;
    padding: 4px 10px;
    font-weight: 650;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: #0F141B;
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 7px 9px;
    min-height: 20px;
    selection-background-color: {COLORS["cyan_dim"]};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border-color: {COLORS["border_active"]};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox#languageSwitch {{
    color: {COLORS["cyan"]};
    background: #151E28;
    border-color: {COLORS["border"]};
    font-weight: 700;
}}
QComboBox QAbstractItemView {{
    background: {COLORS["card_alt"]};
    border: 1px solid {COLORS["border_active"]};
    selection-background-color: {COLORS["cyan_dim"]};
    outline: 0;
}}
QPushButton {{
    background: #171E27;
    border: 1px solid {COLORS["border"]};
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: #1D2732;
    border-color: {COLORS["border_active"]};
}}
QPushButton:pressed {{
    background: #11171E;
}}
QPushButton#primary {{
    color: #07111B;
    background: {COLORS["cyan"]};
    border-color: {COLORS["cyan"]};
    font-weight: 700;
}}
QPushButton#primary:hover {{
    background: #84C5FF;
}}
QPushButton#danger {{
    color: {COLORS["red"]};
    background: #21161B;
    border-color: #49303A;
}}
QPushButton#subtle {{
    color: #B7C2CC;
    background: transparent;
    border-color: {COLORS["border"]};
}}
QPushButton:disabled {{
    color: #4F6578;
    background: #11161D;
    border-color: #1C242D;
}}
QCheckBox {{
    spacing: 8px;
    color: #B6C8D5;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLORS["border_active"]};
    border-radius: 4px;
    background: #09131D;
}}
QCheckBox::indicator:checked {{
    background: {COLORS["cyan"]};
    border-color: {COLORS["cyan"]};
}}
QCheckBox#syncChannelA, QCheckBox#syncChannelB, QCheckBox#syncChannelC {{
    background: #141A22;
    border: 1px solid {COLORS["border"]};
    border-radius: 7px;
    padding: 7px 9px;
    font-weight: 700;
}}
QCheckBox#syncChannelA:checked {{
    color: {COLORS["cyan"]};
    border-color: #355E80;
    background: #142231;
}}
QCheckBox#syncChannelB:checked {{
    color: {COLORS["purple"]};
    border-color: #514A73;
    background: #201D2D;
}}
QCheckBox#syncChannelC:checked {{
    color: {COLORS["green"]};
    border-color: #315E4C;
    background: #16271F;
}}
QCheckBox#syncChannelB::indicator:checked {{
    background: {COLORS["purple"]};
    border-color: {COLORS["purple"]};
}}
QCheckBox#syncChannelC::indicator:checked {{
    background: {COLORS["green"]};
    border-color: {COLORS["green"]};
}}
QTabWidget::pane {{
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    background: {COLORS["card"]};
    top: -1px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QTabBar::tab {{
    color: {COLORS["muted"]};
    background: transparent;
    border: none;
    padding: 9px 15px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {COLORS["cyan"]};
    border-bottom: 2px solid {COLORS["cyan"]};
}}
QTabBar::tab:hover {{
    color: {COLORS["text"]};
}}
QTextEdit {{
    background: #0D1218;
    border: 1px solid {COLORS["border"]};
    border-radius: 7px;
    color: #97A5B2;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
    padding: 6px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #294157;
    border-radius: 4px;
    min-height: 26px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QToolTip {{
    color: {COLORS["text"]};
    background: #1A222C;
    border: 1px solid {COLORS["border_active"]};
    padding: 6px;
}}
QSplitter::handle {{
    background: {COLORS["border"]};
    width: 4px;
    height: 4px;
    margin: 3px;
}}
QFrame#channelReadout:disabled {{
    background: #0B151F;
    border-color: #182A3A;
}}
QFrame#channelReadout:disabled QLabel {{
    color: #496071;
}}
"""
