from decimal import Decimal

import serial
from serial.tools import list_ports
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .scpi import CHANNELS, SerialSettings
from .worker import DeviceWorker, MONITOR_INTERVAL_MS


STYLESHEET = """
QMainWindow, QWidget#content { background: #f1f4f8; color: #152238; }
QFrame#card { background: white; border: 1px solid #d9e2ec; border-radius: 8px; }
QLabel#title { font-size: 24px; font-weight: 700; color: #14223a; }
QLabel#heading { font-size: 16px; font-weight: 700; color: #14223a; }
QLabel#muted { color: #52647b; }
QLabel#active { color: #075f6d; font-weight: 600; }
QLabel#alert { color: #b3262d; font-weight: 600; }
QLabel#reading { font-size: 19px; font-weight: 600; color: #14223a; }
QPushButton { background: #fff; color: #14223a; border: 1px solid #b9c8d7;
              border-radius: 5px; padding: 5px 10px; }
QPushButton:hover { background: #eaf2fa; }
QPushButton#primary { background: #155a94; color: white; border-color: #155a94; }
QPushButton#primary:hover { background: #114877; }
QPushButton#off { color: #a8222a; }
QPushButton:disabled, QPushButton#primary:disabled, QPushButton#off:disabled {
    background: #eef2f6; color: #68798b; border-color: #d5dfe9;
}
QComboBox, QDoubleSpinBox { min-height: 25px; padding-left: 5px; }
QListWidget { border: 1px solid #c3cfdb; border-radius: 4px; }
QListWidget::item { padding: 3px 6px; }
QTabBar::tab { padding: 8px 16px; }
QTabWidget::pane { border: 1px solid #d9e2ec; background: #f1f4f8; }
"""


def label(value, style=""):
    widget = QLabel(value)
    widget.setTextFormat(Qt.PlainText)
    widget.setObjectName(style)
    return widget


def set_label_style(widget, style):
    widget.setObjectName(style)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def button(value, action, style=""):
    widget = QPushButton(value)
    widget.setObjectName(style)
    widget.clicked.connect(action)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    return widget


def number(maximum, value=0):
    widget = QDoubleSpinBox()
    widget.setDecimals(3)
    widget.setRange(0, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMinimumWidth(92)
    return widget


class ChannelCard(QFrame):
    request = pyqtSignal(str, int, object)

    def __init__(self, channel):
        super().__init__()
        self.setObjectName("card")
        self.channel = channel
        self.state = "idle"
        self.last_current = None
        self.voltage_set = number(999.999)
        self.limit_ma = number(999999.999)
        self.threshold = number(999999.999, 100.0)
        self.current = label("—", "reading")
        self.voltage = label("—", "reading")
        self.output = label("输出未知", "muted")
        self.monitor_status = label("未监控", "muted")
        self.monitor_status.setWordWrap(True)

        self.read_button = button("读取", lambda: self.send("read"))
        self.apply_button = button("下发设定", self.apply)
        self.on_button = button("开启输出", lambda: self.send("output", True))
        self.off_button = button("关闭输出", lambda: self.send("output", False), "off")
        self.monitor_button = button("开始监控", self.toggle_monitor, "primary")
        self.reset_button = button("复位过流", lambda: self.send("reset"))

        layout = QGridLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        layout.addWidget(label(f"CH{channel}", "heading"), 0, 0)
        layout.addWidget(self.output, 0, 1)
        layout.addWidget(label("实测电压", "muted"), 0, 2)
        layout.addWidget(self.voltage, 0, 3)
        layout.addWidget(label("实测电流", "muted"), 0, 4)
        layout.addWidget(self.current, 0, 5, 1, 2)
        layout.addWidget(self.read_button, 0, 7)
        layout.addWidget(label("电压设定（V）", "muted"), 1, 0, 1, 2)
        layout.addWidget(self.voltage_set, 1, 2)
        layout.addWidget(label("限流设定（mA）", "muted"), 1, 3)
        layout.addWidget(self.limit_ma, 1, 4)
        layout.addWidget(self.apply_button, 1, 5)
        layout.addWidget(self.on_button, 1, 6)
        layout.addWidget(self.off_button, 1, 7)
        layout.addWidget(label("监控阈值（mA）", "muted"), 2, 0, 1, 2)
        layout.addWidget(self.threshold, 2, 2)
        layout.addWidget(self.monitor_status, 2, 3, 1, 3)
        layout.addWidget(self.monitor_button, 2, 6)
        layout.addWidget(self.reset_button, 2, 7)
        layout.setColumnStretch(5, 1)

    def send(self, action, value=None):
        self.request.emit(action, self.channel, value)

    def apply(self):
        voltage = Decimal(str(self.voltage_set.value()))
        limit = Decimal(str(self.limit_ma.value()))
        self.send("apply", (voltage, limit))

    def toggle_monitor(self):
        if self.state == "active":
            self.send("stop")
        else:
            self.send("start", self.threshold.value())

    def set_controls(self, available):
        latched = self.state in {"tripped", "unconfirmed"}
        for widget in (self.voltage_set, self.limit_ma, self.apply_button,
                       self.read_button, self.off_button):
            widget.setEnabled(available)
        self.threshold.setEnabled(available and self.state == "idle")
        self.on_button.setEnabled(available and not latched)
        self.monitor_button.setEnabled(available and not latched)
        self.reset_button.setEnabled(available and self.state == "tripped")

    def set_current(self, measured):
        self.last_current = measured
        self.current.setText(f"{measured:.3f} mA")

    def set_output(self, enabled):
        self.output.setText("输出开启" if enabled else "输出关闭")
        set_label_style(self.output, "active" if enabled else "muted")

    def setpoints(self, voltage, current):
        self.voltage_set.setValue(float(voltage))
        self.limit_ma.setValue(float(current))

    def update_readings(self, readings):
        self.setpoints(readings.voltage_set, readings.limit_ma)
        self.voltage.setText(f"{readings.voltage:.3f} V")
        self.set_current(readings.current_ma)
        self.set_output(readings.output_on)

    def set_monitor(self, state):
        self.state = state
        style = "muted"
        if state in {"tripped", "unconfirmed"}:
            status = "过流已关断" if state == "tripped" else "过流关断未确认"
            if self.last_current is not None:
                status += f" · {self.last_current:.3f} mA"
            style = "alert"
        elif state == "active":
            status = f"监控中 · {MONITOR_INTERVAL_MS} ms"
            style = "active"
        else:
            status = "监控已中断" if state == "interrupted" else "未监控"
        self.monitor_status.setText(status)
        set_label_style(self.monitor_status, style)
        self.monitor_button.setText("停止监控" if state == "active" else "开始监控")


class DevicePanel(QWidget):
    command = pyqtSignal(str, int, object)
    stop_worker = pyqtSignal()
    updated = pyqtSignal()
    ended = pyqtSignal()
    notice = pyqtSignal(str)

    def __init__(self, port, settings, worker_factory):
        super().__init__()
        self.port = port
        self.model = ""
        self.running = True
        self.online = False
        self.closing = False
        self.busy = False
        self.removing = False
        self.failure = False
        self.identity = label(f"{port} · 正在查询设备标识…", "heading")
        self.detail = label(
            f"{settings.baudrate} baud · 8{settings.parity}1", "muted"
        )
        self.detail.setWordWrap(True)
        self.message = label("", "muted")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(22)
        self.channels = {channel: ChannelCard(channel) for channel in CHANNELS}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)
        layout.addWidget(self.identity)
        layout.addWidget(self.detail)
        for channel in self.channels.values():
            layout.addWidget(channel)
            channel.request.connect(self.dispatch)
        layout.addWidget(self.message)
        layout.addStretch()
        self.update_controls()

        self.io_thread = QThread(self)
        self.worker = worker_factory(port, settings)
        self.worker.moveToThread(self.io_thread)
        self.io_thread.started.connect(self.worker.open)
        self.command.connect(self.worker.execute)
        self.stop_worker.connect(self.worker.close)
        self.worker.connected.connect(self.connected)
        self.worker.readings.connect(self.update_readings)
        self.worker.setpoints.connect(self.update_setpoints)
        self.worker.current.connect(self.update_current)
        self.worker.output.connect(self.update_output)
        self.worker.monitor_state.connect(self.update_monitor)
        self.worker.status_message.connect(self.report)
        self.worker.failed.connect(self.failed)
        self.worker.operation_done.connect(self.operation_done)
        self.worker.finished.connect(self.io_thread.quit)
        self.io_thread.finished.connect(self.worker.deleteLater)
        self.io_thread.finished.connect(self.thread_ended)

    def start(self):
        self.io_thread.start()

    def shutdown(self):
        if self.running and not self.closing:
            self.closing = True
            self.update_controls()
            self.stop_worker.emit()

    @property
    def tab_title(self):
        model = f" · {self.model}" if self.model else ""
        alert = self.failure or any(
            channel.state in {"tripped", "unconfirmed"} for channel in self.channels.values()
        )
        return f"{self.port}{model}{' ⚠' if alert else ''}"

    def update_controls(self):
        for channel in self.channels.values():
            channel.set_controls(self.online and not self.busy and not self.closing)

    @pyqtSlot(str, int, object)
    def dispatch(self, action, channel, value):
        if self.online and not self.busy and not self.closing:
            self.busy = True
            self.update_controls()
            self.command.emit(action, channel, value)

    @pyqtSlot(object)
    def connected(self, identity):
        self.model = identity.model
        self.identity.setText(f"{self.model} · {self.port}")
        self.detail.setText(f"{self.detail.text()}    |    {identity.response}")
        self.online = True
        self.update_controls()
        self.updated.emit()
        self.report("设备已连接")

    @pyqtSlot(int, object)
    def update_readings(self, channel, readings):
        self.channels[channel].update_readings(readings)

    @pyqtSlot(int, object, object)
    def update_setpoints(self, channel, voltage, current):
        self.channels[channel].setpoints(voltage, current)

    @pyqtSlot(int, object)
    def update_current(self, channel, measured):
        self.channels[channel].set_current(measured)

    @pyqtSlot(int, bool)
    def update_output(self, channel, enabled):
        self.channels[channel].set_output(enabled)

    @pyqtSlot(int, str)
    def update_monitor(self, channel, state):
        self.channels[channel].set_monitor(state)
        self.update_controls()
        self.updated.emit()

    @pyqtSlot()
    def operation_done(self):
        self.busy = False
        self.update_controls()

    @pyqtSlot(str)
    def report(self, message):
        self.message.setText(message)
        self.notice.emit(f"{self.port} · {message}")

    @pyqtSlot(str)
    def failed(self, message):
        self.failure = True
        self.online = False
        self.identity.setText(f"{self.port} · {self.model or '设备'} · 通信中断")
        self.report(message)
        set_label_style(self.message, "alert")
        for channel in self.channels.values():
            channel.output.setText("输出状态未知")
            set_label_style(channel.output, "muted")
            if channel.state == "active":
                channel.set_monitor("interrupted")
        self.update_controls()
        self.updated.emit()

    @pyqtSlot()
    def thread_ended(self):
        self.running = False
        self.online = False
        self.update_controls()
        self.ended.emit()


class MainWindow(QMainWindow):
    def __init__(self, port_provider=list_ports.comports, worker_factory=DeviceWorker):
        super().__init__()
        self.port_provider = port_provider
        self.worker_factory = worker_factory
        self.devices = {}
        self.exiting = False
        self.setWindowTitle("IT6300 电源控制台")
        self.resize(1080, 755)
        self.setMinimumWidth(850)
        self.setStyleSheet(STYLESHEET)

        self.ports = QListWidget()
        self.ports.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.ports.setFixedHeight(70)
        self.ports.itemSelectionChanged.connect(self.update_connection_button)
        self.ports.itemDoubleClicked.connect(lambda _: self.connect_selected())
        self.baud = QComboBox()
        self.baud.addItems(["4800", "9600", "19200", "38400", "57600", "115200"])
        self.baud.setCurrentText("9600")
        self.parity = QComboBox()
        for name, value in (("无校验", serial.PARITY_NONE), ("偶校验", serial.PARITY_EVEN),
                            ("奇校验", serial.PARITY_ODD)):
            self.parity.addItem(name, value)
        self.terminator = QComboBox()
        self.terminator.addItem("LF", b"\n")
        self.terminator.addItem("CRLF", b"\r\n")
        self.flow = QCheckBox("RTS/CTS")
        self.connect_button = button("连接所选端口", self.connect_selected, "primary")
        self.port_status = label("", "muted")

        connection = card()
        settings = QGridLayout(connection)
        settings.setContentsMargins(14, 10, 14, 10)
        settings.setHorizontalSpacing(9)
        settings.addWidget(label("可用串口（Ctrl / Shift 多选）", "heading"), 0, 0, 1, 3)
        settings.addWidget(button("刷新串口", self.refresh_ports), 0, 3)
        settings.addWidget(self.ports, 1, 0, 1, 4)
        settings.addWidget(label("波特率", "muted"), 0, 4)
        settings.addWidget(label("校验", "muted"), 0, 5)
        settings.addWidget(label("发送结束符", "muted"), 0, 6)
        settings.addWidget(self.baud, 1, 4, alignment=Qt.AlignTop)
        settings.addWidget(self.parity, 1, 5, alignment=Qt.AlignTop)
        settings.addWidget(self.terminator, 1, 6, alignment=Qt.AlignTop)
        right = QVBoxLayout()
        right.addWidget(self.flow)
        right.addWidget(self.connect_button)
        settings.addLayout(right, 1, 7)
        settings.addWidget(self.port_status, 2, 0, 1, 8)
        settings.setColumnStretch(0, 1)

        content = QWidget()
        content.setObjectName("content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 12, 18, 10)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(label("IT6300 电源控制台", "title"))
        header.addStretch()
        self.disconnect_button = button("断开当前设备", self.disconnect_current)
        header.addWidget(self.disconnect_button)
        layout.addLayout(header)
        layout.addWidget(connection)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.update_disconnect_button)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_label = label("选择串口并连接设备", "muted")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_label)
        self.empty = empty
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.empty, 1)
        self.setCentralWidget(content)
        self.statusBar().setSizeGripEnabled(False)
        self.refresh_ports()
        self.update_tabs()

    def refresh_ports(self):
        selected = {item.data(Qt.UserRole) for item in self.ports.selectedItems()}
        self.ports.clear()
        try:
            ports = sorted(self.port_provider())
        except OSError as error:
            self.port_status.setText(f"枚举串口失败（{error}）")
            self.update_connection_button()
            return
        for port in ports:
            panel = self.devices.get(port.device)
            in_use = panel is not None and panel.running
            name = port.description or port.device
            item = QListWidgetItem(f"{port.device}  ·  {name}{'  ·  已占用' if in_use else ''}")
            item.setData(Qt.UserRole, port.device)
            if in_use:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
            self.ports.addItem(item)
            if not in_use and port.device in selected:
                item.setSelected(True)
        count = sum(panel.running for panel in self.devices.values())
        self.port_status.setText(f"检测到 {len(ports)} 个串口 · 当前占用 {count} 个"
                                 if ports else "未检测到串口，可插入适配器后刷新")
        self.update_connection_button()

    def update_connection_button(self):
        self.connect_button.setEnabled(not self.exiting and bool(self.ports.selectedItems()))

    def connect_selected(self):
        if self.exiting:
            return
        settings = SerialSettings(
            int(self.baud.currentText()), self.parity.currentData(),
            self.flow.isChecked(), self.terminator.currentData(),
        )
        for item in self.ports.selectedItems():
            port = item.data(Qt.UserRole)
            old = self.devices.get(port)
            if old is not None:
                if old.running:
                    continue
                self.remove_panel(old)
            panel = DevicePanel(port, settings, self.worker_factory)
            self.devices[port] = panel
            panel.notice.connect(self.statusBar().showMessage)
            panel.updated.connect(self.panel_updated)
            panel.ended.connect(self.panel_ended)
            self.tabs.addTab(panel, panel.tab_title)
            self.tabs.setCurrentWidget(panel)
            panel.start()
        self.refresh_ports()
        self.update_tabs()

    @pyqtSlot()
    def panel_updated(self):
        panel = self.sender()
        self.tabs.setTabText(self.tabs.indexOf(panel), panel.tab_title)

    @pyqtSlot()
    def panel_ended(self):
        panel = self.sender()
        if panel.removing or self.exiting:
            self.remove_panel(panel)
        self.refresh_ports()
        self.update_tabs()
        if self.exiting and not self.devices:
            QTimer.singleShot(0, self.close)

    def disconnect_current(self):
        panel = self.tabs.currentWidget()
        if panel is None:
            return
        if panel.running:
            panel.removing = True
            panel.shutdown()
        else:
            self.remove_panel(panel)
        self.update_tabs()

    def remove_panel(self, panel):
        del self.devices[panel.port]
        self.tabs.removeTab(self.tabs.indexOf(panel))
        panel.deleteLater()

    def update_disconnect_button(self):
        panel = self.tabs.currentWidget()
        self.disconnect_button.setEnabled(
            not self.exiting and panel is not None and not panel.closing
        )
        self.disconnect_button.setText(
            "关闭设备页" if panel is not None and not panel.running else "断开当前设备"
        )

    def update_tabs(self):
        self.tabs.setVisible(bool(self.devices))
        self.empty.setVisible(not self.devices)
        self.update_disconnect_button()

    def closeEvent(self, event):
        if not any(panel.running for panel in self.devices.values()):
            event.accept()
            return
        event.ignore()
        self.exiting = True
        self.centralWidget().setEnabled(False)
        for panel in list(self.devices.values()):
            if panel.running:
                panel.shutdown()
            else:
                self.remove_panel(panel)
