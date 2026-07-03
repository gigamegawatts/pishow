# Raspberry Pi Photo Slideshow (`pishow`)

A lightweight Python slideshow application built for Raspberry Pi OS. It reads images from `~/photos`, displays them full-screen, scales them dynamically to fit the display, shows filename text overlays, and includes simple keyboard controls. 

It also displays a **live clock (upper-left)** and **current weather (upper-right)** with temperature readings and beautiful, dynamically sized, hand-drawn vector condition icons (Sunny, Cloudy, Rainy, Snowy, etc.).

---

## 🛠️ Required Packages & Installation

Modern versions of Raspberry Pi OS (specifically Bookworm and newer) restrict installing packages globally using `pip` to avoid conflicts with system packages (defined by PEP 668). 

You can choose one of the two methods below to install the necessary packages.

### Method 1: Using the System Package Manager (Recommended)
This is the easiest and cleanest way on a Raspberry Pi because it manages everything using `apt` packages.

Run this command in the terminal on your Raspberry Pi:
```bash
sudo apt update
sudo apt install -y python3-pil python3-pil.imagetk python3-tk
```
*   `python3-tk`: The Tkinter library for GUI/window management.
*   `python3-pil` and `python3-pil.imagetk`: The Pillow library for image processing and loading images into Tkinter.

---

### Method 2: Using a Python Virtual Environment (`venv`)
If you prefer not to use system packages, you can run the program inside an isolated environment.

1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   ```
2. Activate it:
   ```bash
   source venv/bin/activate
   ```
3. Install the dependencies:
   ```bash
   pip install Pillow
   ```
   *(Note: Tkinter is normally bundled with Python, but if it is missing, you still need to run `sudo apt install python3-tk`)*.

---

## 🚀 How to Run the Slideshow

1. **Create the photos directory**:
   The script looks for photos in a folder named `photos` in your home directory. Create it and copy some images into it:
   ```bash
   mkdir -p ~/photos
   ```
2. **Copy the script**:
   Copy the `pishow.py` script onto your Raspberry Pi.
3. **Execute the script**:
   If using **Method 1 (System packages)**:
   ```bash
   python3 pishow.py
   ```
   If using **Method 2 (Virtual environment)**:
   ```bash
   source venv/bin/activate
   python3 pishow.py
   ```

---

## 🎹 Keyboard Controls

While the slideshow is running, you can control it with these keys:

| Key | Action |
|---|---|
| `Space` or `➡️ (Right Arrow)` | Skip to the next photo |
| `⬅️ (Left Arrow)` | Go back to the previous photo |
| `p` | Pause / Resume the slideshow timer |
| `Escape` or `q` | Exit the slideshow |

---

## ⚙️ Customization / Configuration

At the top of [pishow.py](file:///c:/Users/gigam/source/repos/antigravity/pishow/pishow.py), you'll find a **CONFIGURATION** section. You can open the file in a text editor (like `nano`) and change these values:

```python
# ==========================================
# CONFIGURATION
# ==========================================
PHOTO_DIR = "~/photos"          # Folder containing your images
DURATION = 30.0                 # How long each photo shows (in seconds)
SCALING_MODE = "fit"            # Image scaling mode: "fit", "fill", or "stretch"
SHOW_FILENAME = True            # Set to False to hide the filename overlay
FONT_SIZE = 24                  # Font size for the filename overlay
FONT_FAMILY = "DejaVu Sans"     # Font style for filename overlay
SHUFFLE = False                 # Set to True to randomize slideshow order

# --- CLOCK CONFIGURATION ---
SHOW_TIME = True                # Toggle live clock (upper-left)
TIME_FONT_FAMILY = "DejaVu Sans"
TIME_FONT_SIZE = 48
TIME_FONT_COLOR = "white"       # Font color (supports words or hex like "#ffffff")

# --- WEATHER CONFIGURATION ---
SHOW_WEATHER = True             # Toggle weather overlay (upper-right)
WEATHER_LOCATION = "New York"    # City name (e.g. "Paris") or exact "lat,lon" (e.g. "48.8566,2.3522")
WEATHER_FONT_FAMILY = "DejaVu Sans"
WEATHER_FONT_SIZE = 36
WEATHER_FONT_COLOR = "white"
WEATHER_UNIT = "fahrenheit"      # "fahrenheit" or "celsius"
WEATHER_INTERVAL_MINS = 15       # Fetch current weather every 15 minutes
```

### Scaling Modes:
*   `"fit"` *(Default)*: Scales the image to fit the screen without distortion. If the aspect ratio of the image doesn't match your monitor, black bars will appear on the sides/top.
*   `"fill"`: Scales the image so that the entire screen is covered, cropping the edges of the image where necessary to preserve aspect ratio.
*   `"stretch"`: Stretches/squashes the image to exactly match the screen width and height.

### Weather Location:
You can specify your location using either:
*   A city name (e.g., `"Chicago"` or `"London"`). The script will automatically query the free Open-Meteo geocoding service at startup to resolve it.
*   Exact GPS coordinates (e.g., `"41.8781,-87.6298"`). This is the fastest and most reliable option since it skips the geocoding lookup.

---

## 🖥️ Running Automatically on Boot (Optional Kiosk Mode)

To make the slideshow launch automatically whenever the Raspberry Pi boots to the desktop:

1. Create a standard autostart folder configuration:
   ```bash
   mkdir -p ~/.config/autostart
   ```
2. Create a new autostart desktop entry:
   ```bash
   nano ~/.config/autostart/slideshow.desktop
   ```
3. Paste the following configuration (replace `/home/pi/pishow.py` with the actual path to your script):
   ```ini
   [Desktop Entry]
   Type=Application
   Name=Slideshow
   Exec=python3 /home/pi/pishow.py
   ```
4. Save and exit (in Nano: press `Ctrl+O`, `Enter`, then `Ctrl+X`).
