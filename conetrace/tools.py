import datetime
import json
import math
import os
import random
import re
import subprocess
import sys

import cv2
import numpy as np
import requests

def map_num(num, inMin, inMax, outMin, outMax):
  '''Maps a number from one range to another
  
  :param num: the current value to map to another range
  :param inMax inMin: the ``inRange`` of the current value
  :param outMax outMin: the ``outRange`` of the wanted value
  :return: ``num`` mapped to ``outRange``
  '''
  return outMin + (float(num - inMin) / float(inMax - inMin) * (outMax
                  - outMin))

def get_base_path():
    """
    Returns the absolute path of the directory containing the running script or .exe.
    This guarantees safe file creation when bundled with PyInstaller.
    """
    if getattr(sys, 'frozen', False):
        # We are running as a PyInstaller bundle (.exe)
        return os.path.dirname(sys.executable)
    else:
        # We are running as a normal Python script (.py)
        return os.path.dirname(os.getcwd() + "/")

def find_closest_grid(n):
    """
    Finds rows and columns (r, c) such that r * c >= n,
    minimizing both empty slots and the difference between r and c.
    """
    if n <= 0: return sorted((0, 0))
    val = math.ceil(math.sqrt(n))
    
    while True:
        # Check if the current value can form a valid grid
        for i in range(val, 0, -1):
            if i * val >= n:
                # Found the closest square-like factors
                if (val * (i - 1)) >= n:
                    continue
                return sorted((i, val))
        val += 1

def clear_layout(layout):
    for i in reversed(range(layout.count())): 
        layout.itemAt(i).widget().setParent(None)

def get_file_birthtime(file_path):
    stat = os.stat(file_path)
    return int(getattr(stat, 'st_birthtime', stat.st_mtime) * 1000)

def get_ffprobe_path():
    """
    Returns the correct path to ffprobe.exe. 
    Checks if running as a bundled PyInstaller app or a normal script.
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller extracts bundled files to a temp folder at sys._MEIPASS
        return os.path.join(sys._MEIPASS, 'ffprobe.exe')
    
    # If not bundled, assume ffprobe is in the system PATH or same directory
    return 'ffprobe'

def extract_gps_data(video_path):
    """
    Extracts static GPS data from a video file and returns a (lat, lon) tuple.
    """
    ffprobe_exe = get_ffprobe_path()
    
    # Command to extract only the format tags in JSON format for speed
    cmd = [
        ffprobe_exe,
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_entries', 'format_tags=location',
        video_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        location_string = data.get('format', {}).get('tags', {}).get('location')

        if not location_string:
            print("No GPS data found in this video.")
            return None, None

        # GPS data in video is typically stored in ISO 6709 format: +DD.DDDD+DDD.DDDD/
        # This regex extracts the latitude and longitude float values
        match = re.search(r'([+-]\d+\.\d+)([+-]\d+\.\d+)', location_string)
        
        if match:
            lat = float(match.group(1))
            lon = float(match.group(2))
            return (lat, lon)
        else:
            print(f"Could not parse location string: {location_string}")
            return None, None

    except FileNotFoundError:
        print("Error: ffprobe executable not found. Ensure it is bundled or in your PATH.")
    except subprocess.CalledProcessError as e:
        print(f"ffprobe encountered an error: {e}")
    except json.JSONDecodeError:
        print("Error decoding ffprobe output.")

    return None, None

def get_user_gps_data():
    response = requests.get('https://ipinfo.io/')
    data = response.json()
    loc = data['loc'].split(',')
    return float(loc[0]), float(loc[1])

def generate_noise_video_with_gps():
    """Requires ffmpeg to be installed properly"""
    filename_temp = "temp_noise.mp4"
    filename_final = "noise_with_gps.mp4"
    width, height = 1280, 720
    fps = 30
    duration = 5  # seconds
    total_frames = fps * duration

    # Generate a random starting location
    lat = random.uniform(-80, 80)
    lon = random.uniform(-170, 170)

    # Initialize OpenCV Video Writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename_temp, fourcc, fps, (width, height))

    print("Generating noise frames...")
    for i in range(total_frames):
        # Generate random static/noise
        frame = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)

        # Simulate slight movement to make the telemetry dynamic
        lat += random.uniform(-0.0005, 0.0005)
        lon += random.uniform(-0.0005, 0.0005)

        # Burn GPS coordinates visually onto the frame for easy debugging
        text = f"Lat: {lat:.5f} | Lon: {lon:.5f}"
        cv2.putText(frame, text, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        
        # Add a frame counter
        cv2.putText(frame, f"Frame: {i+1}/{total_frames}", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        out.write(frame)

    out.release()
    print(f"Temporary video saved to {filename_temp}")

    # Format location to ISO 6709 standard (e.g., +52.5200+013.4050/)
    iso6709_location = f"{lat:+.4f}{lon:+.4f}/"
    
    # Generate an ISO 8601 timestamp for creation_time
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    print("Injecting GPS and creation_time metadata via FFmpeg...")
    
    # FFmpeg command to copy the video stream and add metadata without re-encoding
    command = [
        'ffmpeg', '-y', '-i', filename_temp,
        '-metadata', f'location={iso6709_location}',
        '-metadata', f'creation_time={current_time}',
        '-codec', 'copy', filename_final
    ]

    try:
        # Run FFmpeg silently
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Success! Final video with metadata saved to '{filename_final}'")
        
        # Clean up the temporary file
        os.remove(filename_temp)
        
    except FileNotFoundError:
        print("\nError: FFmpeg is not installed or not in your system PATH.")
        print(f"The video was generated, but metadata could not be injected. Saved as '{filename_temp}'")
    except subprocess.CalledProcessError:
        print("\nError: FFmpeg failed to process the video.")

def detect_darkmode_in_windows(default = True): 
    """
    Source - https://stackoverflow.com/a/65349866 \\
    Posted by Maximilian Peters, modified by community. See post 'Timeline' for change history \\
    Retrieved 2026-07-06, License - CC BY-SA 4.0

    - It checks if `winreg` can be imported, if not you are probably not using Windows
    - The relevant registry key is searched, if not found, it is assumed that dark mode is not enabled
    - If the registry key is present and the value is set to 0, dark mode is set

    :param boolean default: wether the default mode should be light (`False`) or dark (`True`)
    """
    try:
        import winreg
    except ImportError:
        return default
    registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
    reg_keypath = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'
    try:
        reg_key = winreg.OpenKey(registry, reg_keypath)
    except FileNotFoundError:
        return default

    for i in range(1024):
        try:
            value_name, value, _ = winreg.EnumValue(reg_key, i)
            if value_name == 'AppsUseLightTheme':
                return value == 0
        except OSError:
            break
    return default