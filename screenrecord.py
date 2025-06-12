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
import screeninfo
import pystray
from PIL import Image, ImageDraw
import sys
import threading as th

# Global control
is_recording = False
stop_flag = False
replace_mode = False
record_region = None
selected_monitor = None
region_border_window = None
show_cursor = True  # NEW: Track cursor visibility state

CONFIG_FILE = Path.home() / ".screen_recorder_config.json"

# --- Helper Functions ---
def get_monitors():
    try:
        monitors = screeninfo.get_monitors()
        return [(i, m) for i, m in enumerate(monitors)]
    except Exception as e:
        print(f"[-] Error getting monitors: {e}")
        return []

def convert_to_twitter_format(input_path):
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
    subprocess.run(ffmpeg_cmd)
    return output_path

def get_video_duration(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=duration', '-of',
             'default=noprint_wrappers=1:nokey=1', str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        return float(result.stdout)
    except Exception:
        return 10.0

def save_config(path, replace_mode=False, record_region=None, selected_monitor=None, show_cursor=True):  # NEW: Added show_cursor
    config = {
        "save_path": str(path),
        "replace_mode": replace_mode,
        "record_region": record_region,
        "selected_monitor": selected_monitor,
        "show_cursor": show_cursor  # NEW
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                path = Path(config.get("save_path", ""))
                replace_mode = config.get("replace_mode", False)
                record_region = config.get("record_region", None)
                selected_monitor = config.get("selected_monitor", None)
                show_cursor = config.get("show_cursor", True)  # NEW
                return path, replace_mode, record_region, selected_monitor, show_cursor
        except Exception:
            return None, False, None, None, True
    return None, False, None, None, True

def delete_old_recordings():
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
            selection_rect = canvas.create_rectangle(x1, y1, x2, y2, 
                                                  outline='red', width=3, fill='red', stipple='gray25')
    
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
                save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)  # NEW: Added show_cursor
                messagebox.showinfo("Region Selected", f"Recording region set to:\n{width}x{height} at ({x1},{y1})")
            else:
                overlay.destroy()
                root.deiconify()
                messagebox.showwarning("Invalid Selection", "Region too small. Please select a larger area.")
    
    def cancel_select(event):
        overlay.destroy()
        root.deiconify()
    
    instruction_label = tk.Label(overlay, text="Drag to select region • ESC to cancel • Enter for monitor selection", 
                               fg='white', bg='black', font=('Arial', 14, 'bold'))
    instruction_label.pack(pady=20)
    
    canvas.bind("<Button-1>", start_select)
    canvas.bind("<B1-Motion>", update_select)
    canvas.bind("<ButtonRelease-1>", end_select)
    overlay.bind("<Escape>", cancel_select)
    overlay.bind("<Return>", lambda e: select_monitor_dialog())
    
    overlay.focus_set()

def select_monitor_dialog():
    global selected_monitor, record_region
    monitors = get_monitors()
    
    if not monitors:
        messagebox.showerror("Error", "No monitors detected!")
        return
    
    dialog = tk.Toplevel(root)
    dialog.title("Select Monitor")
    dialog.geometry("300x150")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()
    
    tk.Label(dialog, text="Select Monitor to Record:", font=('Arial', 10, 'bold')).pack(pady=10)
    
    monitor_var = tk.StringVar(value="0")
    for i, monitor in monitors:
        tk.Radiobutton(dialog, text=f"Monitor {i+1}: {monitor.width}x{monitor.height} at ({monitor.x},{monitor.y})",
                      variable=monitor_var, value=str(i)).pack(anchor='w', padx=20)
    
    def confirm():
        global selected_monitor, record_region
        selected_monitor = int(monitor_var.get())
        record_region = None
        dialog.destroy()
        root.deiconify()
        update_region_label()
        save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)  # NEW: Added show_cursor
        monitor = monitors[selected_monitor][1]
        messagebox.showinfo("Monitor Selected", f"Recording set to Monitor {selected_monitor+1}: {monitor.width}x{monitor.height}")
    
    tk.Button(dialog, text="Confirm", command=confirm).pack(pady=10)
    tk.Button(dialog, text="Cancel", command=lambda: dialog.destroy() or root.deiconify()).pack(pady=5)

def update_region_label():
    if selected_monitor is not None:
        monitor = get_monitors()[selected_monitor][1]
        region_label.config(text=f"Region: Monitor {selected_monitor+1} ({monitor.width}x{monitor.height} at {monitor.x},{monitor.y})")
    elif record_region:
        x, y, w, h = record_region
        region_label.config(text=f"Region: {w}x{h} at ({x},{y})")
    else:
        region_label.config(text="Region: Full Screen (auto)")

def clear_region():
    global record_region, selected_monitor
    record_region = None
    selected_monitor = None
    update_region_label()
    save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)  # NEW: Added show_cursor
    messagebox.showinfo("Region Cleared", "Recording region cleared. Will record primary screen.")

def toggle_cursor():  # NEW: Function to toggle cursor visibility
    global show_cursor
    show_cursor = not show_cursor
    cursor_toggle_btn.config(text=f"🖱️ Cursor: {'ON' if show_cursor else 'OFF'}",
                           bg="green" if show_cursor else "red",
                           fg="white" if show_cursor else "black")
    save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)
    messagebox.showinfo("Cursor Visibility", f"Cursor in recordings: {'ON' if show_cursor else 'OFF'}")
    print(f"[+] Cursor visibility: {'ON' if show_cursor else 'OFF'}")

def record_screen(duration, fps=30):
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

    if selected_monitor is not None:
        monitor = get_monitors()[selected_monitor][1]
        x, y, width, height = monitor.x, monitor.y, monitor.width, monitor.height
        print(f"[+] Recording monitor {selected_monitor+1}: {width}x{height} at ({x},{y})")
    elif record_region:
        x, y, width, height = record_region
        print(f"[+] Recording region: {width}x{height} at ({x},{y})")
    else:
        screen_size = pyautogui.size()
        x, y = 0, 0
        width = min(screen_size[0], 1920)
        height = min(screen_size[1], 1080)
        print(f"[+] Recording primary screen: {width}x{height}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    filename = save_path / f"screen_record_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    out = cv2.VideoWriter(str(filename), fourcc, fps, (width, height))

    is_recording = True
    stop_flag = False
    status_text = f"Recording {'monitor ' + str(selected_monitor+1) if selected_monitor is not None else 'region' if record_region else 'primary screen'}..."
    status_label.config(text=status_text)

    start_time = time.time()

    try:
        while time.time() - start_time < duration:
            if stop_flag:
                break
            img = pyautogui.screenshot(region=(x, y, width, height))
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGR2RGB)
            
            # NEW: Draw cursor if show_cursor is True
            if show_cursor:
                try:
                    cursor_x, cursor_y = pyautogui.position()
                    # Adjust cursor coordinates to be relative to the recording region
                    rel_x = cursor_x - x
                    rel_y = cursor_y - y
                    if 0 <= rel_x < width and 0 <= rel_y < height:
                        # Draw a simple cursor (e.g., white circle with black outline)
                        cv2.circle(frame, (rel_x, rel_y), 5, (0, 0, 0), 1)  # Black outline
                        cv2.circle(frame, (rel_x, rel_y), 3, (255, 255, 255), -1)  # White fill
                except Exception as e:
                    print(f"[-] Error drawing cursor: {e}")

            out.write(frame)
            time.sleep(1 / fps)
    except Exception as e:
        print(f"[-] Recording error: {e}")
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
    region_text = f" (Monitor {selected_monitor+1})" if selected_monitor is not None else " (Region)" if record_region else " (Primary Screen)"
    status_label.config(text=f"Saved Twitter-ready{mode_text}{region_text}:\n{twitter_file}")
    print(f"[+] Saved Twitter-ready: {twitter_file}")

def toggle_replace_mode():
    global replace_mode
    replace_mode = not replace_mode
    replace_toggle_btn.config(text=f"📁 Replace Mode: {'ON' if replace_mode else 'OFF'}", 
                            bg="green" if replace_mode else "red",
                            fg="white" if replace_mode else "black")
    save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)  # NEW: Added show_cursor
    messagebox.showinfo("Mode Changed", f"{'Replace' if replace_mode else 'Accumulate'} Mode: {'New recordings will delete old ones' if replace_mode else 'Keep all recordings'}")
    print(f"[+] Replace mode: {'ON' if replace_mode else 'OFF'}")

def start_recording():
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
    global stop_flag
    if is_recording:
        stop_flag = True

def toggle_recording():
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
        print(f"Error toggling window: {e}")

def browse_folder():
    global save_path
    folder = filedialog.askdirectory(initialdir=str(Path.home()), title="Select Save Directory")
    if folder:
        save_path = Path(folder)
        save_path.mkdir(parents=True, exist_ok=True)
        directory_label.config(text=f"Save to:\n{save_path}")
        save_config(save_path, replace_mode, record_region, selected_monitor, show_cursor)  # NEW: Added show_cursor

def open_settings():
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
    if last_recorded_file and last_recorded_file.exists():
        os.startfile(last_recorded_file)
    else:
        messagebox.showinfo("No Recording", "No recent recording to open.")

def open_save_folder():
    os.startfile(save_path)

def delete_last_recorded():
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
    if root.state() == 'iconic':
        root.withdraw()
        status_label.config(text="Running in background... (use hotkey or tray to restore)")

def on_close():
    root.withdraw()
    status_label.config(text="Running in background... (use hotkey or tray to restore)")

def create_image():
    image = Image.new('RGB', (64, 64), color='black')
    dc = ImageDraw.Draw(image)
    dc.rectangle((16, 16, 48, 48), fill='white')
    return image

def on_tray_open(icon, item):
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
            print(f"Error restoring window: {e}")
    
    root.after(0, restore_window)

def on_tray_exit(icon, item):
    def exit_app():
        try:
            keyboard.unhook_all()
            icon.stop()
            root.quit()
            root.destroy()
        except:
            pass
    
    root.after(0, exit_app)

def setup_tray():
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
            print(f"Tray icon error: {e}")
    
    tray_thread = th.Thread(target=run_tray, daemon=True)
    tray_thread.start()
    return icon

# --- GUI Setup ---
root = tk.Tk()
root.title("Simple Screen Recorder")
root.geometry("380x650")  # NEW: Slightly taller to accommodate cursor toggle
root.resizable(False, False)

# Load config
saved_path, saved_replace_mode, saved_record_region, saved_selected_monitor, saved_show_cursor = load_config()  # NEW: Added show_cursor
if saved_path and saved_path.exists():
    save_path = saved_path
    replace_mode = saved_replace_mode
    record_region = saved_record_region
    selected_monitor = saved_selected_monitor
    show_cursor = saved_show_cursor  # NEW
else:
    save_path = Path.home() / "Videos" / "Python Videos"
    replace_mode = False
    record_region = None
    selected_monitor = None
    show_cursor = True  # NEW
save_path.mkdir(parents=True, exist_ok=True)

hotkey = 'ctrl+shift+r'
window_toggle_key = 'f12'
last_recorded_file = None

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

# Region Selection Frame
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
tk.Button(region_btn_frame, text="🖥️ Select Monitor", command=select_monitor_dialog, 
          bg="lightblue", font=('Arial', 8)).pack(side='left', padx=2)
tk.Button(region_btn_frame, text="❌ Clear", command=clear_region, 
          bg="lightcoral", font=('Arial', 8)).pack(side='left', padx=2)

# Update region label with saved settings
update_region_label()

# NEW: Cursor Toggle Button
cursor_toggle_btn = tk.Button(root, text=f"🖱️ Cursor: {'ON' if show_cursor else 'OFF'}", 
                             command=toggle_cursor, 
                             bg="orange" if show_cursor else "lightblue",
                             fg="white" if show_cursor else "black",
                             font=('Arial', 9, 'bold'))
cursor_toggle_btn.pack(pady=5)

replace_toggle_btn = tk.Button(root, text=f"📁 Replace Mode: {'ON' if replace_mode else 'OFF'}", 
                              command=toggle_replace_mode, 
                              bg="orange" if replace_mode else "lightblue",
                              fg="white" if replace_mode else "black",
                              font=('Arial', 9, 'bold'))
replace_toggle_btn.pack(pady=5)

tk.Button(root, text="Choose Save Folder", command=browse_folder).pack(pady=5)
directory_label = tk.Label(root, text=f"Save to:\n{save_path}", wraplength=320)
directory_label.pack(pady=5)

tk.Button(root, text="Start Recording", command=start_recording, bg="green", fg="white").pack(pady=5)
tk.Button(root, text="Stop Recording", command=stop_recording, bg="red", fg="white").pack(pady=5)
tk.Button(root, text="Open Last Recorded", command=open_last_recorded).pack(pady=5)
tk.Button(root, text="Open Save Folder", command=open_save_folder).pack(pady=5)
tk.Button(root, text="Delete Last Recorded", command=delete_last_recorded).pack(pady=5)
tk.Button(root, text="Delete ALL Recordings", command=delete_all_recordings, 
          bg="darkred", fg="white").pack(pady=5)
tk.Button(root, text="Settings (Change Hotkeys)", command=open_settings).pack(pady=5)

status_label = tk.Label(root, text="Ready")
status_label.pack(pady=10)

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
print(f"[+] Cursor visibility: {'ON' if show_cursor else 'OFF'}")  # NEW
if selected_monitor is not None:
    monitor = get_monitors()[selected_monitor][1]
    print(f"[+] Recording monitor {selected_monitor+1}: {monitor.width}x{monitor.height} at ({monitor.x},{monitor.y})")
elif record_region:
    x, y, w, h = record_region
    print(f"[+] Recording region: {w}x{h} at ({x},{y})")
else:
    print(f"[+] Recording: Primary screen")

root.mainloop()
