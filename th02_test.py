#!/usr/bin/env python3
"""
TH02 Temperature and Humidity Sensor Test Utility
Interfaces with a HopeRF TH02 sensor over I2C at address 0x40.
"""

import sys
import time
import argparse
import json
import math

# Try importing fcntl and os for zero-dependency Linux I2C
# (standard in Linux Python libraries)
FCNTL_AVAILABLE = False
try:
    import fcntl
    import os
    FCNTL_AVAILABLE = True
except ImportError:
    pass

# Try importing smbus2 as a backup / alternative
SMBUS2_AVAILABLE = False
try:
    import smbus2
    SMBUS2_AVAILABLE = True
except ImportError:
    pass

# Try importing smbus as a secondary backup
SMBUS_AVAILABLE = False
try:
    import smbus
    SMBUS_AVAILABLE = True
except ImportError:
    pass

# Constants
I2C_SLAVE = 0x0703  # ioctl command to set I2C slave address
DEFAULT_BUS = 1
DEFAULT_ADDRESS = 0x40

# Registers
REG_STATUS = 0x00
REG_DATA_H = 0x01
REG_DATA_L = 0x02
REG_CONFIG = 0x03

# Commands
CMD_MEASURE_HUMI = 0x01
CMD_MEASURE_TEMP = 0x11

def calculate_dew_point(temp_c: float, humidity: float) -> float:
    """Calculates the dew point in Celsius using the Magnus-Tetens formula."""
    if humidity <= 0:
        return -100.0  # Avoid log of 0 or negative
    a = 17.27
    b = 237.7
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity / 100.0)
    return (b * alpha) / (a - alpha)

class TH02:
    def __init__(self, bus_num: int = DEFAULT_BUS, address: int = DEFAULT_ADDRESS, method: str = "auto"):
        self.bus_num = bus_num
        self.address = address
        self.method = method.lower()
        self.fd = None
        self.bus = None
        
        self._connect()

    def _connect(self):
        """Initializes the connection using the specified or auto-detected method."""
        errors = {}

        # 1. Raw fcntl (Unix/Linux direct I2C file descriptor) - Zero external dependencies
        if self.method in ("auto", "raw", "fcntl") and FCNTL_AVAILABLE:
            dev_path = f"/dev/i2c-{self.bus_num}"
            try:
                self.fd = os.open(dev_path, os.O_RDWR)
                fcntl.ioctl(self.fd, I2C_SLAVE, self.address)
                self.method_used = "fcntl (Raw /dev/i2c-X)"
                return
            except PermissionError as pe:
                errors["fcntl"] = f"Permission denied for '{dev_path}'. Use sudo or add your user to the 'i2c' group."
            except FileNotFoundError as fnfe:
                errors["fcntl"] = f"I2C device path '{dev_path}' not found. Make sure I2C is enabled."
            except Exception as e:
                errors["fcntl"] = str(e)

        # 2. smbus2 Library
        if self.method in ("auto", "smbus2") and SMBUS2_AVAILABLE:
            try:
                self.bus = smbus2.SMBus(self.bus_num)
                self.method_used = "smbus2"
                return
            except Exception as e:
                errors["smbus2"] = str(e)

        # 3. smbus Library
        if self.method in ("auto", "smbus") and SMBUS_AVAILABLE:
            try:
                self.bus = smbus.SMBus(self.bus_num)
                self.method_used = "smbus"
                return
            except Exception as e:
                errors["smbus"] = str(e)

        # If we reached here, initialization failed
        if not FCNTL_AVAILABLE and not SMBUS2_AVAILABLE and not SMBUS_AVAILABLE:
            raise RuntimeError(
                "No I2C communication libraries are available. "
                "Ensure you are running on a Linux system with the 'fcntl' package "
                "or install the 'smbus2' python package (`pip install smbus2`)."
            )
            
        err_msg = "Failed to open I2C bus connection.\n"
        for meth, err in errors.items():
            err_msg += f" - Method '{meth}': {err}\n"
        raise RuntimeError(err_msg)

    def _write_reg(self, reg: int, val: int):
        """Writes a byte value to the specified register."""
        if self.fd is not None:
            os.write(self.fd, bytes([reg, val]))
        elif self.bus is not None:
            self.bus.write_byte_data(self.address, reg, val)

    def _read_status(self) -> int:
        """Reads the status register value."""
        if self.fd is not None:
            os.write(self.fd, bytes([REG_STATUS]))
            return os.read(self.fd, 1)[0]
        elif self.bus is not None:
            return self.bus.read_byte_data(self.address, REG_STATUS)
        raise RuntimeError("Not connected.")

    def _wait_for_conversion(self):
        """Polls the status register until the conversion is complete."""
        start_time = time.time()
        while True:
            status = self._read_status()
            # Bit 0 (RDY) of STATUS register is 0 when conversion is complete
            if (status & 0x01) == 0:
                break
            if time.time() - start_time > 1.0:
                raise RuntimeError("Timeout waiting for sensor conversion.")
            time.sleep(0.01)

    def _read_data_block(self) -> bytes:
        """Reads 3 bytes starting from REG_STATUS (STATUS, DATA_H, DATA_L)."""
        if self.fd is not None:
            os.write(self.fd, bytes([REG_STATUS]))
            return os.read(self.fd, 3)
        elif self.bus is not None:
            if self.method_used == "smbus2":
                # Use i2c_rdwr for repeated-start block read
                write_msg = smbus2.i2c_msg.write(self.address, [REG_STATUS])
                read_msg = smbus2.i2c_msg.read(self.address, 3)
                self.bus.i2c_rdwr(write_msg, read_msg)
                return bytes(list(read_msg))
            else:
                # Fallback to standard block read
                return bytes(self.bus.read_i2c_block_data(self.address, REG_STATUS, 3))
        raise RuntimeError("Not connected.")

    def read_temperature(self) -> float:
        """Triggers and reads temperature in Celsius."""
        self._write_reg(REG_CONFIG, CMD_MEASURE_TEMP)
        self._wait_for_conversion()
        data = self._read_data_block()
        
        # Reconstruct 16-bit raw value
        raw_val = (data[1] << 8) | data[2]
        # Shift right by 2 (14-bit data)
        raw_val >>= 2
        
        # Temp (C) = (Value / 32) - 50
        return (raw_val / 32.0) - 50.0

    def read_humidity(self, temperature_c: float = None, compensate: bool = True) -> float:
        """Triggers and reads relative humidity in percentage.
        Optionally applies temperature compensation for higher accuracy.
        """
        self._write_reg(REG_CONFIG, CMD_MEASURE_HUMI)
        self._wait_for_conversion()
        data = self._read_data_block()

        # Reconstruct 16-bit raw value
        raw_val = (data[1] << 8) | data[2]
        # Shift right by 4 (12-bit data)
        raw_val >>= 4

        # Linear humidity: RH = (Value / 16) - 24
        rh_linear = (raw_val / 16.0) - 24.0

        # Perform linearization calibration
        # RH_linear = RH_val - (RH_val^2 * A2 + RH_val * A1 + A0)
        A0 = -4.7844
        A1 = 0.4008
        A2 = -0.00393
        rh_calibrated = rh_linear - (rh_linear * rh_linear * A2 + rh_linear * A1 + A0)

        # Temperature compensation (calibrated around 30 °C baseline)
        if compensate:
            if temperature_c is None:
                # If temperature isn't passed, measure it on-the-fly
                temperature_c = self.read_temperature()
            
            Q0 = 0.1973
            Q1 = 0.00237
            rh_compensated = rh_calibrated + (temperature_c - 30.0) * (rh_calibrated * Q1 + Q0)
            result = rh_compensated
        else:
            result = rh_calibrated

        # Boundary checks
        return max(0.0, min(100.0, result))

    def read(self, compensate: bool = True):
        """Convenience method to read both temperature (C) and humidity (%)."""
        temp_c = self.read_temperature()
        humidity = self.read_humidity(temperature_c=temp_c, compensate=compensate)
        return temp_c, humidity

    def close(self):
        """Closes opened handles."""
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
            self.bus = None

def main():
    parser = argparse.ArgumentParser(
        description="TH02 I2C Temperature & Humidity Sensor Utility",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-b", "--bus", type=int, default=DEFAULT_BUS, help="I2C bus number")
    parser.add_argument("-a", "--address", type=str, default=f"0x{DEFAULT_ADDRESS:02x}", help="I2C address in hex (e.g. 0x40)")
    parser.add_argument("-m", "--method", type=str, choices=["auto", "fcntl", "smbus2", "smbus"], default="auto",
                        help="Connection method to use")
    parser.add_argument("-l", "--loop", type=float, metavar="INTERVAL", help="Continuously read sensor every INTERVAL seconds")
    parser.add_argument("-f", "--fahrenheit", action="store_true", help="Display temperature in Fahrenheit")
    parser.add_argument("-k", "--kelvin", action="store_true", help="Display temperature in Kelvin")
    parser.add_argument("-j", "--json", action="store_true", help="Output values as JSON format")
    parser.add_argument("--no-comp", action="store_true", help="Disable temperature compensation for humidity")

    args = parser.parse_args()

    # Parse address from hex string
    try:
        address_val = int(args.address, 16)
    except ValueError:
        print(f"Error: Invalid hex address format: '{args.address}'", file=sys.stderr)
        sys.exit(1)

    # Initialize sensor
    try:
        sensor = TH02(bus_num=args.bus, address=address_val, method=args.method)
    except Exception as e:
        print(f"Error connecting to TH02 sensor:\n{e}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print("TH02 I2C Sensor Utility")
        print("=======================")
        print(f"I2C Bus:        /dev/i2c-{args.bus}")
        print(f"I2C Address:    0x{address_val:02X}")
        print(f"Method Used:    {sensor.method_used}")
        print(f"Compensation:   {'Disabled' if args.no_comp else 'Enabled'}")
        print("-----------------------")

    try:
        while True:
            try:
                temp_c, humidity = sensor.read(compensate=not args.no_comp)
                dew_point_c = calculate_dew_point(temp_c, humidity)

                # Format Temperature
                if args.fahrenheit:
                    temp_val = temp_c * 9.0 / 5.0 + 32.0
                    temp_unit = "°F"
                    dp_val = dew_point_c * 9.0 / 5.0 + 32.0
                    dp_unit = "°F"
                elif args.kelvin:
                    temp_val = temp_c + 273.15
                    temp_unit = "K"
                    dp_val = dew_point_c + 273.15
                    dp_unit = "K"
                else:
                    temp_val = temp_c
                    temp_unit = "°C"
                    dp_val = dew_point_c
                    dp_unit = "°C"

                if args.json:
                    output = {
                        "temperature": round(temp_val, 2),
                        "unit": temp_unit,
                        "humidity_percent": round(humidity, 2),
                        "dew_point": round(dp_val, 2),
                        "raw_celsius": round(temp_c, 2)
                    }
                    print(json.dumps(output))
                else:
                    print(f"Temperature:    {temp_val:6.2f} {temp_unit}")
                    print(f"Humidity:       {humidity:6.2f} %RH")
                    print(f"Dew Point:      {dp_val:6.2f} {dp_unit}")
                    if args.loop:
                        print("-----------------------")

            except Exception as e:
                if args.json:
                    print(json.dumps({"error": str(e)}))
                else:
                    print(f"Error reading sensor: {e}", file=sys.stderr)
                if not args.loop:
                    sys.exit(1)

            if args.loop is None:
                break
            time.sleep(args.loop)

    except KeyboardInterrupt:
        if not args.json:
            print("\nExiting TH02 test utility.")
    finally:
        sensor.close()

if __name__ == "__main__":
    main()
