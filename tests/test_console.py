import os
import time
import unittest
from decimal import Decimal
from unittest.mock import patch

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from serial.tools.list_ports_common import ListPortInfo

from power_supply.window import MainWindow


class SimulatedSerial:
    def __init__(self, model):
        self.model = model
        self.channel = 1
        self.current = {1: "0.100", 2: "0.010", 3: "0.010"}
        self.voltage = {1: "5.000", 2: "3.300", 3: "1.800"}
        self.limit = {1: "1.000", 2: "1.000", 3: "1.000"}
        self.output = {1: True, 2: True, 3: True}
        self.commands = []
        self.ignore_off = False
        self.closed = False

    def reset_input_buffer(self):
        self.response = b""

    def read_until(self, expected, size):
        response = self.response
        self.response = b""
        return response

    def write(self, data):
        command = data.decode("ascii").strip()
        self.commands.append((self.channel, command, time.monotonic()))
        if command == "*IDN?":
            self.reply(f"ITECH,{self.model},TEST,1.0")
        elif command.startswith("INST:NSEL "):
            self.channel = int(command.split()[1])
        elif command == "INST:NSEL?":
            self.reply(self.channel)
        elif command == "CHAN:OUTP?":
            self.reply(int(self.output[self.channel]))
        elif command in {"CHAN:OUTP ON", "CHAN:OUTP OFF"}:
            if not (self.ignore_off and command.endswith("OFF")):
                self.output[self.channel] = command.endswith("ON")
        elif command == "MEAS:CURR?":
            self.reply(self.current[self.channel])
        elif command in {"MEAS:VOLT?", "VOLT?"}:
            self.reply(self.voltage[self.channel])
        elif command == "CURR?":
            self.reply(self.limit[self.channel])
        elif command.startswith("APPL "):
            channel, voltage, limit = command[5:].split(",")
            self.channel = int(channel[2:])
            self.voltage[self.channel] = voltage
            self.limit[self.channel] = limit
        elif command not in {"SYST:REM", "SYST:LOC"}:
            raise AssertionError(f"Unexpected SCPI command {command}")
        return len(data)

    def reply(self, value):
        self.response = f"{value}\r\n".encode("ascii")

    def close(self):
        self.closed = True

    def sample_times(self, channel):
        return [timestamp for ch, command, timestamp in self.commands
                if ch == channel and command == "MEAS:CURR?"]


class ConsoleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("QT_QPA_PLATFORM") is None:
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.supplies = {
            "COM81": SimulatedSerial("IT6322A"),
            "COM82": SimulatedSerial("IT6332B"),
        }
        patcher = patch("power_supply.scpi.serial.Serial", self.open_serial)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = MainWindow(lambda: [ListPortInfo(name) for name in self.supplies])
        self.addCleanup(self.close_console)
        self.window.show()
        self.window.ports.selectAll()
        self.window.connect_button.click()
        self.until(lambda: all(device.online for device in self.window.devices.values()))
        self.assertEqual(self.window.tabs.count(), 2)
        self.a = self.window.devices["COM81"]
        self.b = self.window.devices["COM82"]
        self.assertIn("IT6322A", self.window.tabs.tabText(0))
        self.assertIn("IT6332B", self.window.tabs.tabText(1))

    def open_serial(self, port, **settings):
        self.assertEqual(settings["baudrate"], 9600)
        self.assertEqual(settings["bytesize"], 8)
        self.assertEqual(settings["parity"], "N")
        self.assertEqual(settings["stopbits"], 1)
        return self.supplies[port]

    def until(self, predicate, seconds=2):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            QTest.qWait(10)
        self.assertTrue(predicate(), "Timed out waiting for the console")

    def close_console(self):
        self.window.close()
        self.until(lambda: all(link.closed for link in self.supplies.values()))
        self.until(lambda: not self.window.isVisible())

    def test_monitors_multiple_ports_and_channels_and_trips_only_above_threshold(self):
        a, b = self.supplies.values()
        for channel in (self.a.channels[1], self.a.channels[2], self.b.channels[1]):
            channel.monitor_button.click()
            self.until(lambda: channel.state == "active" and channel.monitor_button.isEnabled())

        self.until(lambda: all(len(link.sample_times(ch)) >= 2
                               for link, ch in ((a, 1), (a, 2), (b, 1))))
        for link, ch in ((a, 1), (a, 2), (b, 1)):
            first, second, *_ = link.sample_times(ch)
            self.assertAlmostEqual(second - first, 0.4, delta=0.12)
        self.assertTrue(a.output[1])
        self.assertEqual(self.a.channels[1].last_current, Decimal("100"))

        a.current[1] = "0.120"
        self.until(lambda: self.a.channels[1].state == "tripped")
        self.assertFalse(a.output[1])
        self.assertTrue(a.output[2])
        self.assertTrue(b.output[1])
        self.assertIn("120.000 mA", self.a.channels[1].monitor_status.text())
        self.assertFalse(self.a.channels[1].on_button.isEnabled())
        other_count = len(a.sample_times(2))
        self.until(lambda: len(a.sample_times(2)) > other_count)
        channel = self.a.channels[1]
        channel.reset_button.click()
        self.until(lambda: channel.state == "idle" and channel.on_button.isEnabled())
        self.assertFalse(a.output[1])

    def test_manual_controls_and_unconfirmed_trip(self):
        a = self.supplies["COM81"]
        channel = self.a.channels[3]
        channel.read_button.click()
        self.until(lambda: channel.last_current is not None and not self.a.busy)
        self.assertEqual(channel.voltage_set.value(), 1.8)
        channel.voltage_set.setValue(2.2)
        channel.limit_ma.setValue(85)
        channel.apply_button.click()
        self.until(lambda: not self.a.busy)
        self.assertEqual(Decimal(a.voltage[3]), Decimal("2.2"))
        self.assertEqual(Decimal(a.limit[3]), Decimal("0.085"))
        a.current[3] = "0.130"
        a.ignore_off = True
        channel.monitor_button.click()
        self.until(lambda: self.a.failure and not self.a.running)
        self.assertEqual(channel.state, "unconfirmed")
        self.assertIn("关断未确认", self.a.message.text())
        self.assertTrue(a.output[3])
        self.assertTrue(self.b.online)


if __name__ == "__main__":
    unittest.main()
