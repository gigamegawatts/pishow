#!/usr/bin/env python3
"""
SHT30 Temperature and Humidity Sensor Test Utility
Interfaces with an SHT30 sensor over I2C to read temperature and humidity.
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
DEFAULT_ADDRESS = 0x45

# SHT30 Command: Clock stretching disabled, High repeatability
CMD_MEAS_HIGH_REP = bytes([0x24, 0x00])

def crc8(data: bytes) -> int:
    """Calculates the SHT3x CRC-8 checksum.
    Polynomial: x^8 + x^5 + x^4 + 1 (0x31)
    Initialization: 0xFF
    """
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x31
            else:
                crc <<= 1
            crc &= 0xFF
    return crc

def calculate_dew_point(temp_c: float, humidity: float) -> float:
    """Calculates the dew point in Celsius using the Magnus-Tetens formula."""
    if humidity <= 0:
        return -100.0  # Avoid log of 0 or negative
    a = 17.27
    b = 237.7
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity / 100.0)
    return (b * alpha) / (a - alpha)

class SHT30:
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

    def read(self, verify_crc: bool = True):
        """Triggers SHT30 conversion and returns (temp_c, humidity)."""
        if self.fd is not None:
            # Raw file descriptor read/write
            try:
                os.write(self.fd, CMD_MEAS_HIGH_REP)
                # SHT30 high repeatability conversion takes max 15ms. Sleep 50ms to be safe.
                time.sleep(0.05)
                data = os.read(self.fd, 6)
            except Exception as e:
                raise RuntimeError(f"Raw I2C transfer failed: {e}")
        elif self.bus is not None:
            # Using smbus/smbus2. Since standard smbus read_i2c_block_data requires a command
            # register which SHT30 doesn't use for reads, we use raw I2C messages if smbus2 is used,
            # or try block data as a fallback.
            try:
                if self.method_used == "smbus2":
                    # Send write message
                    write_msg = smbus2.i2c_msg.write(self.address, list(CMD_MEAS_HIGH_REP))
                    self.bus.i2c_rdwr(write_msg)
                    time.sleep(0.05)
                    # Read 6 bytes
                    read_msg = smbus2.i2c_msg.read(self.address, 6)
                    self.bus.i2c_rdwr(read_msg)
                    data = bytes(list(read_msg))
                else:
                    # Legacy smbus fallback
                    self.bus.write_i2c_block_data(self.address, CMD_MEAS_HIGH_REP[0], [CMD_MEAS_HIGH_REP[1]])
                    time.sleep(0.05)
                    data = bytes(self.bus.read_i2c_block_data(self.address, 0x00, 6))
            except Exception as e:
                raise RuntimeError(f"SMBus transfer failed: {e}")
        else:
            raise RuntimeError("Not connected to I2C bus.")

        if len(data) < 6:
            raise RuntimeError(f"Received incomplete data from sensor: {len(data)} bytes, expected 6.")

        # Parse data
        temp_bytes = data[0:2]
        temp_crc = data[2]
        humi_bytes = data[3:5]
        humi_crc = data[5]

        # Verify CRC checks
        if verify_crc:
            calc_temp_crc = crc8(temp_bytes)
            calc_humi_crc = crc8(humi_bytes)
            if calc_temp_crc != temp_crc:
                raise ValueError(
                    f"Temperature CRC mismatch! Expected: 0x{temp_crc:02X}, Calculated: 0x{calc_temp_crc:02X}"
                )
            if calc_humi_crc != humi_crc:
                raise ValueError(
                    f"Humidity CRC mismatch! Expected: 0x{humi_crc:02X}, Calculated: 0x{calc_humi_crc:02X}"
                )

        # Math conversions
        raw_temp = (temp_bytes[0] << 8) | temp_bytes[1]
        raw_humi = (humi_bytes[0] << 8) | humi_bytes[1]

        temp_c = -45.0 + 175.0 * (raw_temp / 65535.0)
        humidity = 100.0 * (raw_humi / 65535.0)
        humidity = max(0.0, min(100.0, humidity))

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
        description="SHT30 I2C Temperature & Humidity Sensor Utility",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-b", "--bus", type=int, default=DEFAULT_BUS, help="I2C bus number")
    parser.add_argument("-a", "--address", type=str, default=f"0x{DEFAULT_ADDRESS:02x}", help="I2C address in hex (e.g. 0x44)")
    parser.add_argument("-m", "--method", type=str, choices=["auto", "fcntl", "smbus2", "smbus"], default="auto",
                        help="Connection method to use")
    parser.add_argument("-l", "--loop", type=float, metavar="INTERVAL", help="Continuously read sensor every INTERVAL seconds")
    parser.add_argument("-f", "--fahrenheit", action="store_true", help="Display temperature in Fahrenheit")
    parser.add_argument("-k", "--kelvin", action="store_true", help="Display temperature in Kelvin")
    parser.add_argument("-j", "--json", action="store_true", help="Output values as JSON format")
    parser.add_argument("--no-crc", action="store_true", help="Disable CRC-8 verification")
    
    args = parser.parse_args()

    # Parse address from hex string
    try:
        address_val = int(args.address, 16)
    except ValueError:
        print(f"Error: Invalid hex address format: '{args.address}'", file=sys.stderr)
        sys.exit(1)

    # Initialize sensor
    try:
        sensor = SHT30(bus_num=args.bus, address=address_val, method=args.method)
    except Exception as e:
        print(f"Error connecting to SHT30 sensor:\n{e}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print("SHT30 I2C Sensor Utility")
        print("========================")
        print(f"I2C Bus:        /dev/i2c-{args.bus}")
        print(f"I2C Address:    0x{address_val:02X}")
        print(f"Method Used:    {sensor.method_used}")
        print(f"CRC Check:      {'Disabled' if args.no_crc else 'Enabled'}")
        print("------------------------")

    try:
        while True:
            try:
                temp_c, humidity = sensor.read(verify_crc=not args.no_crc)
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
                        print("------------------------")

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
            print("\nExiting SHT30 test utility.")
    finally:
        sensor.close()

if __name__ == "__main__":
    main()
