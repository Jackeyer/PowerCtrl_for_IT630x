from decimal import Decimal

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal, pyqtSlot

from .scpi import CHANNELS, PowerSupply, ProtocolError


MONITOR_INTERVAL_MS = 400


class DeviceWorker(QObject):
    connected = pyqtSignal(object)
    readings = pyqtSignal(int, object)
    setpoints = pyqtSignal(int, object, object)
    current = pyqtSignal(int, object)
    output = pyqtSignal(int, bool)
    monitor_state = pyqtSignal(int, str)
    status_message = pyqtSignal(str)
    failed = pyqtSignal(str)
    operation_done = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, port, settings, supply_factory=PowerSupply):
        super().__init__()
        self.port = port
        self.settings = settings
        self.supply_factory = supply_factory
        self.supply = None
        self.thresholds = {}
        self.tripped = set()
        self.timers = {}
        for channel in CHANNELS:
            timer = QTimer(self)
            timer.setProperty("channel", channel)
            timer.setTimerType(Qt.PreciseTimer)
            timer.setInterval(MONITOR_INTERVAL_MS)
            timer.timeout.connect(self.poll)
            self.timers[channel] = timer
        self.closed = False

    @pyqtSlot()
    def open(self):
        try:
            self.supply = self.supply_factory(self.port, self.settings)
            identity = self.supply.identify()
            self.supply.write("SYST:REM")
        except (OSError, ProtocolError) as error:
            self.fail(str(error))
            return
        self.connected.emit(identity)

    @pyqtSlot(str, int, object)
    def execute(self, action, channel, value):
        if self.closed or self.supply is None:
            return
        try:
            if action == "start":
                self.start_monitor(channel, value)
            elif action == "stop":
                self.stop_monitor(channel)
            elif action == "reset":
                self.reset_trip(channel)
            else:
                self.control(action, channel, value)
        except (OSError, ProtocolError) as error:
            self.fail(f"CH{channel} · {error}")
        finally:
            self.operation_done.emit()

    def control(self, action, channel, value):
        if action == "output" and value and channel in self.tripped:
            self.status_message.emit(f"CH{channel} · 请先复位过流状态")
            return
        self.supply.select(channel)
        if action == "read":
            self.readings.emit(channel, self.supply.read_channel())
        elif action == "apply":
            voltage, limit_ma = value
            self.supply.write(f"APPL CH{channel},{voltage:f},{limit_ma / 1000:f}")
            actual_voltage, actual_limit = self.supply.setpoints()
            self.setpoints.emit(channel, actual_voltage, actual_limit)
            if (actual_voltage, actual_limit) == value:
                self.status_message.emit(f"CH{channel} · 设定已应用")
            else:
                self.status_message.emit(f"CH{channel} · 设备回读值与请求不同，已显示实际设定值")
        elif action == "output":
            actual = self.supply.set_output(value)
            self.output.emit(channel, actual)
            if actual != value:
                self.status_message.emit(f"CH{channel} · 设备未切换到请求的输出状态")

    def start_monitor(self, channel, threshold):
        if channel in self.tripped:
            self.status_message.emit(f"CH{channel} · 请先复位过流状态")
            return
        self.thresholds[channel] = Decimal(str(threshold))
        self.monitor_state.emit(channel, "active")
        self.timers[channel].start()
        self.sample(channel, self.thresholds[channel])

    def stop_monitor(self, channel):
        self.thresholds.pop(channel, None)
        self.timers[channel].stop()
        self.monitor_state.emit(channel, "idle")

    def reset_trip(self, channel):
        self.supply.select(channel)
        actual = self.supply.output_state()
        self.output.emit(channel, actual)
        if actual:
            self.status_message.emit(f"CH{channel} · 请关闭输出后再复位")
            return
        self.tripped.discard(channel)
        self.monitor_state.emit(channel, "idle")

    @pyqtSlot()
    def poll(self):
        channel = self.sender().property("channel")
        try:
            self.sample(channel, self.thresholds[channel])
        except (OSError, ProtocolError) as error:
            self.fail(f"CH{channel} · {error}")

    def sample(self, channel, threshold):
        self.supply.select(channel)
        measured = self.supply.current_ma()
        self.current.emit(channel, measured)
        if measured <= threshold:
            return

        self.tripped.add(channel)
        del self.thresholds[channel]
        self.timers[channel].stop()
        try:
            if self.supply.set_output(False) and self.supply.set_output(False):
                raise ProtocolError("设备仍回报输出开启")
        except (OSError, ProtocolError) as error:
            self.monitor_state.emit(channel, "unconfirmed")
            raise ProtocolError(
                f"过流 {measured:.3f} mA，关断未确认（{error}），请检查电源面板"
            ) from error
        self.output.emit(channel, False)
        self.monitor_state.emit(channel, "tripped")
        self.status_message.emit(
            f"CH{channel} · 过流 {measured:.3f} mA > {threshold:.3f} mA，已确认关断"
        )

    def fail(self, message):
        self.failed.emit(message)
        self.finish()

    @pyqtSlot()
    def close(self):
        if self.supply is not None:
            try:
                self.supply.write("SYST:LOC")
            except (OSError, ProtocolError) as error:
                self.status_message.emit(f"切回面板控制失败（{error}）")
        self.finish()

    def finish(self):
        if self.closed:
            return
        self.closed = True
        for timer in self.timers.values():
            timer.stop()
        self.thresholds.clear()
        if self.supply is not None:
            try:
                self.supply.close()
            except OSError as error:
                self.status_message.emit(f"关闭串口失败（{error}）")
            self.supply = None
        self.finished.emit()
