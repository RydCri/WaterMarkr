### WaterMarkr

This project is ( hopefully ) a teachable example of using tkinter to make simple python-based self-contained apps.

The app accepts as input a folder containing images and outputs those images in a new subfolder with the chosen text or image watermarks applied.



Build commands

macOS
<br>
pyinstaller --onefile --windowed --add-data "fonts:fonts" --icon=app_icon.icns --name "WaterMarkr_v1.0.0" watermarker_app.py
<br>
windows
<br>
pyinstaller --onefile --windowed --add-data "fonts;fonts" --icon=app_icon.ico --name "WaterMarkr_v1.0.0_windows" watermarker_app.py

