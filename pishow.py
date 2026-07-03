#!/usr/bin/env python3
import os
import sys
import random
import tkinter as tk
from PIL import Image, ImageTk, ImageOps

# ==========================================
# CONFIGURATION
# ==========================================
PHOTO_DIR = "~/photos"          # Directory containing images
DURATION = 30.0                 # Slideshow timer per image (seconds)
SCALING_MODE = "fit"            # Options: "fit" (aspect ratio), "fill" (crop), "stretch" (distort)
SHOW_FILENAME = True            # Display filename overlay without extension
FONT_SIZE = 24                  # Text size
FONT_FAMILY = "DejaVu Sans"     # Standard font on Raspberry Pi OS
SHUFFLE = True                  # Set to True to randomize slideshow order
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
        
        # Create canvas for rendering centered images and text
        self.canvas = tk.Canvas(self.root, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Initialize paths and variables
        self.photo_dir = os.path.expanduser(PHOTO_DIR)
        self.files = []
        self.current_index = -1
        self.paused = False
        self.timer_id = None
        self.current_img_ref = None  # Reference to keep PhotoImage out of GC
        
        # Key bindings for interaction
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<q>", lambda e: self.root.destroy())
        self.root.bind("<space>", lambda e: self.next_photo())
        self.root.bind("<Right>", lambda e: self.next_photo())
        self.root.bind("<Left>", lambda e: self.prev_photo())
        self.root.bind("<p>", lambda e: self.toggle_pause())
        
        # Dynamically redraw image when layout changes (e.g. screen config)
        self.root.bind("<Configure>", self.on_resize)
        
        # Set up slideshow
        self.load_photos()
        self.show_next()
        
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
        """Redraws the current image to properly fit the window size if it changes."""
        if 0 <= self.current_index < len(self.files):
            self.display_photo(self.files[self.current_index])
            
    def display_photo(self, filepath):
        """Loads, scales, and displays a single image along with its filename."""
        self.canvas.delete("all")
        w, h = self.get_dimensions()
        
        try:
            # Load image
            img = Image.open(filepath)
            
            # Auto-rotate based on EXIF info (prevents sideways cell phone photos)
            img = ImageOps.exif_transpose(img)
            
            # Scale image
            img = self.scale_image(img, w, h, SCALING_MODE)
            
            # Render to TK compatibility
            self.current_img_ref = ImageTk.PhotoImage(img)
            
            # Place image in middle of the screen
            self.canvas.create_image(w // 2, h // 2, image=self.current_img_ref, anchor="center")
            
            # Draw overlay filename
            if SHOW_FILENAME:
                filename = os.path.splitext(os.path.basename(filepath))[0]
                font_spec = (FONT_FAMILY, FONT_SIZE, "bold")
                text_y = h - 60  # Float text 60px from the bottom
                
                # Classic dropshadow effect for text readability over light/dark areas
                self.canvas.create_text(w // 2 + 2, text_y + 2, text=filename, fill="black", font=font_spec, anchor="center")
                self.canvas.create_text(w // 2, text_y, text=filename, fill="white", font=font_spec, anchor="center")
                
        except Exception as e:
            # Gracefully handle file reading / scaling errors
            err_msg = f"Error loading image:\n{os.path.basename(filepath)}\n{str(e)}"
            self.canvas.create_text(w // 2, h // 2, text=err_msg, fill="red", font=(FONT_FAMILY, 20), justify="center")
            
        # Draw pause overlay if appropriate
        if self.paused:
            self.draw_pause_indicator(w)
            
    def scale_image(self, img, target_w, target_h, mode):
        """Resizes the image according to chosen configuration."""
        img_w, img_h = img.size
        
        if mode == "stretch":
            return img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
        img_ratio = img_w / img_h
        target_ratio = target_w / target_h
        
        if mode == "fit":
            # Scale down/up so the image fits fully, leaving blank sides
            if img_ratio > target_ratio:
                new_w = target_w
                new_h = int(target_w / img_ratio)
            else:
                new_h = target_h
                new_w = int(target_h * img_ratio)
            return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
        elif mode == "fill":
            # Crop image to match window aspect ratio exactly
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
        
    def show_next(self):
        """Advances to the next image and schedules the timer."""
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
            
        if not self.files:
            # Re-scan directory if no files found
            self.load_photos()
            if not self.files:
                self.canvas.delete("all")
                w, h = self.get_dimensions()
                msg = f"No images found in:\n{self.photo_dir}\n\nAdd .jpg files and the slideshow will start."
                self.canvas.create_text(w // 2, h // 2, text=msg, fill="yellow", font=(FONT_FAMILY, 20), justify="center")
                # Check directory again in 5 seconds
                self.timer_id = self.root.after(5000, self.show_next)
                return
                
        self.current_index = (self.current_index + 1) % len(self.files)
        self.display_photo(self.files[self.current_index])
        
        if not self.paused:
            self.timer_id = self.root.after(int(DURATION * 1000), self.show_next)
            
    def next_photo(self):
        """Key interaction: Skip forward."""
        self.show_next()
        
    def prev_photo(self):
        """Key interaction: Step backward."""
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
        """Draws a subtle red 'PAUSED' indicator on top right."""
        font_spec = (FONT_FAMILY, 14, "bold")
        self.canvas.create_text(screen_w - 40, 40, text="PAUSED", fill="#ff3333", font=font_spec, tags="pause_indicator", anchor="e")
        
    def toggle_pause(self):
        """Key interaction: Pause/Resume timer."""
        self.paused = not self.paused
        w, _ = self.get_dimensions()
        
        if self.paused:
            if self.timer_id:
                self.root.after_cancel(self.timer_id)
                self.timer_id = None
            self.draw_pause_indicator(w)
        else:
            self.canvas.delete("pause_indicator")
            # Resume slideshow sequence and schedule next timer
            self.timer_id = self.root.after(int(DURATION * 1000), self.show_next)

if __name__ == "__main__":
    # Create Tkinter application window
    root = tk.Tk()
    app = PiSlideshow(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
