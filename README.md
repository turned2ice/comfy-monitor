# Comfy Monitor
a vibecoded widget for Windows to have a clue how sampling goes without looking at ComfyUI tab or task manager

## Features and overview:

 - Sampling step progress with elapsed and expected time
 - Sampling preview with video support
 - Hardware graphs incuding vram/ram load and drives usage
 - Switch between preview and graph mode
 - Shrink to small version with progress bar only
 - Hide to tray
 - Right-click on tray icon to edit settings: full color customization, set ComfyUI host adress and which drives to display 
 - Resize by bottom-right corner
 
## Installation:

 1. Download/clone repo somewhere
 2. Install requirements for system-wide python (**pip install -r requirements.txt**)
 3. Install [KJNodes](https://github.com/kijai/ComfyUI-KJNodes) and wire the **Model Preview Override** node to your workflow. For video previews tweak the **preview_frames** and **preview_fps** as you need. There is also a tae option for MiniMax H3 model.
 4. Put **comfy_widget_bridge.py** in **custom_nodes** comfy folder
 5. Run **main.pyw**


