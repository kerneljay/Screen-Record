import tkinter as tk
from tkinter import messagebox, filedialog
import pyautogui
import cv2
import numpy as np
import threading
import time
from datetime import datetime
from pathlib import Path
import keyboard
import os
import json
import subprocess
import glob
import pystray
from PIL import Image, ImageDraw, ImageTk
import mss

# Print available monitors for debugging
with mss.mss() as sct:
    for i, mon in enumerate(sct.monitors[1:], 1):
        print(f"Screen {i}: {mon['width']}x{mon['height']} at ({mon['left']},{mon['top']})")

# Global control variables
is_recording = False
stop_flag = False
replace_mode = False
record_region = None
selected_monitor = None
show_cursor = True
is_previewing = False
preview_thread = None
preview_window = None
CONFIG_FILE = Path.home() / ".screen_recorder_config.json"
save_path = Path.home() / "Videos" / "Python Videos"
last_recorded_file = None
hotkey = 'ctrl+shift+r'
window_toggle_key = 'f12'

def get_monitors():
    """Retrieve list of monitors using mss."""
    try:
        with mss.mss() as sct:
            monitors = [(i, mon) for i, mon in enumerate(sct.monitors[1:], 0)]  # 0-based indexing
            if not monitors:
                print("[-] No screens detected")
                return []
            print("[+] Detected screens:", [(i+1, mon['width'], mon['height'], mon['left'], mon['top']) for i, mon in monitors])
            return monitors
    except Exception as e:
        print(f"[-] Error getting screens: {e}")
        return []

def stop_preview():
    """Stop the preview window and thread."""
    global is_previewing, preview_thread, preview_window
    if is_previewing:
        is_previewing = False
        if preview_window and preview_window.winfo_exists():
            preview_window.destroy()
        preview_thread = None
        print("[+] Preview stopped")

def start_preview():
    """Start a live preview of the recording region."""
    global is_previewing, preview_thread, preview_window
    if is_recording:
        messagebox.showwarning("Recording in Progress", "Cannot preview while recording.")
        print("[-] Preview blocked: Recording in progress")
        return
    if is_previewing:
        stop_preview()
        return
    preview_window = tk.Toplevel(root)
    preview_window.title("Recording Preview")
    preview_window.resizable(False, False)
    preview_window.protocol("WM_DELETE_WINDOW", stop_preview)
    try:
        with mss.mss() as sct:
            if selected_monitor is not None:
                try:
                    monitor = get_monitors()[selected_monitor][1]
                    x, y, width, height = monitor['left'], monitor['top'], monitor['width'], monitor['height']
                    if width <= 0 or height <= 0:
                        raise ValueError("Invalid screen dimensions")
                    mon = {"left": x, "top": y, "width": width, "height": height}
                    title = f"Screen {selected_monitor+1} ({width}x{height})"
                except (IndexError, ValueError) as e:
                    messagebox.showerror("Error", f"Invalid screen selection: {e}")
                    print(f"[-] Screen selection error: {e}")
                    preview_window.destroy()
                    return
            elif record_region:
                x, y, width, height = record_region
                mon = {"left": x, "top": y, "width": width, "height": height}
                title = f"Region ({width}x{height} at {x},{y})"
            else:
                screen_size = sct.monitors[0]
                x, y = 0, 0
                width = min(screen_size["width"], 1920)
                height = min(screen_size["height"], 1080)
                mon = {"left": x, "top": y, "width": width, "height": height}
                title = f"Primary Screen ({width}x{height})"
    except Exception as e:
        messagebox.showerror("Error", f"Failed to initialize capture: {e}")
        print(f"[-] Capture initialization error: {e}")
        preview_window.destroy()
        return
    max_preview_width, max_preview_height = 400, 300
    aspect_ratio = width / height
    if width > max_preview_width or height > max_preview_height:
        if aspect_ratio > max_preview_width / max_preview_height:
            preview_width = max_preview_width
            preview_height = int(max_preview_width / aspect_ratio)
        else:
            preview_height = max_preview_height
            preview_width = int(max_preview_height * aspect_ratio)
    else:
        preview_width, preview_height = width, height
    preview_window.geometry(f"{preview_width}x{preview_height + 40}")
    tk.Label(preview_window, text=title, font=('Arial', 8)).pack(pady=2)
    preview_label = tk.Label(preview_window)
    preview_label.pack(fill='both', expand=True)
    is_previewing = True
    def update_preview():
        try:
            with mss.mss() as sct:
                target_fps = 30
                frame_interval = 1.0 / target_fps
                while is_previewing and preview_window.winfo_exists():
                    start_time = time.time()
                    try:
                        img = sct.grab(mon)
                        if img is None or img.rgb is None:
                            print("[-] Failed to capture frame: Empty image")
                            preview_window.after(0, lambda: preview_label.config(text="Error: Failed to capture frame"))
                            time.sleep(0.1)
                            continue
                        frame = np.array(img)
                        if frame.size == 0:
                            print("[-] Empty frame captured")
                            preview_window.after(0, lambda: preview_label.config(text="Error: Empty frame"))
                            time.sleep(0.1)
                            continue
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                        image = Image.fromarray(frame)
                        image = image.resize((preview_width, preview_height), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(image)
                        def update_label():
                            if is_previewing and preview_window.winfo_exists():
                                preview_label.config(image=photo, text="")
                                preview_label.image = photo
                            else:
                                print("[-] Preview window closed or preview stopped")
                        preview_window.after(0, update_label)
                        elapsed = time.time() - start_time
                        sleep_time = max(0, frame_interval - elapsed)
                        time.sleep(sleep_time)
                    except Exception as e:
                        error_msg = str(e)
                        print(f"[-] Preview frame error: {e}")
                        preview_window.after(0, lambda msg=error_msg: preview_label.config(text=f"Error: {msg}"))
                        time.sleep(0.1)
        except Exception as e:
            error_msg = str(e)
            print(f"[-] Preview loop error: {e}")
            preview_window.after(0, lambda msg=error_msg: preview_label.config(text=f"Error: {msg}"))
        finally:
            # global is_previewing
            # is_previewing = False
            print("[+] Preview thread stopped")
            if preview_window.winfo_exists():
                preview_window.after(0, preview_window.destroy)
    preview_thread = threading.Thread(target=update_preview, daemon=True)
    preview_thread.start()
    print("[+] Preview started")

def convert_to_twitter_format(input_path):
    """Convert video to Twitter-compatible format."""
    output_path = input_path.with_name(input_path.stem + "_twitter.mp4")
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-f", "lavfi", "-t", str(get_video_duration(input_path)),
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-vcodec", "libx264", "-pix_fmt", "yuv420p",
        "-profile:v", "baseline", "-level", "3.0",
        "-acodec", "aac", "-b:a", "128k",
        str(output_path)
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"[-] Error converting to Twitter format: {e}")
        return input_path

def get_video_duration(path):
    """Get duration of a video file using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        return float(result.stdout)
    except Exception as e:
        print(f"[-] Error getting video duration: {e}")
        return 10.0

def save_config(path, replace_mode, record_region, selected_monitor, show_cursor):
    """Save configuration to JSON file."""
    config = {
        "save_path": str(path),
        "replace_mode": replace_mode,
        "record_region": record_region,
        "selected_monitor": selected_monitor,
        "show_cursor": show_cursor
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f)
        print("[+] Configuration saved")
    except Exception as e:
        print(f"[-] Error saving config: {e}")

def load_config():
    """Load configuration from JSON file."""
    default_path = Path.home() / "Videos" / "Python Videos"
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                path = Path(config.get("save_path", str(default_path)))
                replace_mode = config.get("replace_mode", False)
                record_region = config.get("record_region", None)
                selected_monitor = config.get("selected_monitor", None)
                show_cursor = config.get("show_cursor", True)
                # Validate selected_monitor
                if selected_monitor is not None:
                    monitors = get_monitors()
                    if selected_monitor >= len(monitors):
                        print(f"[-] Invalid selected_monitor {selected_monitor}, resetting to None")
                        selected_monitor = None
                return path, replace_mode, record_region, selected_monitor, show_cursor
        except Exception as e:
            print(f"[-] Error loading config: {e}")
    return default_path, False, None, None, True

def delete_old_recordings():
    """Delete old recordings based on pattern."""
    patterns = ["screen_record_*.mp4", "*_twitter.mp4"]
    deleted_count = 0
    for pattern in patterns:
        for file_path in save_path.glob(pattern):
            try:
                os.remove(file_path)
                deleted_count += 1
                print(f"[+] Deleted old recording: {file_path.name}")
            except Exception as e:
                print(f"[-] Failed to delete {file_path.name}: {e}")
    return deleted_count

def select_region():
    """Allow user to select a custom recording region."""
    global record_region, selected_monitor
    root.withdraw()
    overlay = tk.Toplevel()
    overlay.title("Select Recording Region")
    overlay.attributes('-fullscreen', True)
    overlay.attributes('-alpha', 0.3)
    overlay.attributes('-topmost', True)
    overlay.configure(bg='black')
    overlay.focus_force()
    canvas = tk.Canvas(overlay, highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    start_x = start_y = end_x = end_y = 0
    is_selecting = False
    selection_rect = None
    def start_select(event):
        nonlocal start_x, start_y, is_selecting, selection_rect
        start_x, start_y = event.x_root, event.y_root
        is_selecting = True
    def update_select(event):
        nonlocal end_x, end_y, selection_rect
        if is_selecting:
            end_x, end_y = event.x_root, event.y_root
            if selection_rect:
                canvas.delete(selection_rect)
            x1, y1 = min(start_x, end_x), min(start_y, end_y)
            x2, y2 = max(start_x, end_x), max(start_y, end_y)
            selection_rect = canvas.create_rectangle(x1, y1, x2, y2, outline='red', width=3, fill='red', stipple='gray25')
    def end_select(event):
        nonlocal is_selecting
        if is_selecting:
            is_selecting = False
            end_x, end_y = event.x_root, event.y_root
            x1, y1 = min(start_x, end_x), min(start_y, end_y)
            x2, y2 = max(start_x, end_x), max(start_y, end_y)
            width, height = x2 - x1, y2 - y1
            if width > 10 and height > 10:
                record_region = (x1, y1, width, height)
                selected_monitor = None
                overlay.destroy()
                root.deiconify()
                update_region_label()
                save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)
                messagebox.showinfo("Region Selected", f"Recording region set to:\n{width}x{height} at ({x1},{y1})")
            else:
                overlay.destroy()
                root.deiconify()
                messagebox.showwarning("Invalid Selection", "Region too small. Please select a larger area.")
    def cancel_select(event):
        overlay.destroy()
        root.deiconify()
    def open_monitor_dialog(event):
        overlay.destroy()
        root.deiconify()
        select_monitor_dialog()
    instruction_label = tk.Label(overlay, text="Drag to select region • ESC to cancel • Enter for screen selection",
                               fg='white', bg='black', font=('Arial', 14, 'bold'))
    instruction_label.pack(pady=20)
    canvas.bind("<Button-1>", start_select)
    canvas.bind("<B1-Motion>", update_select)
    canvas.bind("<ButtonRelease-1>", end_select)
    overlay.bind("<Escape>", cancel_select)
    overlay.bind("<Return>", open_monitor_dialog)
    overlay.focus_set()

def select_monitor_dialog():
    """Display dialog to select a monitor for recording."""
    global selected_monitor, record_region
    monitors = get_monitors()
    if not monitors:
        messagebox.showerror("Error", "No screens detected! Please check your display settings.")
        print("[-] No screens detected in select_monitor_dialog")
        root.deiconify()
        return
    dialog = tk.Toplevel(root)
    dialog.title("Select Screen")
    dialog.geometry("400x200")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()
    tk.Label(dialog, text="Select Screen to Record:", font=('Arial', 10, 'bold')).pack(pady=10)
    monitor_var = tk.StringVar(value=str(selected_monitor if selected_monitor is not None else "0"))
    for i, monitor in monitors:
        monitor_dict = monitor
        tk.Radiobutton(dialog,
                      text=f"Screen {i+1}: {monitor_dict['width']}x{monitor_dict['height']} at ({monitor_dict['left']},{monitor_dict['top']})",
                      variable=monitor_var,
                      value=str(i),
                      font=('Arial', 9)).pack(anchor='w', padx=20, pady=2)
    def confirm():
        global selected_monitor, record_region
        try:
            selected_monitor = int(monitor_var.get())
            record_region = None
            dialog.destroy()
            root.deiconify()
            update_region_label()
            save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)
            monitor = monitors[selected_monitor][1]
            messagebox.showinfo("Screen Selected",
                               f"Recording set to Screen {selected_monitor+1}: {monitor['width']}x{monitor['height']}")
        except (ValueError, IndexError) as e:
            messagebox.showerror("Error", f"Invalid screen selection: {e}")
            dialog.destroy()
            root.deiconify()
    tk.Button(dialog, text="Confirm", command=confirm, bg="lightgreen").pack(pady=10)
    tk.Button(dialog, text="Cancel", command=lambda: [dialog.destroy(), root.deiconify()]).pack(pady=5)

def update_region_label():
    """Update the region label based on current settings."""
    try:
        monitors = get_monitors()
        if selected_monitor is not None and selected_monitor < len(monitors):
            monitor = monitors[selected_monitor][1]
            region_label.config(text=f"Region: Screen {selected_monitor+1} ({monitor['width']}x{monitor['height']} at {monitor['left']},{monitor['top']})")
        elif record_region:
            x, y, w, h = record_region
            region_label.config(text=f"Region: {w}x{h} at ({x},{y})")
        else:
            region_label.config(text="Region: Full Screen (auto)")
    except Exception as e:
        print(f"[-] Error updating region label: {e}")
        region_label.config(text="Region: Error updating region")

def clear_region():
    """Clear the selected region or monitor."""
    global record_region, selected_monitor
    record_region = None
    selected_monitor = None
    update_region_label()
    save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)
    messagebox.showinfo("Region Cleared", "Recording region cleared. Will record primary screen.")

def toggle_cursor():
    """Toggle cursor visibility in recordings."""
    global show_cursor
    show_cursor = not show_cursor
    cursor_toggle_btn.config(text=f"🖱️ Cursor: {'ON' if show_cursor else 'OFF'}",
                           bg="green" if show_cursor else "red",
                           fg="white" if show_cursor else "black")
    save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)
    messagebox.showinfo("Cursor Visibility", f"Cursor in recordings: {'ON' if show_cursor else 'OFF'}")
    print(f"[+] Cursor visibility: {'ON' if show_cursor else 'OFF'}")

def record_screen(duration, fps=30):
    """Record the screen for the specified duration."""
    global is_recording, stop_flag, last_recorded_file
    if replace_mode:
        deleted_count = delete_old_recordings()
        if deleted_count > 0:
            status_label.config(text=f"Deleted {deleted_count} old recordings...")
            time.sleep(1)
    was_visible = root.winfo_viewable()
    if was_visible:
        root.withdraw()
        print("[+] Window hidden during recording")
    with mss.mss() as sct:
        if selected_monitor is not None:
            try:
                monitor = get_monitors()[selected_monitor][1]
                x, y, width, height = monitor['left'], monitor['top'], monitor['width'], monitor['height']
                print(f"[+] Recording screen {selected_monitor+1}: {width}x{height} at ({x},{y})")
                if width <= 0 or height <= 0:
                    raise ValueError("Invalid screen dimensions")
                mon = {"left": x, "top": y, "width": width, "height": height}
            except (IndexError, ValueError) as e:
                print(f"[-] Error with screen selection: {e}")
                status_label.config(text="Error: Invalid screen selection")
                if was_visible:
                    root.deiconify()
                return
        elif record_region:
            x, y, width, height = record_region
            print(f"[+] Recording region: {width}x{height} at ({x},{y})")
            mon = {"left": x, "top": y, "width": width, "height": height}
        else:
            screen_size = sct.monitors[0]
            x, y = 0, 0
            width = min(screen_size["width"], 1920)
            height = min(screen_size["height"], 1080)
            print(f"[+] Recording primary screen: {width}x{height}")
            mon = {"left": x, "top": y, "width": width, "height": height}
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        filename = save_path / f"screen_record_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        out = cv2.VideoWriter(str(filename), fourcc, fps, (width, height))
        is_recording = True
        stop_flag = False
        status_text = f"Recording {'screen ' + str(selected_monitor+1) if selected_monitor is not None else 'region' if record_region else 'primary screen'}..."
        status_label.config(text=status_text)
        start_time = time.time()
        frame_interval = 1.0 / fps
        next_frame_time = start_time
        try:
            while time.time() - start_time < duration:
                if stop_flag:
                    break
                current_time = time.time()
                if current_time >= next_frame_time:
                    img = sct.grab(mon)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    if show_cursor:
                        try:
                            cursor_x, cursor_y = pyautogui.position()
                            rel_x = cursor_x - x
                            rel_y = cursor_y - y
                            if 0 <= rel_x < width and 0 <= rel_y < height:
                                cv2.circle(frame, (rel_x, rel_y), 5, (0, 0, 0), 1)
                                cv2.circle(frame, (rel_x, rel_y), 3, (255, 255, 255), -1)
                        except Exception as e:
                            print(f"[-] Error drawing cursor: {e}")
                    out.write(frame)
                    next_frame_time += frame_interval
                    if next_frame_time < current_time:
                        next_frame_time = current_time + frame_interval
                time.sleep(max(0, next_frame_time - time.time()))
        except Exception as e:
            print(f"[-] Recording error: {e}")
            status_label.config(text=f"Recording error: {e}")
        finally:
            out.release()
            is_recording = False
            if was_visible:
                root.deiconify()
                root.state('normal')
                root.lift()
                print("[+] Window restored after recording")
        status_label.config(text="Encoding for Twitter...")
        twitter_file = convert_to_twitter_format(filename)
        last_recorded_file = twitter_file
        mode_text = " (Replace Mode)" if replace_mode else ""
        region_text = f" (Screen {selected_monitor+1})" if selected_monitor is not None else " (Region)" if record_region else " (Primary Screen)"
        status_label.config(text=f"Saved Twitter-ready{mode_text}{region_text}:\n{twitter_file}")
        print(f"[+] Saved Twitter-ready: {twitter_file}")

def toggle_replace_mode():
    """Toggle replace mode for recordings."""
    global replace_mode
    replace_mode = not replace_mode
    replace_toggle_btn.config(text=f"📁 Replace Mode: {'ON' if replace_mode else 'OFF'}",
                            bg="green" if replace_mode else "red",
                            fg="white" if replace_mode else "black")
    save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)
    messagebox.showinfo("Mode Changed", f"{'Replace' if replace_mode else 'Accumulate'} Mode: {'New recordings will delete old ones' if replace_mode else 'Keep all recordings'}")
    print(f"[+] Replace mode: {'ON' if replace_mode else 'OFF'}")

def start_recording():
    """Start the screen recording."""
    if is_recording:
        return
    duration_value = duration_entry.get()
    unit = duration_unit.get()
    duration_sec = convert_to_seconds(duration_value, unit)
    if duration_sec <= 0:
        messagebox.showerror("Invalid Duration", "Please enter a valid number for duration.")
        return
    t = threading.Thread(target=record_screen, args=(duration_sec,))
    t.start()

def convert_to_seconds(value, unit):
    """Convert duration to seconds."""
    try:
        value = float(value)
    except ValueError:
        return -1
    if unit == "Seconds":
        return value
    elif unit == "Minutes":
        return value * 60
    elif unit == "Hours":
        return value * 3600
    return -1

def stop_recording():
    """Stop the current recording."""
    global stop_flag
    if is_recording:
        stop_flag = True

def toggle_recording():
    """Toggle recording state."""
    if not root.winfo_viewable():
        root.deiconify()
        root.state('normal')
        root.lift()
        root.focus_force()
        return
    if is_recording:
        stop_recording()
    else:
        start_recording()

def toggle_window_visibility():
    """Toggle the visibility of the main window."""
    try:
        if root.winfo_viewable():
            root.withdraw()
            print(f"[+] Window hidden (use {window_toggle_key.upper()} to show)")
        else:
            root.deiconify()
            root.state('normal')
            root.lift()
            root.attributes('-topmost', True)
            root.focus_force()
            root.attributes('-topmost', False)
            print(f"[+] Window restored (use {window_toggle_key.upper()} to hide)")
    except Exception as e:
        print(f"[-] Error toggling window: {e}")

def browse_folder():
    """Select a folder to save recordings."""
    global save_path
    folder = filedialog.askdirectory(initialdir=str(Path.home()), title="Select Save Directory")
    if folder:
        save_path = Path(folder)
        save_path.mkdir(parents=True, exist_ok=True)
        directory_label.config(text=f"Save to:\n{save_path}")
        save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)

def open_settings():
    """Open settings window to change hotkeys."""
    def save_hotkey():
        global hotkey, window_toggle_key
        new_hotkey = hotkey_entry.get().strip()
        new_toggle_key = toggle_key_entry.get().strip()
        if new_hotkey:
            try:
                keyboard.remove_hotkey(hotkey)
                keyboard.add_hotkey(new_hotkey, toggle_recording)
                hotkey = new_hotkey
            except Exception as e:
                messagebox.showerror("Error", f"Invalid recording hotkey: {e}")
                return
        if new_toggle_key:
            try:
                keyboard.remove_hotkey(window_toggle_key)
                keyboard.add_hotkey(new_toggle_key, toggle_window_visibility)
                window_toggle_key = new_toggle_key
            except Exception as e:
                messagebox.showerror("Error", f"Invalid toggle key: {e}")
                return
        settings_win.destroy()
        messagebox.showinfo("Hotkeys Set", f"Recording: {hotkey}\nWindow Toggle: {window_toggle_key}")
    settings_win = tk.Toplevel(root)
    settings_win.title("Settings")
    settings_win.geometry("350x180")
    settings_win.resizable(False, False)
    tk.Label(settings_win, text="Recording Hotkey (e.g. ctrl+shift+r):").pack(pady=(10, 2))
    hotkey_entry = tk.Entry(settings_win, width=25)
    hotkey_entry.pack(pady=2)
    hotkey_entry.insert(0, hotkey)
    tk.Label(settings_win, text="Window Toggle Key (e.g. f12):").pack(pady=(10, 2))
    toggle_key_entry = tk.Entry(settings_win, width=25)
    toggle_key_entry.pack(pady=2)
    toggle_key_entry.insert(0, window_toggle_key)
    tk.Button(settings_win, text="Save", command=save_hotkey).pack(pady=15)

def open_last_recorded():
    """Open the last recorded file."""
    if last_recorded_file and last_recorded_file.exists():
        os.startfile(last_recorded_file)
    else:
        messagebox.showinfo("No Recording", "No recent recording to open.")

def open_save_folder():
    """Open the save folder."""
    os.startfile(save_path)

def delete_last_recorded():
    """Delete the last recorded file."""
    global last_recorded_file
    if last_recorded_file and last_recorded_file.exists():
        try:
            os.remove(last_recorded_file)
            messagebox.showinfo("Deleted", f"Deleted: {last_recorded_file.name}")
            last_recorded_file = None
            status_label.config(text="Last recording deleted.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not delete file: {e}")
    else:
        messagebox.showinfo("No File", "No recent recording to delete.")

def delete_all_recordings():
    """Delete all recordings in the save folder."""
    result = messagebox.askyesno("Delete All Recordings",
                                f"Are you sure you want to delete ALL recordings in:\n{save_path}?\n\nThis cannot be undone!")
    if result:
        deleted_count = delete_old_recordings()
        if deleted_count > 0:
            messagebox.showinfo("Deleted", f"Deleted {deleted_count} recordings.")
            status_label.config(text=f"Deleted {deleted_count} recordings.")
        else:
            messagebox.showinfo("No Files", "No recordings found to delete.")

def on_minimize(event):
    """Handle window minimize event."""
    if root.state() == 'iconic':
        root.withdraw()
        status_label.config(text="Running in background... (use hotkey or tray to restore)")

def on_close():
    """Handle window close event."""
    root.withdraw()
    status_label.config(text="Running in background... (use hotkey or tray to restore)")

def create_image():
    """Create an icon for the system tray."""
    image = Image.new('RGB', (64, 64), color='black')
    dc = ImageDraw.Draw(image)
    dc.rectangle((16, 16, 48, 48), fill='white')
    return image

def on_tray_open(icon, item):
    """Restore window from system tray."""
    def restore_window():
        try:
            root.deiconify()
            root.state('normal')
            root.lift()
            root.attributes('-topmost', True)
            root.focus_force()
            root.attributes('-topmost', False)
            status_label.config(text="Window restored from tray")
        except Exception as e:
            print(f"[-] Error restoring window: {e}")
    root.after(0, restore_window)

def on_tray_exit(icon, item):
    """Exit the application from system tray."""
    def exit_app():
        try:
            keyboard.unhook_all()
            icon.stop()
            root.quit()
            root.destroy()
        except Exception as e:
            print(f"[-] Error exiting app: {e}")
    root.after(0, exit_app)

def setup_tray():
    """Set up the system tray icon."""
    icon = pystray.Icon("screen_recorder")
    icon.icon = create_image()
    icon.title = "Simple Screen Recorder"
    icon.menu = pystray.Menu(
        pystray.MenuItem("Open Window", on_tray_open, default=True),
        pystray.MenuItem("Toggle Recording", lambda icon, item: toggle_recording()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_tray_exit)
    )
    def run_tray():
        try:
            icon.run()
        except Exception as e:
            print(f"[-] Tray icon error: {e}")
    tray_thread = threading.Thread(target=run_tray, daemon=True)
    tray_thread.start()
    return icon

# GUI Setup
root = tk.Tk()
root.title("Simple Screen Recorder")
root.geometry("380x650")
root.resizable(False, False)

# Load configuration
saved_path, saved_replace_mode, saved_record_region, saved_selected_monitor, saved_show_cursor = load_config()
save_path = saved_path
save_path.mkdir(parents=True, exist_ok=True)
replace_mode = saved_replace_mode
record_region = saved_record_region
selected_monitor = saved_selected_monitor
show_cursor = saved_show_cursor

# GUI Elements
info_frame = tk.Frame(root, bg='lightgray', relief='sunken', bd=1)
info_frame.pack(fill='x', pady=(5, 10))
tk.Label(info_frame, text=f"Hotkeys: {hotkey.upper()} = Record | {window_toggle_key.upper()} = Hide/Show",
         bg='lightgray', font=('Arial', 8)).pack(pady=3)
tk.Label(root, text="Duration:").pack(pady=(10, 2))
duration_entry = tk.Entry(root, width=10)
duration_entry.pack()
duration_entry.insert(0, "10")
duration_unit = tk.StringVar(value="Seconds")
tk.OptionMenu(root, duration_unit, "Seconds", "Minutes", "Hours").pack(pady=5)
region_frame = tk.Frame(root, bg='lightyellow', relief='ridge', bd=2)
region_frame.pack(fill='x', padx=10, pady=5)
tk.Label(region_frame, text="📹 Recording Region", bg='lightyellow',
         font=('Arial', 10, 'bold')).pack(pady=(5, 2))
region_label = tk.Label(region_frame, text="Region: Full Screen (auto)",
                       bg='lightyellow', font=('Arial', 9), wraplength=320)
region_label.pack(pady=2)
region_btn_frame = tk.Frame(region_frame, bg='lightyellow')
region_btn_frame.pack(pady=(2, 5))
tk.Button(region_btn_frame, text="🎯 Select Region", command=select_region,
          bg="lightgreen", font=('Arial', 8)).pack(side='left', padx=2)
tk.Button(region_btn_frame, text="❌ Clear Region", command=clear_region,
          bg="lightcoral", font=('Arial', 8)).pack(side='left', padx=2)
tk.Button(region_btn_frame, text="🖥️ Select Screen", command=select_monitor_dialog,
          bg="lightblue", font=('Arial', 8)).pack(side='left', padx=2)
region_btn_frame = tk.Frame(region_frame, bg='lightyellow')
region_btn_frame.pack(pady=(2, 5))
tk.Button(region_btn_frame, text="Start Recording", command=start_recording,
          bg="lightgreen", font=('Arial', 8)).pack(side='left', padx=5)
tk.Button(region_btn_frame, text="Stop Recording", command=stop_recording,
          bg="lightcoral", font=('Arial', 8)).pack(side='right', padx=5)
cursor_toggle_btn = tk.Button(root, text=f"🖱️ Cursor: {'ON' if show_cursor else 'OFF'}",
                             command=toggle_cursor,
                             bg="green" if show_cursor else "red",
                             fg="white" if show_cursor else "black",
                             font=('Arial', 9, 'bold'))
cursor_toggle_btn.pack(pady=5)
tk.Button(root, text="👁️ Toggle Preview", command=start_preview,
         bg="lightblue", font=('Arial', 9, 'bold')).pack(pady=5)
replace_toggle_btn = tk.Button(root, text=f"📁 Replace Mode: {'ON' if replace_mode else 'OFF'}",
                              command=toggle_replace_mode,
                              bg="green" if replace_mode else "red",
                              fg="white" if replace_mode else "black",
                              font=('Arial', 9, 'bold'))
replace_toggle_btn.pack(pady=5)
tk.Button(root, text="Choose Save Folder", command=browse_folder).pack(pady=5)
directory_label = tk.Label(root, text=f"Save to:\n{save_path}", wraplength=320)
directory_label.pack(pady=5)
tk.Button(root, text="Open Last Recorded", command=open_last_recorded).pack(pady=5)
tk.Button(root, text="Open Save Folder", command=open_save_folder).pack(pady=5)
tk.Button(root, text="Delete Last Recorded", command=delete_last_recorded).pack(pady=5)
tk.Button(root, text="Delete ALL Recordings", command=delete_all_recordings,
          bg="darkred", fg="white").pack(pady=5)
tk.Button(root, text="Settings (Change Hotkeys)", command=open_settings).pack(pady=5)
status_label = tk.Label(root, text="Ready")
status_label.pack(pady=10)

# Update region label on startup
update_region_label()

# Bind events
root.bind("<Unmap>", on_minimize)
root.protocol("WM_DELETE_WINDOW", on_close)

# Register hotkeys
keyboard.add_hotkey(hotkey, toggle_recording)
keyboard.add_hotkey(window_toggle_key, toggle_window_visibility)

# Start system tray
tray_icon = setup_tray()

# Print startup info
print(f"[+] Screen Recorder started!")
print(f"[+] Press {hotkey.upper()} to start/stop recording")
print(f"[+] Press {window_toggle_key.upper()} to hide/show window")
print(f"[+] Replace mode: {'ON' if replace_mode else 'OFF'}")
print(f"[+] Cursor visibility: {'ON' if show_cursor else 'OFF'}")
if selected_monitor is not None:
    monitors = get_monitors()
    if selected_monitor < len(monitors):
        monitor = monitors[selected_monitor][1]
        print(f"[+] Recording screen {selected_monitor+1}: {monitor['width']}x{monitor['height']} at ({monitor['left']},{monitor['top']})")
    else:
        print(f"[-] Invalid screen {selected_monitor+1}, using primary screen")
elif record_region:
    x, y, w, h = record_region
    print(f"[+] Recording region: {w}x{h} at ({x},{y})")
else:
    print(f"[+] Recording: Primary screen")

root.mainloop()
