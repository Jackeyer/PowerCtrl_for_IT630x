from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import serial


CHANNELS = (1, 2, 3)


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class SerialSettings:
    baudrate: int = 9600
    parity: str = serial.PARITY_NONE
    rtscts: bool = False
    terminator: bytes = b"\n"


@dataclass(frozen=True)
class Identity:
    model: str
    response: str


@dataclass(frozen=True)
class ChannelReadings:
    voltage_set: Decimal
    limit_ma: Decimal
    voltage: Decimal
    current_ma: Decimal
    output_on: bool


class PowerSupply:
    def __init__(self, port, settings):
        self.terminator = settings.terminator
        self.link = serial.Serial(
            port=port,
            baudrate=settings.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=settings.parity,
            stopbits=serial.STOPBITS_ONE,
            rtscts=settings.rtscts,
            timeout=0.30,
            write_timeout=0.25,
        )

    def close(self):
        self.link.close()

    def write(self, command):
        message = command.encode("ascii") + self.terminator
        if self.link.write(message) != len(message):
            raise ProtocolError(f"{command} 写入不完整")

    def query(self, command):
        self.write(command)
        response = self.link.read_until(b"\n", size=512)
        if not response.endswith(b"\n"):
            raise ProtocolError(f"{command} 响应超时或报文不完整")
        try:
            value = response.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise ProtocolError(f"{command} 响应含非 ASCII 字节") from error
        if not value:
            raise ProtocolError(f"{command} 收到空响应")
        return value

    def identify(self):
        self.link.reset_input_buffer()
        response = self.query("*IDN?")
        parts = [part.strip() for part in response.split(",")]
        if len(parts) < 2 or not all(parts[:2]):
            raise ProtocolError(f"*IDN? 返回的仪器标识无效（{response}）")
        return Identity(parts[1], response)

    def numeric(self, command):
        response = self.query(command)
        try:
            value = Decimal(response)
        except InvalidOperation as error:
            raise ProtocolError(f"{command} 返回的数值无效（{response}）") from error
        if not value.is_finite() or abs(value) >= 1_000_000:
            raise ProtocolError(f"{command} 返回的数值无效（{response}）")
        return value

    def select(self, channel):
        if channel not in CHANNELS:
            raise ValueError(f"无效通道 CH{channel}")
        self.write(f"INST:NSEL {channel}")
        selected = self.numeric("INST:NSEL?")
        if selected != channel:
            raise ProtocolError(f"选择 CH{channel} 失败，设备回报通道 {selected}")

    def current_ma(self):
        return self.numeric("MEAS:CURR?") * 1000

    def output_state(self):
        response = self.query("CHAN:OUTP?").upper()
        if response in {"0", "OFF"}:
            return False
        if response in {"1", "ON"}:
            return True
        raise ProtocolError(f"CHAN:OUTP? 返回的状态无效（{response}）")

    def set_output(self, enabled):
        self.write("CHAN:OUTP ON" if enabled else "CHAN:OUTP OFF")
        return self.output_state()

    def setpoints(self):
        return self.numeric("VOLT?"), self.numeric("CURR?") * 1000

    def read_channel(self):
        voltage_set, limit_ma = self.setpoints()
        return ChannelReadings(
            voltage_set, limit_ma, self.numeric("MEAS:VOLT?"),
            self.current_ma(), self.output_state(),
        )
