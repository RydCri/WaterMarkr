import sys
import os
import platform
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QFileDialog, QLabel, QMessageBox, QProgressBar,
    QComboBox, QGroupBox, QRadioButton, QSizePolicy, QSpacerItem, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIntValidator

# Pillow for Image Processing
from PIL import Image, ImageDraw, ImageFont


# --- 1. Watermarking Worker Thread (Core Logic) ---

class WatermarkWorker(QThread):
    """A separate thread to handle the long-running watermarking process."""
    progress_updated = Signal(int)
    finished_processing = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, input_folder, watermark_type, text_or_path, wm_size_percent, wm_position, apply_filter=False):
        super().__init__()
        self.input_folder = Path(input_folder)
        self.watermark_type = watermark_type
        self.text_or_path = text_or_path
        self.wm_size_percent = wm_size_percent
        self.wm_position = wm_position
        self.apply_filter = apply_filter
        self.output_folder = self.input_folder / "watermarked_output"

    def _create_watermark_effect(self, img_path):
        """Converts an image from the path to black and white with 50% opacity."""
        try:
            # Open the image.
            img = Image.open(img_path).convert("RGBA")

            # 1. Convert to Grayscale (Luminance)
            bw_img = img.convert('L')

            # 2. Add an Alpha Channel and set opacity to 50% (128)
            L = bw_img  # Luminance is the new single channel

            # Create a new solid alpha channel set to 128 (50% opacity)
            new_alpha = Image.new('L', img.size, 128)

            # 3. Merge: L, L, L for R, G, B, and the new 50% alpha channel
            # This creates a grayscale image with a static 50% transparency layer
            watermark_img = Image.merge('RGBA', (L, L, L, new_alpha))

            return watermark_img

        except Exception as e:
            # Emit error if the watermark file itself is corrupted or missing
            self.error_occurred.emit(f"Failed to apply filter to watermark image: {e}")
            return None

    def run(self):
        try:
            # Create the output folder if it doesn't exist
            self.output_folder.mkdir(exist_ok=True)

            # Supported image file extensions
            image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp']

            # Find all image files
            image_files = []
            for ext in image_extensions:
                image_files.extend(list(self.input_folder.glob(ext)))

            total_files = len(image_files)
            if total_files == 0:
                self.error_occurred.emit("No supported image files found in the selected folder.")
                return

            # Process each file
            for i, input_path in enumerate(image_files):
                self._apply_watermark(input_path)
                progress_percent = int((i + 1) / total_files * 100)
                self.progress_updated.emit(progress_percent)

            self.finished_processing.emit(f"Successfully watermarked {total_files} files in: {self.output_folder.name}")

        except Exception as e:
            self.error_occurred.emit(f"An error occurred during batch processing: {e}")



    def _calculate_position(self, img_width, img_height, wm_width, wm_height, margin=20):
        """Helper to calculate X, Y coordinates based on the selected position."""

        x, y = 0, 0

        if self.wm_position == "Top-Left":
            x, y = margin, margin
        elif self.wm_position == "Top-Right":
            x = img_width - wm_width - margin
            y = margin
        elif self.wm_position == "Bottom-Left":
            x = margin
            y = img_height - wm_height - margin
        elif self.wm_position == "Bottom-Right":
            x = img_width - wm_width - margin
            y = img_height - wm_height - margin
        elif self.wm_position == "Center":
            x = (img_width - wm_width) // 2
            y = (img_height - wm_height) // 2

        return x, y

    def _apply_watermark(self, input_path):
        """Core Pillow watermarking logic for both Text and Image watermarks."""

        output_path = self.output_folder / input_path.name

        try:
            img = Image.open(input_path).convert("RGBA")
        except Exception:
            # Skip file if it can't be opened/converted
            return

        width, height = img.size

        if self.watermark_type == 'image':
            # --- Image Watermark Logic ---

            # 1. Open and (Conditionally) Filter the watermark PNG
            if self.apply_filter:
                wm_img = self._create_watermark_effect(self.text_or_path)
                if wm_img is None:
                    # If filtering failed, skip this file to prevent crashing
                    return
            else:
                # Open image without filtering
                try:
                    wm_img = Image.open(self.text_or_path).convert("RGBA")
                except FileNotFoundError:
                    return # Skip if file not found

            # 2. Resize the watermark based on the percentage of the main image width
            target_wm_width = int(width * (self.wm_size_percent / 100))
            wm_width, wm_height = wm_img.size
            target_wm_height = int(wm_height * (target_wm_width / wm_width))

            wm_img = wm_img.resize((target_wm_width, target_wm_height))

            x, y = self._calculate_position(width, height, target_wm_width, target_wm_height)

            # 4. Paste the watermark using its own alpha channel as a mask
            wm_alpha = wm_img.getchannel('A')
            img.paste(wm_img, (x, y), mask=wm_alpha)

        # --- Text Watermark Logic ---
        elif self.watermark_type == 'text':

            watermark_layer = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(watermark_layer)
            BASE_FONT_SIZE = int(height / 15)

            # 2. Apply user's percentage (self.wm_size_percent) as a scaling factor
            scaling_factor = self.wm_size_percent / 100.0

            # 3. Calculate FINAL font size
            font_size = int(BASE_FONT_SIZE * scaling_factor)

            # --- CRITICAL FIX: Ensure font_size is never 0 ---
            # Set a non-zero minimum, like 5 pixels, to prevent the error
            if font_size == 0:
                font_size = 5

            try:
                # 4. Load the font
                font = ImageFont.truetype("./fonts/arial.ttf", font_size)
            except IOError:
                font = ImageFont.load_default()
            # Measure text size using the correct Pillow 10+ method
            bbox = draw.textbbox((0, 0), self.text_or_path, font=font)
            textwidth = bbox[2] - bbox[0]
            textheight = bbox[3] - bbox[1]

            # Calculate position
            x, y = self._calculate_position(width, height, textwidth, textheight)

            # Draw the text: White with 50% opacity (Alpha=128)
            draw.text((x, y), self.text_or_path, font=font, fill=(255, 255, 255, 128))

            img = Image.alpha_composite(img, watermark_layer)

        # --- Final Save ---
        if output_path.suffix.lower() in ['.jpg', '.jpeg']:
            img = img.convert("RGB")

        img.save(output_path)


# --- 2. Main GUI Window (PySide6) ---

class WatermarkApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Batch Image Watermarker")
        self.setGeometry(100, 100, 700, 500)

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- UI Components ---

        # 1. Input Folder Selection
        folder_group = QGroupBox("1. Select Input Folder")
        folder_layout = QHBoxLayout(folder_group)
        self.input_folder_line = QLineEdit()
        self.input_folder_line.setPlaceholderText("Select the folder containing images...")
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.select_input_folder)
        folder_layout.addWidget(self.input_folder_line)
        folder_layout.addWidget(browse_button)
        main_layout.addWidget(folder_group)

        # 2. Watermark Type Selection
        type_group = QGroupBox("2. Choose Watermark Type")
        type_layout = QHBoxLayout(type_group)
        self.radio_text = QRadioButton("Text Watermark")
        self.radio_image = QRadioButton("Image Watermark (PNG)")
        self.radio_text.setChecked(True) # Default
        self.radio_text.toggled.connect(self.update_watermark_ui)
        self.radio_image.toggled.connect(self.update_watermark_ui)
        type_layout.addWidget(self.radio_text)
        type_layout.addWidget(self.radio_image)
        type_layout.addSpacerItem(QSpacerItem(
            40,
            20,
            QSizePolicy.Policy.Expanding, # Horizontal Policy
            QSizePolicy.Policy.Minimum    # Vertical Policy
        ))
        main_layout.addWidget(type_group)

        # 3. Watermark Configuration (Stacked Content)
        self.config_area = QWidget()
        self.config_layout = QVBoxLayout(self.config_area)
        self.config_layout.setContentsMargins(0, 0, 0, 0)

        # Create separate widgets for each type
        self.text_config_widget = self._create_text_config_ui()
        self.image_config_widget = self._create_image_config_ui()

        self.config_layout.addWidget(self.text_config_widget)
        self.config_layout.addWidget(self.image_config_widget)
        self.image_config_widget.hide() # Image is hidden by default

        main_layout.addWidget(self.config_area)

        # 4. Global Settings (Position and Process Button)
        global_group = QGroupBox("3. Placement and Processing")
        global_layout = QVBoxLayout(global_group)

        # Position Dropdown
        position_layout = QHBoxLayout()
        position_layout.addWidget(QLabel("Position:"))
        self.position_combo = QComboBox()
        self.position_combo.addItems(["Bottom-Right", "Top-Left", "Top-Right", "Bottom-Left", "Center"])
        position_layout.addWidget(self.position_combo)
        position_layout.addStretch()
        global_layout.addLayout(position_layout)

        # Output folder button
        self.open_output_button = QPushButton("📂 Open Output Folder")
        self.open_output_button.setEnabled(False) # Initially disabled
        self.open_output_button.clicked.connect(self.open_output_directory)

        # Status and Progress
        self.process_button = QPushButton("🚀 Start Watermarking")
        self.process_button.clicked.connect(self.start_watermarking)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignCenter) # not an attribute error, Qt accesses through nested class
        self.status_label = QLabel("Ready. Select a folder and configure the watermark.")

        global_layout.addWidget(self.process_button)
        global_layout.addWidget(self.progress_bar)
        global_layout.addWidget(self.open_output_button)
        global_layout.addWidget(self.status_label)
        main_layout.addWidget(global_group)

        main_layout.addStretch() # Push everything up

        self.watermark_thread = None


    # --- 2. Main GUI Window (PySide6) ---

    def _create_text_config_ui(self):
        """Creates the configuration widget for text watermarks."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Text Input
        layout.addWidget(QLabel("Watermark Text:"))
        self.text_line = QLineEdit()
        self.text_line.setPlaceholderText("Enter the watermark text (e.g., @MyBrandName)")
        layout.addWidget(self.text_line)

        # New Size Configuration
        size_layout = QHBoxLayout()
        # Change default from "6" to "100" (representing 100% scale)
        self.text_size_percent_line = QLineEdit("100")
        # Allow a reasonable scaling range, e.g., 50% to 300% of the base size
        self.text_size_percent_line.setValidator(QIntValidator(50, 300))
        size_layout.addWidget(QLabel("Size (as % of default scale):"))
        size_layout.addWidget(self.text_size_percent_line)
        size_layout.addWidget(QLabel("%"))
        layout.addLayout(size_layout)

        layout.addStretch()
        return widget

    def _create_image_config_ui(self):
        """Creates the configuration widget for image watermarks."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # File Selection
        file_layout = QHBoxLayout()
        self.image_path_line = QLineEdit()
        self.image_path_line.setPlaceholderText("Select the transparent PNG watermark file...")
        image_browse_button = QPushButton("Browse PNG...")
        image_browse_button.clicked.connect(self.select_image_watermark)
        file_layout.addWidget(QLabel("Image File:"))
        file_layout.addWidget(self.image_path_line)
        file_layout.addWidget(image_browse_button)
        layout.addLayout(file_layout)

        # Size Configuration
        size_layout = QHBoxLayout()
        self.size_percent_line = QLineEdit("15") # Default to 15% width
        self.size_percent_line.setValidator(QIntValidator(1, 100))
        size_layout.addWidget(QLabel("Width (as % of image):"))
        size_layout.addWidget(self.size_percent_line)
        size_layout.addWidget(QLabel("% (Maintains Aspect Ratio)"))
        size_layout.addStretch()
        layout.addLayout(size_layout)
        # layout.addStretch()

        # Filter Group
        filter_group = QGroupBox("Filter Options")
        filter_layout = QVBoxLayout(filter_group)
        self.filter_checkbox = QCheckBox("Apply B&W + 50% Opacity Filter")
        filter_layout.addWidget(self.filter_checkbox)
        layout.addWidget(filter_group)

        layout.addStretch()
        return widget



    def update_watermark_ui(self):
        """Switches between text and image configuration widgets."""
        if self.radio_text.isChecked():
            self.text_config_widget.show()
            self.image_config_widget.hide()
        else:
            self.text_config_widget.hide()
            self.image_config_widget.show()

    def select_input_folder(self):
        """Opens a dialog to select the input folder."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder_path:
            self.input_folder_line.setText(folder_path)
            self.status_label.setText(f"Folder selected: {Path(folder_path).name}")

    def select_image_watermark(self):
        """Opens a dialog to select the PNG watermark file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Watermark PNG", "", "PNG Files (*.png)")
        if file_path:
            self.image_path_line.setText(file_path)

    def start_watermarking(self):
        """Initiates the watermarking process, collecting all parameters."""
        input_folder = self.input_folder_line.text()
        wm_position = self.position_combo.currentText()
        apply_filter = False

        # Basic Validation
        if not input_folder or not os.path.isdir(input_folder):
            QMessageBox.warning(self, "Input Error", "Please select a valid input folder.")
            return

        # Parameter Collection based on type
        if self.radio_text.isChecked():
            watermark_type = 'text'
            text_or_path = self.text_line.text().strip()

            text_size_input = self.text_size_percent_line.text() or "6"
            wm_size_percent = int(text_size_input)

            if not text_or_path:
                QMessageBox.warning(self, "Input Error", "Please enter watermark text.")
                return
        else:
            watermark_type = 'image'
            text_or_path = self.image_path_line.text().strip()
            wm_size_percent = int(self.size_percent_line.text() or 10)
            apply_filter = self.filter_checkbox.isChecked()
            if not text_or_path or not os.path.isfile(text_or_path):
                QMessageBox.warning(self, "Input Error", "Please select a valid PNG watermark file.")
                return

        # Disable UI during processing
        self.process_button.setEnabled(False)
        self.status_label.setText("Processing... Please wait.")
        self.progress_bar.setValue(0)

        # Start the worker thread
        self.watermark_thread = WatermarkWorker(
            input_folder,
            watermark_type,
            text_or_path,
            wm_size_percent,
            wm_position,
            apply_filter=apply_filter
        )
        self.watermark_thread.progress_updated.connect(self.progress_bar.setValue)
        self.watermark_thread.finished_processing.connect(self.on_processing_complete)
        self.watermark_thread.error_occurred.connect(self.on_processing_error)
        self.watermark_thread.start()

    def open_output_directory(self):
        """Opens the watermarked_output folder in the user's file explorer."""
        input_folder = self.input_folder_line.text()
        if not input_folder:
            QMessageBox.warning(self, "Error", "No input folder selected.")
            return

        # Define the path to the output folder
        output_dir = Path(input_folder) / "watermarked_output"

        if not output_dir.exists():
            QMessageBox.warning(self, "Error", "Output folder not found yet. Run the process first.")
            return

        # Use platform-specific commands to open the directory
        system = platform.system()
        try:
            if system == "Windows":
                # Windows command: explorer /select, or just explorer for directory
                subprocess.Popen(['explorer', str(output_dir)])
            elif system == "Darwin":
                # macOS command
                subprocess.Popen(['open', str(output_dir)])
            else:
                # Linux command (works for most modern distros)
                subprocess.Popen(['xdg-open', str(output_dir)])
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", "Could not find file explorer command.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open directory: {e}")


    def on_processing_complete(self, message):
        """Handles successful completion."""
        self.status_label.setText(f"✅ DONE! {message}")
        self.process_button.setEnabled(True)
        self.open_output_button.setEnabled(True)
        QMessageBox.information(self, "Success", message)

    def on_processing_error(self, message):
        """Handles errors."""
        self.status_label.setText(f"❌ ERROR: {message}")
        self.progress_bar.setValue(0)
        self.process_button.setEnabled(True)
        self.open_output_button.setEnabled(False)
        QMessageBox.critical(self, "Error", message)


# --- 3. Run the Application ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WatermarkApp()
    window.show()
    sys.exit(app.exec())