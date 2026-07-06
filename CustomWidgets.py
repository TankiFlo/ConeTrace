from datetime import datetime
from tools import extract_gps_data, get_file_birthtime
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QFileInfo, Qt, Signal

class AddVideoDialog(QDialog):
    """Dialog to show video metadata and input map coordinates before adding to canvas."""
    # @group Context/Dialog Menus:
    def __init__(self, file_path, default_lat, default_lon, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Video to Map")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        # Extract Standard Metadata
        file_info = QFileInfo(file_path)
        size_mb = file_info.size() / (1024 * 1024)
        birth_time_ms = get_file_birthtime(file_path)
        birth_time_str = datetime.fromtimestamp(birth_time_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S')

        # Attempt to extract GPS coordinates
        meta_lat, meta_lon = extract_gps_data(file_path)
        
        # Determine final coordinates and labeling
        if meta_lat is not None and meta_lon is not None:
            final_lat, final_lon = meta_lat, meta_lon
            gps_source_label = "Extracted from Metadata"
        else:
            final_lat, final_lon = default_lat, default_lon
            gps_source_label = "Map Center (Fallback)"

        # Add Metadata to Form
        form_layout.addRow("File:", QLabel(file_info.fileName()))
        form_layout.addRow("Size:", QLabel(f"{size_mb:.2f} MB"))
        form_layout.addRow("Created:", QLabel(birth_time_str))
        form_layout.addRow("GPS Source:", QLabel(gps_source_label))

        # Add Coordinate Inputs (pre-filled with metadata or default)
        self.lat_input = QLineEdit(str(final_lat))
        self.lon_input = QLineEdit(str(final_lon))
        
        form_layout.addRow("Latitude:", self.lat_input)
        form_layout.addRow("Longitude:", self.lon_input)
        
        layout.addLayout(form_layout)

        # OK / Cancel Buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        
        layout.addWidget(self.buttonBox)
        
        self.fallback_lat = default_lat
        self.fallback_lon = default_lon

    def get_coordinates(self):
        """Returns the parsed coordinates, falling back to defaults if parsing fails."""
        try:
            lat = float(self.lat_input.text())
            lon = float(self.lon_input.text())
            return lat, lon
        except ValueError:
            return self.fallback_lat, self.fallback_lon

    def get_coordinates(self):
        """Returns the parsed coordinates, falling back to defaults if parsing fails."""
        try:
            lat = float(self.lat_input.text())
            lon = float(self.lon_input.text())
            return lat, lon
        except ValueError:
            return self.fallback_lat, self.fallback_lon
        
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("About ConeTrace")
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Application Title
        title_label = QLabel("<h2>ConeTrace Forensics</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Application Info
        info_text = (
            "<p align='center'>A metadata-based analysis interface for correlating "
            "heterogeneous media data relating to major incidents.</p>"
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Third-Party Legal Notices for GPLv3 Compliance
        legal_text = (
            "<h3>Third-Party Software Notices:</h3>"
            "<p>This application bundles a pre-compiled, unmodified binary of <b>ffprobe</b>, "
            "which is part of the FFmpeg suite.</p>"
            "<p>FFmpeg is free software licensed under the "
            "<a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU General Public License v3 (GPLv3)</a>.</p>"
            "<p>To comply with the GPLv3, you can download the exact, corresponding source code "
            "for FFmpeg directly from the official repository at:<br>"
            "<a href='https://ffmpeg.org/download.html'>https://ffmpeg.org/download.html</a></p>"
        )
        
        legal_label = QLabel(legal_text)
        legal_label.setWordWrap(True)
        # This is the crucial part: it makes the links open in the user's default web browser
        legal_label.setOpenExternalLinks(True) 
        
        # Give it a slightly different background to distinguish it as a legal notice
        legal_label.setStyleSheet("background-color: #f5f5f5; padding: 12px; border-radius: 4px; color: #333333;")
        layout.addWidget(legal_label)
        
        # Standard OK Button to close the dialog
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

class MapEngineView(QWebEngineView):
    '''
    Component to display Folium maps and interact with them
    '''
    fileDropped = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            pos = event.position()
            event.acceptProposedAction()
            self.fileDropped.emit(file_path, pos.x(), pos.y())