#!/usr/bin/env python3
import os
import sys
import random
import time
import tkinter as tk
import urllib.request
import urllib.parse
import json
import threading
import math
from datetime import datetime
from PIL import Image, ImageTk, ImageOps, ImageDraw

# Try importing fcntl for direct I2C (standard on Linux)
FCNTL_AVAILABLE = False
try:
    import fcntl
    FCNTL_AVAILABLE = True
except ImportError:
    pass

# Try importing smbus2
SMBUS2_AVAILABLE = False
try:
    import smbus2
    SMBUS2_AVAILABLE = True
except ImportError:
    pass

# Try importing smbus
SMBUS_AVAILABLE = False
try:
    import smbus
    SMBUS_AVAILABLE = True
except ImportError:
    pass

# ==========================================
# CONFIGURATION
# ==========================================

# --- GENERAL CONFIGURATION ---
OUTLINE_WIDTH = 2               # Width of the black outline in pixels (0 to disable)

# --- SLIDESHOW CONFIGURATION ---
PHOTO_DIR = "~/photos"          # Directory containing images
DURATION = 30.0                 # Slideshow timer per image (seconds)
SCALING_MODE = "fit"            # Options: "fit" (aspect ratio), "fill" (crop), "stretch" (distort)
SHOW_FILENAME = True            # Display filename overlay without extension
FONT_SIZE = 24                  # Filename text size
FONT_FAMILY = "DejaVu Sans"     # Filename text font family
FONT_COLOR = "white"            # Filename text color
SHUFFLE = True                 # Set to True to randomize slideshow order

# --- CLOCK CONFIGURATION ---
SHOW_TIME = True
TIME_FONT_FAMILY = "DejaVu Sans"
TIME_FONT_SIZE = 64
TIME_FONT_COLOR = "white"

# --- WEATHER CONFIGURATION ---
SHOW_WEATHER = True
WEATHER_LOCATION = "Toronto"    # City name (e.g., "Chicago") or "lat,lon" (e.g., "40.7128,-74.0060")
WEATHER_FONT_FAMILY = "DejaVu Sans"
WEATHER_FONT_SIZE = 36
WEATHER_FONT_COLOR = "white"
WEATHER_UNIT = "celsius"      # Options: "fahrenheit", "celsius"
WEATHER_INTERVAL_MINS = 15       # Fetch current weather every 15 minutes

# --- SHT30 CONFIGURATION ---
SHOW_SHT30 = True               # Enable/disable SHT30 sensor display
SHT30_I2C_ADDRESS = 0x45        # SHT30 I2C address (usually 0x44 or 0x45)
SHT30_I2C_BUS = 1               # I2C bus number
SHT30_TEMP_UNIT = "celsius"   # Options: "celsius", "fahrenheit"
SHT30_FONT_FAMILY = "DejaVu Sans"
SHT30_FONT_SIZE = 36
SHT30_FONT_COLOR = "cyan"
SHT30_INTERVAL_SECS = 10        # Read the sensor every 10 seconds
# ==========================================

# Constants for SHT30 I2C
I2C_SLAVE = 0x0703
CMD_MEAS_HIGH_REP = bytes([0x24, 0x00])

def crc8(data: bytes) -> int:
    """Calculates SHT3x CRC-8 checksum."""
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

class SHT30Reader:
    def __init__(self, bus_num=1, address=0x44):
        self.bus_num = bus_num
        self.address = address
        self.fd = None
        self.bus = None
        self.method_used = None
        self._connect()

    def _connect(self):
        errors = []
        if FCNTL_AVAILABLE:
            dev_path = f"/dev/i2c-{self.bus_num}"
            try:
                self.fd = os.open(dev_path, os.O_RDWR)
                fcntl.ioctl(self.fd, I2C_SLAVE, self.address)
                self.method_used = "fcntl"
                return
            except Exception as e:
                errors.append(f"fcntl: {e}")
        if SMBUS2_AVAILABLE:
            try:
                self.bus = smbus2.SMBus(self.bus_num)
                self.method_used = "smbus2"
                return
            except Exception as e:
                errors.append(f"smbus2: {e}")
        if SMBUS_AVAILABLE:
            try:
                self.bus = smbus.SMBus(self.bus_num)
                self.method_used = "smbus"
                return
            except Exception as e:
                errors.append(f"smbus: {e}")
        raise RuntimeError(f"SHT30 init failed. Errors: {errors}")

    def read(self):
        if self.fd is not None:
            try:
                os.write(self.fd, CMD_MEAS_HIGH_REP)
                time.sleep(0.05)
                data = os.read(self.fd, 6)
            except Exception as e:
                raise RuntimeError(f"Raw I2C write/read failed: {e}")
        elif self.bus is not None:
            try:
                if self.method_used == "smbus2":
                    write_msg = smbus2.i2c_msg.write(self.address, list(CMD_MEAS_HIGH_REP))
                    self.bus.i2c_rdwr(write_msg)
                    time.sleep(0.05)
                    read_msg = smbus2.i2c_msg.read(self.address, 6)
                    self.bus.i2c_rdwr(read_msg)
                    data = bytes(list(read_msg))
                else:
                    self.bus.write_i2c_block_data(self.address, CMD_MEAS_HIGH_REP[0], [CMD_MEAS_HIGH_REP[1]])
                    time.sleep(0.05)
                    data = bytes(self.bus.read_i2c_block_data(self.address, 0x00, 6))
            except Exception as e:
                raise RuntimeError(f"SMBus read failed: {e}")
        else:
            raise RuntimeError("Not connected.")

        if len(data) < 6:
            raise RuntimeError(f"Incomplete SHT30 data: read {len(data)} bytes, expected 6.")

        if crc8(data[0:2]) != data[2] or crc8(data[3:5]) != data[5]:
            raise ValueError("SHT30 CRC verification failed.")

        raw_temp = (data[0] << 8) | data[1]
        raw_humi = (data[3] << 8) | data[4]

        temp_c = -45.0 + 175.0 * (raw_temp / 65535.0)
        humidity = 100.0 * (raw_humi / 65535.0)
        humidity = max(0.0, min(100.0, humidity))

        return temp_c, humidity

    def close(self):
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


class PiSlideshow:
    def __init__(self, root):
        self.root = root
        self.root.title("Pi Photo Slideshow")
        self.root.configure(bg='black')
        
        # Configure full screen and hide cursor
        self.root.attributes('-fullscreen', True)
        self.root.config(cursor="none")
        self.root.focus_force()
        
        # Create canvas for rendering centered images and overlays
        self.canvas = tk.Canvas(self.root, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Initialize paths and variables
        self.photo_dir = os.path.expanduser(PHOTO_DIR)
        self.files = []
        self.current_index = -1
        self.paused = False
        self.timer_id = None
        
        # Overlay references
        self.current_img_ref = None          # Keeps main photo out of Garbage Collection
        self.current_weather_icon_ref = None # Keeps weather icon out of Garbage Collection
        
        # Weather data state
        self.weather_lat = None
        self.weather_lon = None
        self.weather_temp = None
        self.weather_condition = None
        self.weather_unit_symbol = ""
        self.weather_loaded = False
        
        # Key bindings for interaction
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<q>", lambda e: self.root.destroy())
        self.root.bind("<space>", lambda e: self.next_photo())
        self.root.bind("<Right>", lambda e: self.next_photo())
        self.root.bind("<Left>", lambda e: self.prev_photo())
        self.root.bind("<p>", lambda e: self.toggle_pause())
        
        # Dynamically redraw image when layout changes (e.g. screen resolution changes)
        self.root.bind("<Configure>", self.on_resize)
        
        # SHT30 sensor state
        self.sht30_temp = None
        self.sht30_humi = None
        self.sht30_loaded = False
        self.sht30_sensor = None

        # Start scanning directory and slideshow loop
        self.load_photos()
        self.show_next()
        
        # Start overlay update loops
        self.start_clock_updates()
        self.start_weather_updates()
        if SHOW_SHT30:
            self.start_sht30_updates()
        
    def load_photos(self):
        """Scans the directory for valid image files."""
        valid_extensions = ('.jpg', '.jpeg', '.png', '.webp')
        self.files = []
        if os.path.exists(self.photo_dir):
            try:
                for entry in os.scandir(self.photo_dir):
                    if entry.is_file() and entry.name.lower().endswith(valid_extensions):
                        self.files.append(entry.path)
            except Exception as e:
                print(f"Error reading directory {self.photo_dir}: {e}", file=sys.stderr)
        
        if SHUFFLE:
            random.shuffle(self.files)
        else:
            self.files.sort()

    def check_and_update_photos(self):
        """Scans the photo directory, synchronizing self.files with disk.
        Returns True if the current photo was deleted, False otherwise.
        """
        valid_extensions = ('.jpg', '.jpeg', '.png', '.webp')
        if not os.path.exists(self.photo_dir):
            if self.files:
                self.files = []
                self.current_index = -1
            return False

        try:
            disk_files = []
            for entry in os.scandir(self.photo_dir):
                if entry.is_file() and entry.name.lower().endswith(valid_extensions):
                    disk_files.append(entry.path)
        except Exception as e:
            print(f"Error scanning directory {self.photo_dir}: {e}", file=sys.stderr)
            return False

        disk_set = set(disk_files)
        current_set = set(self.files)

        if disk_set == current_set:
            return False

        # Find current file path before modification
        current_file = None
        if 0 <= self.current_index < len(self.files):
            current_file = self.files[self.current_index]

        deleted = current_set - disk_set
        added = disk_set - current_set

        # Remove deleted files
        if deleted:
            self.files = [f for f in self.files if f in disk_set]

        # Add new files
        if added:
            if SHUFFLE:
                # Insert added files at random positions
                for f in added:
                    insert_idx = random.randint(0, len(self.files))
                    self.files.insert(insert_idx, f)
            else:
                self.files.extend(added)
                self.files.sort()

        # Update current_index to match the same current_file if it still exists
        current_deleted = False
        if current_file:
            if current_file in self.files:
                self.current_index = self.files.index(current_file)
            else:
                current_deleted = True
                if not self.files:
                    self.current_index = -1
                else:
                    self.current_index = self.current_index % len(self.files)
        else:
            # If current_index was invalid (e.g. -1 because files was empty, but now we have files)
            if self.files and self.current_index < 0:
                self.current_index = -1

        return current_deleted

    def get_dimensions(self):
        """Helper to get actual screen/window dimensions."""
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 1 or h <= 1:
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()
        return w, h
        
    def on_resize(self, event=None):
        """Redraws the current image and overlays if the window sizes change."""
        if 0 <= self.current_index < len(self.files):
            self.display_photo(self.files[self.current_index])
            
    def create_text_with_outline(self, x, y, **kwargs):
        """Draws text on the canvas with a black outline of configurable width."""
        if OUTLINE_WIDTH > 0:
            outline_kwargs = kwargs.copy()
            outline_kwargs["fill"] = "black"
            for dx in range(-OUTLINE_WIDTH, OUTLINE_WIDTH + 1):
                for dy in range(-OUTLINE_WIDTH, OUTLINE_WIDTH + 1):
                    if dx == 0 and dy == 0:
                        continue
                    self.canvas.create_text(x + dx, y + dy, **outline_kwargs)
        return self.canvas.create_text(x, y, **kwargs)

    def display_photo(self, filepath):
        """Loads, scales, and displays a single image along with all overlays."""
        self.canvas.delete("all")
        w, h = self.get_dimensions()
        
        try:
            # Load and transpose image based on EXIF tag (corrects mobile photo orientation)
            img = Image.open(filepath)
            img = ImageOps.exif_transpose(img)
            
            # Scale image based on mode
            img = self.scale_image(img, w, h, SCALING_MODE)
            
            # Render and cache for canvas compatibility
            self.current_img_ref = ImageTk.PhotoImage(img)
            self.canvas.create_image(w // 2, h // 2, image=self.current_img_ref, anchor="center")
            
            # 1. Filename overlay
            if SHOW_FILENAME:
                filename = os.path.splitext(os.path.basename(filepath))[0]
                font_spec = (FONT_FAMILY, FONT_SIZE, "bold")
                text_y = h - 60
                
                self.create_text_with_outline(w // 2, text_y, text=filename, fill=FONT_COLOR, font=font_spec, anchor="center")
                
        except Exception as e:
            # Gracefully handle file reading / scaling errors on screen
            err_msg = f"Error loading image:\n{os.path.basename(filepath)}\n{str(e)}"
            self.create_text_with_outline(w // 2, h // 2, text=err_msg, fill="red", font=(FONT_FAMILY, 20), justify="center", anchor="center")
            
        # Draw pause overlay if active
        if self.paused:
            self.draw_pause_indicator(w)
            
        # 2. Draw live overlays on top of the newly drawn photo
        if SHOW_TIME:
            self.draw_clock(w, h)
        if SHOW_WEATHER:
            self.draw_weather(w, h)
        if SHOW_SHT30:
            self.draw_sht30(w, h)
            
    def scale_image(self, img, target_w, target_h, mode):
        """Resizes the image according to chosen configuration."""
        img_w, img_h = img.size
        
        if mode == "stretch":
            return img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
        img_ratio = img_w / img_h
        target_ratio = target_w / target_h
        
        if mode == "fit":
            if img_ratio > target_ratio:
                new_w = target_w
                new_h = int(target_w / img_ratio)
            else:
                new_h = target_h
                new_w = int(target_h * img_ratio)
            return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
        elif mode == "fill":
            if img_ratio > target_ratio:
                new_h = target_h
                new_w = int(target_h * img_ratio)
                resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                left = (new_w - target_w) // 2
                return resized.crop((left, 0, left + target_w, target_h))
            else:
                new_w = target_w
                new_h = int(target_w / img_ratio)
                resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                top = (new_h - target_h) // 2
                return resized.crop((0, top, target_w, top + target_h))
                
        return img

    # ==========================================
    # CLOCK OVERLAY LOGIC
    # ==========================================
    def start_clock_updates(self):
        """Kicks off clock update interval loop."""
        if not SHOW_TIME:
            return
        w, h = self.get_dimensions()
        self.draw_clock(w, h)
        # Redraw clock every 10 seconds to ensure time is accurate
        self.root.after(10000, self.start_clock_updates)
        
    def draw_clock(self, w, h):
        """Draws/refreshes the clock in the top-left corner."""
        self.canvas.delete("clock")
        
        now = datetime.now()
        hour = now.hour % 12
        if hour == 0:
            hour = 12
        time_str = f"{hour}:{now.minute:02d}"
        
        x, y = 0,0
        font_spec = (TIME_FONT_FAMILY, TIME_FONT_SIZE, "bold")
        
        self.create_text_with_outline(x, y, text=time_str, fill=TIME_FONT_COLOR, font=font_spec, anchor="nw", tags="clock")

    # ==========================================
    # SHT30 OVERLAY LOGIC
    # ==========================================
    def start_sht30_updates(self):
        """Kicks off SHT30 sensor update loop."""
        if not SHOW_SHT30:
            return
        threading.Thread(target=self._fetch_sht30_thread, daemon=True).start()
        self.root.after(int(SHT30_INTERVAL_SECS * 1000), self.start_sht30_updates)

    def _fetch_sht30_thread(self):
        """Runs in background thread to read SHT30 sensor values."""
        try:
            if self.sht30_sensor is None:
                self.sht30_sensor = SHT30Reader(bus_num=SHT30_I2C_BUS, address=SHT30_I2C_ADDRESS)
            temp_c, humidity = self.sht30_sensor.read()
            self.root.after(0, self._apply_sht30, temp_c, humidity)
        except Exception as e:
            print(f"SHT30 sensor read error: {e}", file=sys.stderr)

    def _apply_sht30(self, temp_c, humidity):
        """Updates SHT30 values and redraws the display."""
        self.sht30_temp = temp_c
        self.sht30_humi = humidity
        self.sht30_loaded = True
        w, h = self.get_dimensions()
        self.draw_sht30(w, h)

    def draw_sht30(self, w, h):
        """Draws the SHT30 temperature and humidity below the clock."""
        self.canvas.delete("sht30")
        if not self.sht30_loaded or not SHOW_SHT30:
            return

        y_offset = 0
        if SHOW_TIME:
            y_offset += TIME_FONT_SIZE + 50

        font_spec = (SHT30_FONT_FAMILY, SHT30_FONT_SIZE, "bold")

        # Format Temperature
        if SHT30_TEMP_UNIT.lower() == "fahrenheit":
            temp_val = self.sht30_temp * 9.0 / 5.0 + 32.0
            temp_str = f"{temp_val:.1f}F"
        else:
            temp_str = f"{self.sht30_temp:.1f}C"

        # Format Humidity
        humi_str = f"{int(round(self.sht30_humi))}%"

        # Draw Temperature
        self.create_text_with_outline(
            0, y_offset,
            text=temp_str,
            fill=SHT30_FONT_COLOR,
            font=font_spec,
            anchor="nw",
            tags="sht30"
        )

        # Draw Humidity
        self.create_text_with_outline(
            0, y_offset + SHT30_FONT_SIZE + 10,
            text=humi_str,
            fill=SHT30_FONT_COLOR,
            font=font_spec,
            anchor="nw",
            tags="sht30"
        )

    # ==========================================
    # WEATHER OVERLAY LOGIC
    # ==========================================
    def start_weather_updates(self):
        """Spawns an asynchronous weather fetching cycle."""
        if not SHOW_WEATHER:
            return
        threading.Thread(target=self._fetch_weather_thread, daemon=True).start()
        # Schedule the next refresh
        interval_ms = int(WEATHER_INTERVAL_MINS * 60 * 1000)
        self.root.after(interval_ms, self.start_weather_updates)
        
    def _fetch_weather_thread(self):
        """Runs in background thread to avoid blocking Tkinter main loop."""
        try:
            # Geocode city to lat/lon if not cached
            if not self.weather_lat or not self.weather_lon:
                lat, lon = self._resolve_location(WEATHER_LOCATION)
                self.weather_lat = lat
                self.weather_lon = lon
            
            # Fetch weather measurements
            temp, code, unit = self._get_weather_data(self.weather_lat, self.weather_lon)
            condition = self._map_weather_code(code)
            
            # Request main thread to update state and redraw weather
            self.root.after(0, self._apply_weather, temp, condition, unit)
        except Exception as e:
            print(f"Weather Fetch Error: {e}", file=sys.stderr)
            # In case of persistent failure, trigger fallback state
            self.root.after(0, self._apply_weather, None, "unknown", "")
            
    def _resolve_location(self, location):
        """Parses coordinates or geocodes city name using Open-Meteo API."""
        # Try processing as coordinates directly
        parts = location.split(',')
        if len(parts) == 2:
            try:
                return float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                pass
                
        # Call geocoding API
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(location)}&count=1&format=json"
        req = urllib.request.Request(url, headers={'User-Agent': 'PiSlideshow'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if not data.get("results"):
                raise ValueError(f"Location not found: {location}")
            res = data["results"][0]
            return float(res["latitude"]), float(res["longitude"])
            
    def _get_weather_data(self, lat, lon):
        """Fetches live weather values from Open-Meteo API."""
        unit_str = "fahrenheit" if WEATHER_UNIT.lower() == "fahrenheit" else "celsius"
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&temperature_unit={unit_str}"
        req = urllib.request.Request(url, headers={'User-Agent': 'PiSlideshow'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            current = data["current"]
            temp = float(current["temperature_2m"])
            code = int(current["weather_code"])
            unit_sym = "F" if unit_str == "fahrenheit" else "C"
            return temp, code, unit_sym
            
    def _map_weather_code(self, code):
        """Maps WMO Weather codes to condition groups."""
        if code == 0:
            return "sunny"
        elif code in (1, 2):
            return "partly_cloudy"
        elif code == 3:
            return "cloudy"
        elif code in (45, 48):
            return "foggy"
        elif code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
            return "rainy"
        elif code in (56, 57, 66, 67, 71, 73, 75, 77, 85, 86):
            return "snowy"
        elif code in (95, 96, 99):
            return "stormy"
        return "unknown"

    def _apply_weather(self, temp, condition, unit_sym):
        """Callback from background thread to safely update UI state."""
        if temp is not None:
            self.weather_temp = temp
            self.weather_condition = condition
            self.weather_unit_symbol = unit_sym
            self.weather_loaded = True
        
        # Trigger immediate refresh of weather overlay on canvas
        w, h = self.get_dimensions()
        self.draw_weather(w, h)
        
    def draw_weather(self, w, h):
        """Draws the temperature and weather icon in top-right corner."""
        self.canvas.delete("weather")
        if not self.weather_loaded:
            return
            
        icon_size = w // 10
        margin = 0
        top_margin = 0
        spacing = 10
        
        # Position temperature text at the top-right
        text_x = w - margin
        text_y = top_margin
        anchor_pos = "ne"
        
        # Draw temperature label
        if self.weather_temp is not None:
            # Display temperature as an integer without decimal point
            temp_str = f"{int(round(self.weather_temp))}°{self.weather_unit_symbol}"
            font_spec = (WEATHER_FONT_FAMILY, WEATHER_FONT_SIZE, "bold")
            
            self.create_text_with_outline(text_x, text_y, text=temp_str, fill=WEATHER_FONT_COLOR, font=font_spec, anchor=anchor_pos, tags="weather")
            
            # Since temperature is drawn, the icon will go below it
            icon_y_offset = top_margin + WEATHER_FONT_SIZE + spacing
        else:
            icon_y_offset = top_margin
            
        # Position icon below temperature text, aligned to the right side of the screen
        if self.weather_condition and self.weather_condition != "unknown":
            try:
                # Generate weather icon dynamically via PIL
                icon_img = self.create_weather_icon(self.weather_condition, icon_size)
                self.current_weather_icon_ref = ImageTk.PhotoImage(icon_img)
                
                icon_x = w - margin - icon_size // 2
                icon_y = icon_y_offset + icon_size // 2
                self.canvas.create_image(icon_x, icon_y, image=self.current_weather_icon_ref, anchor="center", tags="weather")
            except Exception as e:
                print(f"Error drawing icon: {e}", file=sys.stderr)

    def create_weather_icon(self, condition, size):
        """Generates a high-quality vector weather icon onto a transparent image."""
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Grid scaling helper
        def r(val):
            return int(val * size / 100)
            
        def draw_rect_safe(d, coords, radius, fill):
            if hasattr(d, "rounded_rectangle"):
                d.rounded_rectangle(coords, radius=radius, fill=fill)
            else:
                d.rectangle(coords, fill=fill)
                
        if condition == "sunny":
            # Yellow center sun
            draw.ellipse([r(30), r(30), r(70), r(70)], fill="#FFCC00")
            # Rays
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                x1 = size / 2 + math.cos(rad) * r(23)
                y1 = size / 2 + math.sin(rad) * r(23)
                x2 = size / 2 + math.cos(rad) * r(38)
                y2 = size / 2 + math.sin(rad) * r(38)
                draw.line([x1, y1, x2, y2], fill="#FFCC00", width=max(1, r(4)))
                
        elif condition == "partly_cloudy":
            # Draw smaller sun behind cloud
            draw.ellipse([r(45), r(15), r(75), r(45)], fill="#FFCC00")
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                x1 = r(60) + math.cos(rad) * r(17)
                y1 = r(30) + math.sin(rad) * r(17)
                x2 = r(60) + math.cos(rad) * r(28)
                y2 = r(30) + math.sin(rad) * r(28)
                draw.line([x1, y1, x2, y2], fill="#FFCC00", width=max(1, r(3)))
                
            # Foreground Cloud (Light Grey)
            draw.ellipse([r(15), r(45), r(45), r(75)], fill="#E6E6E6")
            draw.ellipse([r(30), r(35), r(65), r(70)], fill="#E6E6E6")
            draw.ellipse([r(50), r(45), r(75), r(75)], fill="#E6E6E6")
            draw.rectangle([r(30), r(50), r(60), r(75)], fill="#E6E6E6")
            
        elif condition == "cloudy":
            # Dark back cloud
            draw.ellipse([r(35), r(30), r(65), r(60)], fill="#B3B3B3")
            draw.ellipse([r(50), r(40), r(75), r(65)], fill="#B3B3B3")
            draw.ellipse([r(20), r(40), r(45), r(65)], fill="#B3B3B3")
            # Light front cloud
            draw.ellipse([r(25), r(45), r(55), r(75)], fill="#E6E6E6")
            draw.ellipse([r(40), r(35), r(75), r(70)], fill="#E6E6E6")
            draw.ellipse([r(60), r(45), r(85), r(75)], fill="#E6E6E6")
            draw.rectangle([r(40), r(55), r(70), r(75)], fill="#E6E6E6")
            
        elif condition == "foggy":
            # Minimalist horizontal fog lines
            draw_rect_safe(draw, [r(10), r(25), r(90), r(35)], r(5), "#CCCCCC")
            draw_rect_safe(draw, [r(20), r(40), r(80), r(50)], r(5), "#E6E6E6")
            draw_rect_safe(draw, [r(15), r(55), r(85), r(65)], r(5), "#CCCCCC")
            draw_rect_safe(draw, [r(30), r(70), r(70), r(80)], r(5), "#999999")
            
        elif condition == "rainy":
            # Cloud
            draw.ellipse([r(15), r(25), r(45), r(55)], fill="#999999")
            draw.ellipse([r(30), r(15), r(65), r(50)], fill="#999999")
            draw.ellipse([r(50), r(25), r(75), r(55)], fill="#999999")
            draw.rectangle([r(30), r(35), r(60), r(55)], fill="#999999")
            # Rain drops
            draw.line([r(25), r(65), r(20), r(80)], fill="#3399FF", width=max(1, r(3)))
            draw.line([r(45), r(65), r(40), r(80)], fill="#3399FF", width=max(1, r(3)))
            draw.line([r(65), r(65), r(60), r(80)], fill="#3399FF", width=max(1, r(3)))
            draw.line([r(35), r(75), r(30), r(90)], fill="#3399FF", width=max(1, r(3)))
            draw.line([r(55), r(75), r(50), r(90)], fill="#3399FF", width=max(1, r(3)))
            
        elif condition == "snowy":
            # Cloud
            draw.ellipse([r(15), r(25), r(45), r(55)], fill="#E6E6E6")
            draw.ellipse([r(30), r(15), r(65), r(50)], fill="#E6E6E6")
            draw.ellipse([r(50), r(25), r(75), r(55)], fill="#E6E6E6")
            draw.rectangle([r(30), r(35), r(60), r(55)], fill="#E6E6E6")
            # Snowflakes
            draw.ellipse([r(23), r(65), r(29), r(71)], fill="#FFFFFF")
            draw.ellipse([r(42), r(68), r(48), r(74)], fill="#FFFFFF")
            draw.ellipse([r(62), r(65), r(68), r(71)], fill="#FFFFFF")
            draw.ellipse([r(32), r(78), r(38), r(84)], fill="#FFFFFF")
            draw.ellipse([r(52), r(78), r(58), r(84)], fill="#FFFFFF")
            
        elif condition == "stormy":
            # Dark cloud
            draw.ellipse([r(15), r(25), r(45), r(55)], fill="#4D4D4D")
            draw.ellipse([r(30), r(15), r(65), r(50)], fill="#4D4D4D")
            draw.ellipse([r(50), r(25), r(75), r(55)], fill="#4D4D4D")
            draw.rectangle([r(30), r(35), r(60), r(55)], fill="#4D4D4D")
            # Yellow lightning bolt
            draw.polygon([r(45), r(55), r(35), r(75), r(48), r(75), r(40), r(95), r(58), r(70), r(48), r(70)], fill="#FFCC00")
            
        return img

    # ==========================================
    # NAVIGATION LOGIC
    # ==========================================
    def show_next(self):
        """Advances to the next image in list and resets the timer."""
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
            
        current_deleted = self.check_and_update_photos()
        
        if not self.files:
            self.canvas.delete("all")
            w, h = self.get_dimensions()
            msg = f"No images found in:\n{self.photo_dir}\n\nAdd .jpg files and the slideshow will start."
            self.create_text_with_outline(w // 2, h // 2, text=msg, fill="yellow", font=(FONT_FAMILY, 20), justify="center", anchor="center")
            self.timer_id = self.root.after(5000, self.show_next)
            return
            
        if not current_deleted:
            self.current_index = (self.current_index + 1) % len(self.files)
            
        self.display_photo(self.files[self.current_index])
        
        if not self.paused:
            self.timer_id = self.root.after(int(DURATION * 1000), self.show_next)
            
    def next_photo(self):
        """Skips to the next photo."""
        self.show_next()
        
    def prev_photo(self):
        """Steps back to the previous photo."""
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
            
        self.check_and_update_photos()
        
        if not self.files:
            self.show_next()
            return
            
        self.current_index = (self.current_index - 1) % len(self.files)
        self.display_photo(self.files[self.current_index])
        
        if not self.paused:
            self.timer_id = self.root.after(int(DURATION * 1000), self.show_next)
            
    def draw_pause_indicator(self, screen_w):
        """Draws visual pause indicator in the bottom right."""
        w, h = self.get_dimensions()
        font_spec = (FONT_FAMILY, 14, "bold")
        self.create_text_with_outline(w - 15, h - 15, text="PAUSED", fill="#ff3333", font=font_spec, anchor="se", tags="pause_indicator")
        
    def toggle_pause(self):
        """Pauses/resumes the slideshow transitions."""
        self.paused = not self.paused
        w, _ = self.get_dimensions()
        
        if self.paused:
            if self.timer_id:
                self.root.after_cancel(self.timer_id)
                self.timer_id = None
            self.draw_pause_indicator(w)
        else:
            self.canvas.delete("pause_indicator")
            self.timer_id = self.root.after(int(DURATION * 1000), self.show_next)

if __name__ == "__main__":
    root = tk.Tk()
    app = PiSlideshow(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
