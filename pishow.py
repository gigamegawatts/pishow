#!/usr/bin/env python3
import os
import sys
import random
import tkinter as tk
import urllib.request
import urllib.parse
import json
import threading
import math
from datetime import datetime
from PIL import Image, ImageTk, ImageOps, ImageDraw

# ==========================================
# CONFIGURATION
# ==========================================
PHOTO_DIR = "~/photos"          # Directory containing images
DURATION = 30.0                 # Slideshow timer per image (seconds)
SCALING_MODE = "fit"            # Options: "fit" (aspect ratio), "fill" (crop), "stretch" (distort)
SHOW_FILENAME = True            # Display filename overlay without extension
FONT_SIZE = 24                  # Filename text size
FONT_FAMILY = "DejaVu Sans"     # Filename text font family
SHUFFLE = False                 # Set to True to randomize slideshow order

# --- CLOCK CONFIGURATION ---
SHOW_TIME = True
TIME_FONT_FAMILY = "DejaVu Sans"
TIME_FONT_SIZE = 48
TIME_FONT_COLOR = "white"

# --- WEATHER CONFIGURATION ---
SHOW_WEATHER = True
WEATHER_LOCATION = "New York"    # City name (e.g., "Chicago") or "lat,lon" (e.g., "40.7128,-74.0060")
WEATHER_FONT_FAMILY = "DejaVu Sans"
WEATHER_FONT_SIZE = 36
WEATHER_FONT_COLOR = "white"
WEATHER_UNIT = "fahrenheit"      # Options: "fahrenheit", "celsius"
WEATHER_INTERVAL_MINS = 15       # Fetch current weather every 15 minutes
# ==========================================

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
        
        # Start scanning directory and slideshow loop
        self.load_photos()
        self.show_next()
        
        # Start overlay update loops
        self.start_clock_updates()
        self.start_weather_updates()
        
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
                
                # Dropshadow
                self.canvas.create_text(w // 2 + 2, text_y + 2, text=filename, fill="black", font=font_spec, anchor="center")
                self.canvas.create_text(w // 2, text_y, text=filename, fill="white", font=font_spec, anchor="center")
                
        except Exception as e:
            # Gracefully handle file reading / scaling errors on screen
            err_msg = f"Error loading image:\n{os.path.basename(filepath)}\n{str(e)}"
            self.canvas.create_text(w // 2, h // 2, text=err_msg, fill="red", font=(FONT_FAMILY, 20), justify="center")
            
        # Draw pause overlay if active
        if self.paused:
            self.draw_pause_indicator(w)
            
        # 2. Draw live overlays on top of the newly drawn photo
        if SHOW_TIME:
            self.draw_clock(w, h)
        if SHOW_WEATHER:
            self.draw_weather(w, h)
            
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
        
        x, y = 40, 40
        font_spec = (TIME_FONT_FAMILY, TIME_FONT_SIZE, "bold")
        
        # Dual text draw for dropshadow contrast
        self.canvas.create_text(x + 2, y + 2, text=time_str, fill="black", font=font_spec, anchor="nw", tags="clock")
        self.canvas.create_text(x, y, text=time_str, fill=TIME_FONT_COLOR, font=font_spec, anchor="nw", tags="clock")

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
        with urllib.request.urlopen(req) as response:
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
        with urllib.request.urlopen(req) as response:
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
        margin = 40
        
        # Position icon in top-right corner
        if self.weather_condition and self.weather_condition != "unknown":
            try:
                # Generate weather icon dynamically via PIL
                icon_img = self.create_weather_icon(self.weather_condition, icon_size)
                self.current_weather_icon_ref = ImageTk.PhotoImage(icon_img)
                
                icon_x = w - margin - icon_size // 2
                icon_y = margin + icon_size // 2
                self.canvas.create_image(icon_x, icon_y, image=self.current_weather_icon_ref, anchor="center", tags="weather")
                
                # Temperature text positioning (offset to the left of the icon)
                text_x = w - margin - icon_size - 20
                text_y = margin + icon_size // 2
                anchor_pos = "e"
            except Exception as e:
                print(f"Error drawing icon: {e}", file=sys.stderr)
                text_x = w - margin
                text_y = margin
                anchor_pos = "ne"
        else:
            # Fallback alignment if no icon is loaded
            text_x = w - margin
            text_y = margin
            anchor_pos = "ne"
            
        # Draw temperature label
        if self.weather_temp is not None:
            temp_str = f"{self.weather_temp:.1f}°{self.weather_unit_symbol}"
            font_spec = (WEATHER_FONT_FAMILY, WEATHER_FONT_SIZE, "bold")
            
            # Dropshadow offset
            self.canvas.create_text(text_x + 2, text_y + 2, text=temp_str, fill="black", font=font_spec, anchor=anchor_pos, tags="weather")
            self.canvas.create_text(text_x, text_y, text=temp_str, fill=WEATHER_FONT_COLOR, font=font_spec, anchor=anchor_pos, tags="weather")

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
            
        if not self.files:
            self.load_photos()
            if not self.files:
                self.canvas.delete("all")
                w, h = self.get_dimensions()
                msg = f"No images found in:\n{self.photo_dir}\n\nAdd .jpg files and the slideshow will start."
                self.canvas.create_text(w // 2, h // 2, text=msg, fill="yellow", font=(FONT_FAMILY, 20), justify="center")
                self.timer_id = self.root.after(5000, self.show_next)
                return
                
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
            
        if not self.files:
            self.show_next()
            return
            
        self.current_index = (self.current_index - 1) % len(self.files)
        self.display_photo(self.files[self.current_index])
        
        if not self.paused:
            self.timer_id = self.root.after(int(DURATION * 1000), self.show_next)
            
    def draw_pause_indicator(self, screen_w):
        """Draws visual pause indicator in the top right."""
        font_spec = (FONT_FAMILY, 14, "bold")
        self.canvas.create_text(screen_w - 40, 40, text="PAUSED", fill="#ff3333", font=font_spec, tags="pause_indicator", anchor="e")
        
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
