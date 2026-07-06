# pyinstaller main.py -n ConeTrace --add-binary ./res/ffprobe.exe:./ --upx-dir ./res/upx-5.2.0-win64/ --onefile --noconsole
import io
import sys
import json
import folium
from datetime import datetime, timedelta, timezone
from itertools import chain

from PySide6.QtWidgets import QApplication, QDial, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QMainWindow, QMenu, QMessageBox, QSizePolicy, QSlider, QStatusBar, QVBoxLayout, QWidget, QLabel, QLineEdit, QPushButton
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QFileInfo, QSettings, QTimer, QUrl, Qt
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import QAction, QFont

from tools import find_closest_grid, clear_layout, get_file_birthtime, get_user_gps_data, detect_darkmode_in_windows
from ForensicLogger import ForensicLogger
from CustomEventFilter import GlobalSpacebarFilter, VideoRightClickFilter, ProportionResizeFilter
from CustomWidgets import AddVideoDialog, MapEngineView, AboutDialog
from VideoTimeline import VideoTimeline
from BackendBridge import BackendBridge
from AspectRatioWrapper import AspectRatioWrapper

class MainWindow(QMainWindow):
    '''
    The one window to rule them all
    '''
    # @group Start of Main Window:
    def __init__(self):
        self.f_logger = ForensicLogger()
        self.f_logger.log("START")
        
        super().__init__()

        self.lat, self.lon = get_user_gps_data()
        self.zoom = 10

        self.lastSemiParameters = {'marker_id' : "", 'r' : 0, 'dir' : 0, 'arc' : 0}

        self.lastSaved = -1
        '''The last time SAVE has been activated in UTC, POSIX timestamp in ms'''
        self.timeDeltaBetweenSavesBeforeWarning = 60000
        '''How many ms can go between saves, before a warning is issued when wanting to leave the programm'''
        self.current_file_path = None

        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.playback_tick)

        self.setWindowTitle("ConeTrace")
        self.setWindowState(Qt.WindowMaximized)
        self.setMinimumSize(960, 540)

        self.active_marker_id = None

        self.map_view = MapEngineView()
        self.map_view.fileDropped.connect(self.handle_file_drop)

        self.channel = QWebChannel()
        self.bridge = BackendBridge()
        self.channel.registerObject("backend", self.bridge)
        self.map_view.page().setWebChannel(self.channel)
        
        self.bridge.markerClicked.connect(self.handle_marker_click)
        self.bridge.mapClicked.connect(self.handle_map_click) 
        self.bridge.semiCircleReturned.connect(self.handle_semicircle_return)
        self.bridge.markerMoved.connect(self.handle_marker_moved)

        self.video_markers = {}
        self.currentlyComparingVideos = []

        self.marker_colors = ["#6160a3", "#699000", "#bf2f97", "#16efc2", "#c71046", "#009b49", "#b194ff", "#bb9600", "#0167cb", "#c26b00", "#381255", "#a3e4a0", "#91004d", "#596e00", "#ff74ad", "#cebe73", "#5d0e00", "#ff954b", "#d93f3d"]
        """A list of 19 unique colors, adjusted for colorblindness. Generated using https://medialab.github.io/iwanthue/"""
        self.color_index = 0

        self.setupUi()
        self.init_map()

        self.spacebar_filter = GlobalSpacebarFilter(self.toggle_playback, self)
        QApplication.instance().installEventFilter(self.spacebar_filter)

        self.toggle_dark_mode(self.dark_action.isChecked())

    # @group Setup UI:
    def setupUi(self):
        self.centralwidget = QWidget(parent=self)
        self.setCentralWidget(self.centralwidget)

        # Main Layout attached directly to central widget for automatic scaling
        self.mainVerticalLayout = QVBoxLayout(self.centralwidget)
        self.mainVerticalLayout.setContentsMargins(10, 10, 10, 10)
        self.mainVerticalLayout.setSpacing(10)

        self.mainHorizontalLayout = QHBoxLayout()
        self.videoAreaVertical = QVBoxLayout()

        # ==========================================
        # VIDEO COMPARISON AREA (Top Grid)
        # ==========================================
        self.videoComparisonArea = QGridLayout()
        self.videoComparisonArea.setSpacing(1)
        self.videoComparisonArea.setContentsMargins(0, 0, 0, 0)
        self.videoAreaVertical.addLayout(self.videoComparisonArea)

        # ==========================================
        # VIDEO PREVIEW AREA (Bottom Grid)
        # ==========================================
        self.videoPreviewArea = QGridLayout()
        self.videoAreaVertical.addLayout(self.videoPreviewArea)

        self.mainHorizontalLayout.addLayout(self.videoAreaVertical, 5)

        # ==========================================
        # MAP AREA
        # ==========================================
        self.mapArea = QVBoxLayout()
        self.mainHorizontalLayout.addLayout(self.mapArea, 4)

        # PREVIEW & MAP PARAMETERS
        self.preview_parameterArea = QHBoxLayout()
        self.mapArea.addLayout(self.preview_parameterArea)

        # Preview
        self.moveToCompareButt = QPushButton("<<")
        self.moveToCompareButt.setStatusTip("Move Video to Comparison Area")
        self.moveToCompareButt.clicked.connect(self.moveQuickPreviewToComparisonArea)
        self.preview_parameterArea.addWidget(self.moveToCompareButt)

        self.videoQuickPreview = QVideoWidget(parent=self.centralwidget)

        quick_preview_policy = self.videoQuickPreview.sizePolicy()
        quick_preview_policy.setRetainSizeWhenHidden(True)
        self.videoQuickPreview.setSizePolicy(quick_preview_policy)

        self.preview_click_filter = VideoRightClickFilter(None, self.showPreviewContextMenu, self.videoQuickPreview)
        self.videoQuickPreview.installEventFilter(self.preview_click_filter)

        self.videoQuickPreview_container = AspectRatioWrapper(self.videoQuickPreview, ratio=16.0/9.0)
        self.videoQuickPreview_container.setMinimumWidth(160)
        
        self.videoQuickPreview_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.videoQuickPreview_container.setStyleSheet("background-color: black;")
        
        self.videoQuickPreview_MP = QMediaPlayer()
        self.videoQuickPreview_AO = QAudioOutput()
        self.videoQuickPreview_MP.setAudioOutput(self.videoQuickPreview_AO)
        self.videoQuickPreview_MP.setVideoOutput(self.videoQuickPreview)
        self.videoQuickPreview_AO.setVolume(0)
        self.preview_parameterArea.addWidget(self.videoQuickPreview_container, 1)

        # Parameter
        self.parameterParentWidget = QWidget()
        self.parameterParentWidget.setObjectName("parameterContainer")
        self.parameterParentWidget.setFixedHeight(90)
        self.parameterParentLayout = QHBoxLayout(self.parameterParentWidget)

        self.parameterWidget = QWidget()
        self.parameterWidget.setFixedHeight(90)
        param_policy = self.parameterWidget.sizePolicy()
        param_policy.setRetainSizeWhenHidden(True)
        self.parameterWidget.setSizePolicy(param_policy)
        self.parameterLayout = QHBoxLayout(self.parameterWidget)

        self.paramNameLabel = QLabel()
        boldfont = QFont()
        boldfont.setBold(True)
        self.paramNameLabel.setFont(boldfont)

        self.paramNameLabel.setMinimumWidth(75)
        label_policy = self.paramNameLabel.sizePolicy()
        label_policy.setHorizontalPolicy(QSizePolicy.Ignored)
        self.paramNameLabel.setSizePolicy(label_policy)

        self.label_resize_filter = ProportionResizeFilter(self.paramNameLabel, width_ratio=0.15, parent=self.parameterWidget)
        self.parameterWidget.installEventFilter(self.label_resize_filter)

        # Radius
        radius_layout = QVBoxLayout()
        self.radiusLabel = QLabel("Radius (m):")
        self.radiusLabel.setAlignment(Qt.AlignCenter)
        self.paramRadiusInput = QLineEdit("500")
        self.paramRadiusInput.textChanged.connect(self.apply_semi_parameters)
        radius_layout.addWidget(self.radiusLabel)
        radius_layout.addWidget(self.paramRadiusInput)
        
        # Arc (Angle)
        arc_layout = QVBoxLayout()
        self.arcLabel = QLabel("Arc: 90°")
        self.arcLabel.setAlignment(Qt.AlignCenter)
        self.paramArcSlider = QSlider(Qt.Horizontal)
        self.paramArcSlider.setRange(1, 360)
        self.paramArcSlider.valueChanged.connect(self.apply_semi_parameters)
        self.paramArcSlider.valueChanged.connect(self.update_arc_label) # New connection
        arc_layout.addWidget(self.arcLabel)
        arc_layout.addWidget(self.paramArcSlider)
        self.label_resize_filter = ProportionResizeFilter(self.arcLabel, width_ratio=0.15, parent=self.parameterWidget)
        self.parameterWidget.installEventFilter(self.label_resize_filter)

        # Direction
        dir_layout = QVBoxLayout()
        self.dirLabel = QLabel("Dir: 0°")
        self.dirLabel.setAlignment(Qt.AlignCenter)
        self.paramDirDial = QDial()
        self.paramDirDial.setRange(0, 360)
        self.paramDirDial.setSingleStep(5)
        self.paramDirDial.setPageStep(90)
        self.paramDirDial.setWrapping(True)
        self.paramDirDial.valueChanged.connect(self.apply_semi_parameters)
        self.paramDirDial.valueChanged.connect(self.update_dir_label) # New connection
        dir_layout.addWidget(self.dirLabel)
        dir_layout.addWidget(self.paramDirDial)

        keyframe_layout = QVBoxLayout()
        self.addKeyframeButt = QPushButton("Add Keyframe")
        self.addKeyframeButt.clicked.connect(self.add_keyframe)
        keyframe_layout.addWidget(self.addKeyframeButt)
        self.removeKeyframeButt = QPushButton("Remove Keyframe")
        self.removeKeyframeButt.clicked.connect(self.remove_last_keyframe)
        keyframe_layout.addWidget(self.removeKeyframeButt)

        self.parameterLayout.addWidget(self.paramNameLabel, stretch=1)
        self.parameterLayout.addLayout(radius_layout, stretch=0)
        self.parameterLayout.addLayout(arc_layout, stretch=0)
        self.parameterLayout.addLayout(dir_layout, stretch=0)
        self.parameterLayout.addLayout(keyframe_layout, stretch=0)

        self.parameterParentLayout.addWidget(self.parameterWidget)
        self.preview_parameterArea.addWidget(self.parameterParentWidget, 2)

        self.parameterWidget.hide()

        # TODO record videos (s. list in latex file)
        # TODO FIX crash when loading files too far apart?

        self.mapArea.addWidget(self.map_view, 4)
        self.mainVerticalLayout.addLayout(self.mainHorizontalLayout)

        # Bottom Timeline
        self.timelineSlider = VideoTimeline(parent=self.centralwidget)
        self.timelineSlider.setMinimum(0)
        self.timelineSlider.setOrientation(Qt.Orientation.Horizontal)
        # self.timelineSlider.sliderMoved.connect(self.seek)
        self.timelineSlider.valueChanged.connect(self.seek)
        self.timelineSlider.setSingleStep(17) # 1 Frame is about 127 ms at 60FPS
        self.timelineSlider.setPageStep(1000)
        self.mainVerticalLayout.addWidget(self.timelineSlider)

        self.playPauseButton = QPushButton("PLAY")
        self.playPauseButton.clicked.connect(self.toggle_playback)
        self.mainVerticalLayout.addWidget(self.playPauseButton)
        
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        edit_menu = menu.addMenu("&Edit")
        view_menu = menu.addMenu("&View")
        help_menu = menu.addMenu("&Help")

        # ==========
        # HELP MENU
        # ==========
        
        self.dark_action = QAction("Dark Mode", self)
        self.dark_action.setCheckable(True)
        is_dark = detect_darkmode_in_windows()
        self.dark_action.setChecked(is_dark)
        self.dark_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(self.dark_action)

        # ==========
        # HELP MENU
        # ==========
        
        about_action = QAction("About / Legal", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        # ==========
        # FILE MENU
        # ==========
        new_button = QAction("New", self)
        new_button.triggered.connect(self.new_canvas)
        new_button.setShortcut("Ctrl+N")
        file_menu.addAction(new_button)

        open_button = QAction("Open", self)
        open_button.triggered.connect(self.load_canvas)
        open_button.setShortcut("Ctrl+O")
        file_menu.addAction(open_button)

        self.recent_menu = file_menu.addMenu("Open Recent")
        self.update_recent_files_menu()

        file_menu.addSeparator()

        save_button = QAction("Save", self)
        save_button.triggered.connect(self.save_canvas)
        save_button.setShortcut("Ctrl+S")
        file_menu.addAction(save_button)
        
        save_button = QAction("Save As...", self)
        save_button.triggered.connect(self.save_as_canvas)
        save_button.setShortcut("Ctrl+Shift+S")
        file_menu.addAction(save_button)
        
        file_menu.addSeparator()

        save_log_as_human_button = QAction("Save log to human-readable file", self)
        save_log_as_human_button.triggered.connect(lambda: self.f_logger.jsonl_to_human_readable()) # use lambda function, because PySide overwrites default value of `human_file` with False otherwise
        file_menu.addAction(save_log_as_human_button)

        file_menu.addSeparator()

        exit_button = QAction("Exit", self)
        exit_button.triggered.connect(self.exit_program)
        file_menu.addAction(exit_button)
        
        # ==========
        # EDIT MENU
        # ==========
        add_to_comp_button = QAction("Add Quick Preview to comparison", self)
        add_to_comp_button.triggered.connect(self.moveQuickPreviewToComparisonArea)
        edit_menu.addAction(add_to_comp_button)
        
        edit_menu.addSeparator()

        add_video_action = QAction("Add Video from File...", self)
        add_video_action.triggered.connect(self.open_add_video_dialog)
        edit_menu.addAction(add_video_action)

        self.remove_video_action = QAction("Remove Last Video Marker", self)
        self.remove_video_action.setShortcut("Ctrl+Shift+Z")
        self.remove_video_action.triggered.connect(self.remove_last_video_marker)
        edit_menu.addAction(self.remove_video_action)
        
        edit_menu.addSeparator()

        self.tracking_points = []
        self.paint_mode_active = False

        self.paint_mode_button = QAction("Paint Mode: OFF", parent=self.map_view)
        self.paint_mode_button.setShortcut("Ctrl+F")
        self.paint_mode_button.setCheckable(True)
        self.paint_mode_button.triggered.connect(self.toggle_paint_mode)
        edit_menu.addAction(self.paint_mode_button)

        self.remove_track_action = QAction("Remove Last Tracking Point", self)
        self.remove_track_action.setShortcut("Ctrl+Z") 
        self.remove_track_action.triggered.connect(self.remove_last_tracking_point)
        edit_menu.addAction(self.remove_track_action)

        # ==========
        # This was a consideration to add, I'll leave it for now, but it probably will be left commented

        # edit_menu.addSeparator()

        # self.remove_kf_action = QAction("Remove Last Parameter Keyframe from current active video", self)
        # self.remove_kf_action.setShortcut("Ctrl+Alt+Z")
        # self.remove_kf_action.triggered.connect(self.remove_last_keyframe)
        # edit_menu.addAction(self.remove_kf_action)

        # remove_from_comp_button = QAction("Remove from comparison", self)
        # remove_from_comp_button.triggered.connect(self.removeVideoFromComparison)
        # file_menu.addAction(remove_from_comp_button)

        self.statusbar = QStatusBar(self)
        self.setStatusBar(self.statusbar)

    def setupVideoCompareUi(self):
        clear_layout(self.videoComparisonArea)

        # we add these lines to fix ghost stretches (e.g. when going from 2x1 to 1x1)
        for r in range(self.videoComparisonArea.rowCount()):
            self.videoComparisonArea.setRowStretch(r, 0)
        for c in range(self.videoComparisonArea.columnCount()):
            self.videoComparisonArea.setColumnStretch(c, 0)

        self.videoCompare_MPs = []
        n = len(self.currentlyComparingVideos)
        
        if n == 0:
            return
            
        rows, cols = find_closest_grid(n)

        # Force the grid to maintain equal, fixed cell sizes
        for r in range(rows):
            self.videoComparisonArea.setRowStretch(r, 1)
        for c in range(cols):
            self.videoComparisonArea.setColumnStretch(c, 1)

        for r in range(rows):
            for c in range(cols):
                i = r * cols + c
                if i < n:
                    videoCompareWidget = QWidget()
                    videoCompareWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                    
                    videoCompareVLayout = QVBoxLayout(videoCompareWidget)

                    videoCompareName = QLabel(self.currentlyComparingVideos[i]['name'])
                    videoCompareName.setMaximumHeight(20)

                    videoCompare = QVideoWidget(parent=self.centralwidget)
                    
                    click_filter = VideoRightClickFilter(i, self.showCompareContextMenu, videoCompare)
                    videoCompare.installEventFilter(click_filter)
                    
                    sizePolicy = videoCompare.sizePolicy()
                    sizePolicy.setRetainSizeWhenHidden(True)
                    videoCompare.setSizePolicy(sizePolicy)
                    
                    videoCompare_container = AspectRatioWrapper(videoCompare, ratio=16.0/9.0)
                    videoCompare_container.setMinimumWidth(160)
                    
                    videoCompare_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                    videoCompare_container.setStyleSheet("background-color: black;")
                    
                    videoCompare_MP = QMediaPlayer()
                    videoCompare_AO = QAudioOutput()
                    videoCompare_MP.setAudioOutput(videoCompare_AO)
                    videoCompare_MP.setVideoOutput(videoCompare)
                    videoCompare_AO.setVolume(0)
                    videoCompare_MP.setSource(QUrl.fromLocalFile(self.currentlyComparingVideos[i]['file']))
                    videoCompare_MP.play()

                    videoCompareVLayout.addWidget(videoCompare_container)
                    videoCompareVLayout.addWidget(videoCompareName)

                    self.videoComparisonArea.addWidget(videoCompareWidget, r, c, 1, 1)
                    self.videoCompare_MPs.append(videoCompare_MP)

    def setupVideoPreviewUi(self):
        clear_layout(self.videoPreviewArea)
        
        # we add these lines to fix ghost stretches (e.g. when going from 2x1 to 1x1)
        for r in range(self.videoPreviewArea.rowCount()):
            self.videoPreviewArea.setRowStretch(r, 0)
        for c in range(self.videoPreviewArea.columnCount()):
            self.videoPreviewArea.setColumnStretch(c, 0)
        self.videoPreview_MPs = []
        
        n = len(self.video_markers)
        
        if n == 0:
            return
            
        rows, cols = find_closest_grid(n)

        marker_ids = list(self.video_markers.keys())

        for r in range(rows):
            self.videoPreviewArea.setRowStretch(r, 1)
        for c in range(cols):
            self.videoPreviewArea.setColumnStretch(c, 1)

        for r in range(rows): 
            for c in range(cols):
                i = r * cols + c
                if i < n:
                    marker_id = marker_ids[i]
                    
                    videoPreviewWidget = QWidget()
                    videoPreviewWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                    
                    videoPreviewVLayout = QVBoxLayout(videoPreviewWidget)

                    videoPreviewName = QLabel(self.video_markers[marker_id]['name'])
                    videoPreviewName.setMaximumHeight(20)

                    videoPreview = QVideoWidget(parent=self.centralwidget)
                    
                    click_filter = VideoRightClickFilter(i, self.showPreviewGridContextMenu, videoPreview)
                    videoPreview.installEventFilter(click_filter)
                    
                    sizePolicy = videoPreview.sizePolicy()
                    sizePolicy.setRetainSizeWhenHidden(True)
                    videoPreview.setSizePolicy(sizePolicy)
                    
                    videoPreview_container = AspectRatioWrapper(videoPreview, ratio=16.0/9.0)
                    videoPreview_container.setMinimumWidth(160)
                    videoPreview_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                    videoPreview_container.setStyleSheet("background-color: black;")
                    
                    videoPreview_MP = QMediaPlayer()
                    videoPreview_AO = QAudioOutput()
                    videoPreview_MP.setAudioOutput(videoPreview_AO)
                    videoPreview_MP.setVideoOutput(videoPreview)
                    videoPreview_AO.setVolume(0)
                    videoPreview_MP.setSource(QUrl.fromLocalFile(self.video_markers[marker_id]['file']))
                    videoPreview_MP.durationChanged.connect(self.setup_timelineSlider)
                    videoPreview_MP.play()

                    videoPreviewVLayout.addWidget(videoPreview_container)
                    videoPreviewVLayout.addWidget(videoPreviewName)

                    self.videoPreviewArea.addWidget(videoPreviewWidget, r, c, 1, 1)
                    self.videoPreview_MPs.append(videoPreview_MP)

    def init_map(self):
        m = folium.Map(location=[self.lat, self.lon], zoom_start=self.zoom)
        
        data = io.BytesIO()
        m.save(data, close_file=False)
        html = data.getvalue().decode()

        injection = """
        <script src="https://cdn.jsdelivr.net/npm/leaflet-semicircle@2.0.4/Semicircle.min.js"></script>
        <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
        <script>
            var backend;
            var mapData = {};

            var trackingMarkers = {};

            var isPaintModeActive = false;

            function setPaintMode(state) {
                isPaintModeActive = state;
            }

            function syncTrackingPoints(visiblePointsJson, currentTime, maxTime) {
                var mapObj = """ + m.get_name() + """;
                var points = JSON.parse(visiblePointsJson);
                var activeIds = new Set();

                points.forEach(function(p) {
                    activeIds.add(p.id);
                    
                    // Calculate opacity based on age relative to tracking marker timeframe
                    var fadeRatio = 0;
                    if (maxTime > 1) {
                        var age = currentTime - p.time;
                        fadeRatio = Math.max(0, Math.min(1, age / maxTime));
                    }
                    
                    var currentOpacity = 1.0 - (fadeRatio * 0.75);

                    if (!trackingMarkers[p.id]) {
                        // Create a small red circle for the tracking point
                        var tMarker = L.circleMarker([p.lat, p.lon], {
                            radius: 4,
                            color: 'red',
                            fillColor: '#f03',
                            fillOpacity: currentOpacity,
                            opacity: currentOpacity
                        }).addTo(mapObj);
                        trackingMarkers[p.id] = tMarker;
                    } else {
                        // Update the opacity dynamically if the marker already exists
                        trackingMarkers[p.id].setStyle({
                            fillOpacity: currentOpacity,
                            opacity: currentOpacity
                        });
                    }
                });

                // Clean up markers that are no longer visible
                for (var id in trackingMarkers) {
                    if (!activeIds.has(id)) {
                        mapObj.removeLayer(trackingMarkers[id]);
                        delete trackingMarkers[id];
                    }
                }
            }
            
            new QWebChannel(qt.webChannelTransport, function (channel) {
                backend = channel.objects.backend;
            });

            function addVideoMarker(lat, lng, markerId, r = 500, direction = 0, arc = 90, color = '#3388ff') {
                var mapObj = """ + m.get_name() + """;
                
                var marker = L.marker([lat, lng], {draggable: true}).addTo(mapObj);
                
                var semi = L.semiCircle([lat, lng], {
                    radius: r,
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.3,
                    startAngle: 0,
                    stopAngle: 360
                }).addTo(mapObj);
                semi.setDirection(direction, arc);
                
                mapData[markerId] = {marker: marker, semi: semi};

                // Sync Semicircle location with Marker during dragging
                marker.on('drag', function(e) {
                    semi.setLatLng(e.latlng);
                    if(backend) backend.js_marker_moved(markerId, e.latlng.lat, e.latlng.lng);
                });

                marker.on('click', function(e) {
                    if (isPaintModeActive) return;
                    L.DomEvent.stopPropagation(e);
                    if(backend) backend.js_marker_clicked(markerId);
                });
                
                semi.on('click', function(e) {
                    if (isPaintModeActive) return;
                    L.DomEvent.stopPropagation(e);
                    if(backend) backend.js_marker_clicked('semi_' + markerId);
                });
            }

            function removeVideoMarker(markerId) {
                var mapObj = """ + m.get_name() + """;
                
                if (mapData[markerId]) {
                        mapObj.removeLayer(mapData[markerId].marker);
                        mapObj.removeLayer(mapData[markerId].semi);
                        
                        delete mapData[markerId];
                }
            }

            // Function to update geometry from Python
            function updateSemiCircle(markerId, radius, dir, arc) {
                if(mapData[markerId]) {
                    var semi = mapData[markerId].semi;
                    semi.setRadius(radius);
                    semi.setDirection(dir, arc);
                }
            }

            function updateMarkerPosition(markerId, lat, lng) {
                if(mapData[markerId]) {
                    var newLatLng = new L.LatLng(lat, lng);
                    mapData[markerId].marker.setLatLng(newLatLng);
                    mapData[markerId].semi.setLatLng(newLatLng);
                }
            }

            // Function to return SemiCircleValues to Python
            function getSemiCircle(markerId, updateUI = false) {
                if(mapData[markerId]) {
                    var semi = mapData[markerId].semi;
                    var r = semi.getRadius()
                    var dir = (semi.options.startAngle + semi.options.stopAngle)/2
                    var arc = Math.abs(semi.options.stopAngle - semi.options.startAngle)
                    if(backend) backend.js_return_semicircle('semi_' + markerId, r, dir, arc, updateUI);
                }
            }

            function getAllMarkersData() {
                var currentData = {};
                for (var markerId in mapData) {
                    var marker = mapData[markerId].marker;
                    var semi = mapData[markerId].semi;
                    var latlng = marker.getLatLng();
                    
                    var r = semi.getRadius();
                    var dir = (semi.options.startAngle + semi.options.stopAngle) / 2;
                    var arc = Math.abs(semi.options.stopAngle - semi.options.startAngle);
                    
                    currentData[markerId] = {
                        lat: latlng.lat,
                        lon: latlng.lng,
                        radius: r,
                        direction: dir,
                        arc: arc
                    };
                }
                return JSON.stringify(currentData);
            }

            setTimeout(function() {
                var mapObj = """ + m.get_name() + """;
                mapObj.on('click', function(e) {
                    if(backend) backend.js_map_clicked(e.latlng.lat, e.latlng.lng);
                });
            }, 500);
        </script>
        """
        html = html.replace("</head>", injection + "</head>")
        self.map_view.setHtml(html)

    def setup_timelineSlider(self):
        self.firstCreated = sys.maxsize
        max_end_time = 0

        # Calculate the absolute timeline bounds
        for mp in self.videoPreview_MPs:
            file = mp.source().toString().replace("file:///", "")
            createdtime = get_file_birthtime(file)
            duration = mp.duration()
            
            if createdtime < self.firstCreated:
                self.firstCreated = createdtime
            
            end_time = createdtime + duration
            if end_time > max_end_time:
                max_end_time = end_time

        if self.firstCreated == sys.maxsize:
            self.firstCreated = 0
            
        raw_maxi = max_end_time - self.firstCreated if max_end_time > 0 else 0

        # Calculate scale factor (1 if under ~2 billion ms, scales up if larger)
        self.time_scale = max(1, int(raw_maxi // 2000000000) + 1)
        
        maxi = int(raw_maxi // self.time_scale)

        segments = []
        marker_ids = list(self.video_markers.keys())
        
        for i, mp in enumerate(self.videoPreview_MPs):
            marker_id = marker_ids[i]
            
            file = mp.source().toString().replace("file:///", "")
            createdtime = get_file_birthtime(file)
            start_offset = createdtime - self.firstCreated
            
            scaled_start = int(start_offset // self.time_scale)
            scaled_duration = int(mp.duration() // self.time_scale)
            
            name = self.video_markers[marker_id]['name']
            color = self.video_markers[marker_id].get('color', '#3388ff')
            raw_kfs = self.video_markers[marker_id].get('keyframes', [])
            scaled_kfs = [int(kf['time'] // self.time_scale) for kf in raw_kfs]
            
            segments.append((scaled_start, scaled_duration, name, color, scaled_kfs))

        self.timelineSlider.setMinimum(0)
        self.timelineSlider.setMaximum(maxi)
        
        # Scale the tick marks and steps so they remain proportionate
        self.timelineSlider.setTickPosition(QSlider.TicksBothSides)
        
        # Define a safe maximum number of visual ticks (e.g., 100)
        target_tick_count = 100 
        calculated_interval = maxi // target_tick_count
        
        self.timelineSlider.setTickInterval(max(1, calculated_interval))
        
        # The single and page steps can remain time-based, as they don't trigger draw calls
        self.timelineSlider.setSingleStep(max(1, 17 // self.time_scale))
        self.timelineSlider.setPageStep(max(1, 1000 // self.time_scale))
        
        # Pass the segments to the custom slider to draw the blocks
        self.timelineSlider.set_video_segments(segments)

    # @group Comparison Area Moving:
    def moveQuickPreviewToComparisonArea(self):
        if self.active_marker_id != None:
            if not any(d['id'] == self.active_marker_id for d in self.currentlyComparingVideos): # check if there is already an entry
                self.currentlyComparingVideos.append({
                    'file' : self.videoQuickPreview_MP.source().toString().replace("file:///", ""),
                    'name' : self.video_markers[self.active_marker_id]['name'], 
                    'id' : self.active_marker_id
                })
                self.setupVideoCompareUi()
                self.f_logger.log("COMP_ADD", {'file' : self.videoQuickPreview_MP.source().toString().replace("file:///", "")})

    def removeVideoFromComparison(self, index):
        """Removes the video track from the active array and redraws the comparison UI."""
        if 0 <= index < len(self.currentlyComparingVideos):
            if index < len(self.videoCompare_MPs):
                self.videoCompare_MPs[index].stop()
                
            self.f_logger.log("COMP_RM", {'file' : self.videoCompare_MPs[index].source().toString().replace("file:///", "")})
            self.currentlyComparingVideos.pop(index)
            self.setupVideoCompareUi()

    # @group Loading and Saving: 
    def save_canvas(self):
        # If a file is already loaded/saved, skip the dialog and save directly
        if self.current_file_path:
            self.map_view.page().runJavaScript("getAllMarkersData();", self._execute_save)
        else:
            # Otherwise, fall back to the Save As behavior
            self.save_as_canvas()

    def save_as_canvas(self):
        self.lastSaved = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Canvas",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        # If the user canceled, do nothing
        if not file_path:
            return
            
        self.current_file_path = file_path
        self.map_view.page().runJavaScript("getAllMarkersData();", self._execute_save)

    def _execute_save(self, js_result):
        if not js_result or not self.current_file_path:
            return

        dynamic_marker_data = json.loads(js_result)
        
        merged_markers = {}
        for marker_id, js_data in dynamic_marker_data.items():
            if marker_id in self.video_markers:
                merged_markers[marker_id] = {
                    'lat': js_data['lat'],
                    'lon': js_data['lon'],
                    'radius': js_data['radius'],
                    'direction': js_data['direction'],
                    'arc': js_data['arc'],
                    'file': self.video_markers[marker_id]['file'],
                    'name': self.video_markers[marker_id]['name'],
                    'keyframes': self.video_markers[marker_id].get('keyframes', []),
                    'color': self.video_markers[marker_id].get('color', '#3388ff')
                }

        data = {
            "markers": merged_markers,
            "compared_vids": self.currentlyComparingVideos,
            "tracking_points": getattr(self, 'tracking_points', []),
            "saveTime": self.lastSaved
        }
        
        try:
            with open(self.current_file_path, 'w') as file:
                json.dump(data, file, indent=4)
            self.statusbar.showMessage(f"Canvas saved successfully.", 3000)

            self.add_recent_file(self.current_file_path)

            self.f_logger.log("C_SAVE", {"file": self.current_file_path})
        except Exception as e:
            self.statusbar.showMessage(f"Failed to save file: {str(e)}", 5000)

        # Check if the user requested to exit during the save process
        if getattr(self, '_exit_after_save', False):
            sys.exit()

    def new_canvas(self):
        for marker_id in self.video_markers:
            js_code = f"removeVideoMarker('{marker_id}');"
            self.map_view.page().runJavaScript(js_code)

        self.video_markers = {}
        self.currentlyComparingVideos = []
        clear_layout(self.videoPreviewArea)
        clear_layout(self.videoComparisonArea)
        self.active_marker_id = None
        self.current_file_path = None
        self.tracking_points = []
        self.update_tracking_markers(0)
        self.lastSaved = -1
        self.f_logger.log("C_NEW")

    def load_canvas(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Canvas",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return

        self._load_file_from_path(file_path)

    def _load_file_from_path(self, file_path):
        """Helper method to load a canvas directly from a string path."""
        try:
            with open(file_path, "r") as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.statusbar.showMessage(f"Failed to read file: {str(e)}", 5000)
            # If the file is missing/corrupted, remove it from recent files
            self.remove_recent_file(file_path)
            return

        self.new_canvas()
        self.current_file_path = file_path
        
        # Add to recent files upon successful load
        self.add_recent_file(file_path)

        self.f_logger.log("C_LOAD", {"file": file_path})

        self.video_markers = data.get("markers", {})
        for marker_id, m_data in self.video_markers.items():
            lat = m_data['lat']
            lon = m_data['lon']
            radius = m_data.get('radius', 500)
            direction = m_data.get('direction', 0)
            arc = m_data.get('arc', 90)
            color = m_data.get('color', '#3388ff')
            
            js_code = f"addVideoMarker({lat}, {lon}, '{marker_id}', {radius}, {direction}, {arc}, '{color}');"
            file_hash = self.f_logger.get_file_hash(self.video_markers[marker_id]['file'])
            self.f_logger.log("V_ADD", {
                "name": self.video_markers[marker_id]['name'],
                "file": self.video_markers[marker_id]['file'],
                "sha256": file_hash
            })
            self.map_view.page().runJavaScript(js_code)

        self.currentlyComparingVideos = data.get("compared_vids", [])
        self.tracking_points = data.get("tracking_points", [])
        self.lastSaved = int(datetime.now(timezone.utc).timestamp() * 1000)

        self.setupVideoPreviewUi()
        self.setupVideoCompareUi()

        self.statusbar.showMessage("Canvas loaded successfully.", 3000)

    # @group Exit Program:
    def exit_program(self):

        diff = timedelta(milliseconds=int(datetime.now(timezone.utc).timestamp() * 1000) - self.lastSaved).total_seconds()

        if diff > self.timeDeltaBetweenSavesBeforeWarning / 1000:
            dig = QDialog(self)
            dig.setWindowTitle("Do you really want to quit?")
            QBtn = QDialogButtonBox.Yes | QDialogButtonBox.Cancel | QDialogButtonBox.Save
            dig.buttonBox = QDialogButtonBox(QBtn)

            save_btn = dig.buttonBox.button(QDialogButtonBox.Save)
            save_btn.setText("Save before exit")

            def handle_button(button):
                if button == save_btn:
                    self._exit_after_save = True # Set a flag to exit after the async JS completes
                    self.save_canvas()
                    dig.accept()
                elif button == dig.buttonBox.button(QDialogButtonBox.Yes):
                    self.f_logger.log("EXIT")
                    sys.exit()
                else:
                    dig.reject()

            dig.buttonBox.clicked.connect(handle_button)

            layout = QVBoxLayout()
            message = QLabel(f"You haven't saved for more than {int(diff)} seconds, proceed?")
            layout.addWidget(message)
            layout.addWidget(dig.buttonBox)
            dig.setLayout(layout)

            return dig.exec()
        else:
            self.f_logger.log("EXIT")
            sys.exit()

    def closeEvent(self, event):
        """Intercepts the default `closeEvent` of the MainWindow and uses `self.exit_program()` logic"""
        if self.exit_program() == 0:
            event.ignore()

    # @group Video Markers:
    def remove_specific_video_marker(self, index):
        """Removes a specific video marker based on its index in the preview grid."""
        if not self.video_markers or index >= len(self.video_markers):
            return

        # Safely map the grid index to the dictionary key
        marker_ids = list(self.video_markers.keys())
        target_marker_id = marker_ids[index]

        js_code = f"removeVideoMarker('{target_marker_id}');"
        self.map_view.page().runJavaScript(js_code)

        # Check if it's the active marker and clear the parameter preview UI if it is
        if self.active_marker_id == target_marker_id:
            self.parameterWidget.hide()
            self.videoQuickPreview_MP.stop()
            self.active_marker_id = None

        #Check if it's currently in the Top Comparison Area and remove it
        for idx, comp_vid in enumerate(self.currentlyComparingVideos):
            if comp_vid['id'] == target_marker_id:
                self.removeVideoFromComparison(idx)
                break 

        removed_vid_data = self.video_markers.pop(target_marker_id)

        self.f_logger.log("V_RM", {"file": removed_vid_data['file']})

        self.pause_all_videos() 
        self.setupVideoPreviewUi()
        self.setup_timelineSlider()

        self.statusbar.showMessage(f"Removed video marker: {removed_vid_data['name']}", 4000)

    def place_video_marker(self, js_result, file_path):
        if not js_result: return
        data = json.loads(js_result)
        lat, lng = data['lat'], data['lng']
        
        new_file_time = get_file_birthtime(file_path)
        one_week_in_ms = 7 * 24 * 60 * 60 * 1000
        
        for marker_id in self.video_markers:
            existing_file = self.video_markers[marker_id]['file']
            existing_file_time = get_file_birthtime(existing_file)
            
            if abs(new_file_time - existing_file_time) > one_week_in_ms:
                QMessageBox.warning(
                    self, 
                    "Time Gap Warning", 
                    "Warning: This video is more than 1 week apart from existing markers. This may cause timeline performance issues."
                )
                break

        if not self.video_markers:
            new_idx = 0
        else:
            indices = [int(k.split('_')[1]) for k in self.video_markers.keys() if k.startswith('vid_')]
            new_idx = max(indices) + 1 if indices else 0
            
        marker_id = f"vid_{new_idx}"

        self.video_markers[marker_id] = {}
        self.video_markers[marker_id]['file'] = file_path
        self.video_markers[marker_id]['name'] = f"({marker_id}) | " + QFileInfo(file_path).completeBaseName()
        self.video_markers[marker_id]['lat'] = lat
        self.video_markers[marker_id]['lon'] = lng
        self.video_markers[marker_id]['keyframes'] = []
        
        color = self.marker_colors[self.color_index % len(self.marker_colors)]
        self.color_index += 1
        self.video_markers[marker_id]['color'] = color

        file_hash = self.f_logger.get_file_hash(file_path)
        self.f_logger.log("V_ADD", {
            "name": self.video_markers[marker_id]['name'],
            "file": file_path,
            "sha256": file_hash
        })

        self.map_view.page().runJavaScript(f"addVideoMarker({lat}, {lng}, '{marker_id}', 500, 0, 90, '{color}');")
        self.play_video(file_path)
        self.setupVideoPreviewUi()

    def update_arc_label(self, value):
        self.arcLabel.setText(f"Arc: {value}°")

    def update_dir_label(self, value):
        self.dirLabel.setText(f"Dir: {(value + 180) % 360}°")

    def remove_last_video_marker(self):
        """Removes the most recently added video marker and all its associated UI/Map elements."""
        if not self.video_markers:
            self.statusbar.showMessage("No video markers to remove.", 3000)
            return

        last_marker_id = f"vid_{len(self.video_markers) - 1}"

        # Fallback just in case standard dictionary order is needed
        if last_marker_id not in self.video_markers:
            last_marker_id = list(self.video_markers.keys())[-1]

        js_code = f"removeVideoMarker('{last_marker_id}');"
        self.map_view.page().runJavaScript(js_code)

        if self.active_marker_id == last_marker_id:
            self.parameterWidget.hide()
            self.videoQuickPreview_MP.stop()
            self.active_marker_id = None

        for idx, comp_vid in enumerate(self.currentlyComparingVideos):
            if comp_vid['id'] == last_marker_id:
                self.removeVideoFromComparison(idx)
                break 

        removed_vid_data = self.video_markers.pop(last_marker_id)

        self.f_logger.log("V_RM", {"file": removed_vid_data['file']})

        self.setupVideoPreviewUi()
        
        self.pause_all_videos() 
        self.setup_timelineSlider()

        self.statusbar.showMessage(f"Removed video marker: {removed_vid_data['name']}", 4000)

    def handle_semicircle_return(self, marker_id, radius, direction, arc, updateUI = False):
        self.lastSemiParameters['marker_id'] = marker_id
        self.lastSemiParameters['r'] = radius
        self.lastSemiParameters['dir'] = direction
        self.lastSemiParameters['arc'] = arc

        if updateUI:
            self.paramRadiusInput.blockSignals(True)
            self.paramDirDial.blockSignals(True)
            self.paramArcSlider.blockSignals(True)

            self.paramRadiusInput.setText(str(radius))
            self.paramDirDial.setValue((direction + 180) % 360)
            self.paramArcSlider.setValue(arc)

            self.arcLabel.setText(f"Arc: {arc}°")
            self.dirLabel.setText(f"Dir: {direction}°")

            self.paramRadiusInput.blockSignals(False)
            self.paramDirDial.blockSignals(False)
            self.paramArcSlider.blockSignals(False)

    def apply_semi_parameters(self):
        if not self.active_marker_id:
            return
            
        try:
            r = float(self.paramRadiusInput.text())
            arc = self.paramArcSlider.value() % 360
            direction = int((self.paramDirDial.value() + 180) % 360)
            
            js_code = f"updateSemiCircle('{self.active_marker_id}', {r}, {direction}, {arc});"
            self.map_view.page().runJavaScript(js_code)
        except ValueError:
            print("Please enter valid numbers for the parameters.")

    # @group Event Handling:
    def handle_file_drop(self, file_path, x, y):
        js_code = """
        (function() {
            for (var key in window) {
                if (key.startsWith('map_')) {
                    var latlng = window[key].containerPointToLatLng([%f, %f]);
                    return JSON.stringify({lat: latlng.lat, lng: latlng.lng});
                }
            }
        })();
        """ % (x, y)
        
        self.map_view.page().runJavaScript(js_code, lambda res: self.place_video_marker(res, file_path))

    def handle_marker_click(self, marker_id):
        real_id = marker_id.replace("semi_", "")
        self.active_marker_id = real_id
        if real_id in self.video_markers and 'name' in self.video_markers[real_id]:
            self.paramNameLabel.setText(self.video_markers[real_id]['name'])
        else:
            self.paramNameLabel.setText("Kamera")

        self.map_view.page().runJavaScript(f"getSemiCircle('{self.active_marker_id}', true);")

        self.parameterWidget.show()

        if real_id in self.video_markers:
            self.play_video(self.video_markers[real_id]['file'])

    def handle_marker_moved(self, marker_id, lat, lng):
        """Updates the Python dictionary when a marker is dragged on the JS map."""
        if marker_id in self.video_markers:
            self.video_markers[marker_id]['lat'] = lat
            self.video_markers[marker_id]['lon'] = lng

    def handle_map_click(self, lat, lng):
        if getattr(self, 'paint_mode_active', False):
            global_pos = self.timelineSlider.value() * getattr(self, 'time_scale', 1)
            
            point_id = f"track_{len(self.tracking_points)}_{int(global_pos)}"
            self.tracking_points.append({
                'id': point_id,
                'lat': lat,
                'lon': lng,
                'time': global_pos
            })
            
            # Ensure list stays chronological
            self.tracking_points.sort(key=lambda x: x['time'])
            self.update_tracking_markers(global_pos)
            
            self.statusbar.showMessage(f"Added tracking point at {int(global_pos)}ms", 2000)
        else:
            self.parameterWidget.hide()
            self.videoQuickPreview_MP.stop()
            self.active_marker_id = None

    # @group Tracking Markers:
    def toggle_paint_mode(self, checked):
        self.paint_mode_active = checked
        if checked:
            self.paint_mode_button.setText("Paint Mode: ON")
            self.statusbar.showMessage("Enabled Paint Mode", 3000)
        else:
            self.paint_mode_button.setText("Paint Mode: OFF")
            self.statusbar.showMessage("Disabled Paint Mode", 3000)

        js_state = 'true' if checked else 'false'
        self.map_view.page().runJavaScript(f"setPaintMode({js_state});")

    def update_tracking_markers(self, global_pos):
        """Filters tracking points up to the current timestamp and syncs them with JS, passing dynamic time span for fading."""
        visible_points = [p for p in getattr(self, 'tracking_points', []) if p['time'] <= global_pos]
        
        if hasattr(self, 'tracking_points') and len(self.tracking_points) > 1:
            first_time = self.tracking_points[0]['time']
            last_time = self.tracking_points[-1]['time']
            max_time_span = last_time - first_time
            
            # Catch edge cases where points are placed on the exact same millisecond
            if max_time_span <= 0:
                max_time_span = 1
        else:
            # Fallback if there are fewer than 2 points placed
            max_time_span = 1 
            
        # Pass the global_pos (current time) and max_time_span to JS alongside the data
        js_code = f"syncTrackingPoints('{json.dumps(visible_points)}', {global_pos}, {max_time_span});"
        self.map_view.page().runJavaScript(js_code)

    def remove_last_tracking_point(self):
        """Removes the chronologically latest tracking point and updates the map."""
        if hasattr(self, 'tracking_points') and self.tracking_points:
            removed_point = self.tracking_points.pop()
            
            # Get the current timeline position to refresh the map accurately
            global_pos = self.timelineSlider.value() * getattr(self, 'time_scale', 1)
            
            # Sync the updated (shorter) list with the JavaScript map
            self.update_tracking_markers(global_pos)
            
            self.statusbar.showMessage(f"Removed tracking point at {int(removed_point['time'])}ms", 3000)
        else:
            self.statusbar.showMessage("No tracking points to remove.", 3000)

    # @group Playback:
    def toggle_playback(self):
        """Toggles between play and pause states based on the timer activity."""
        if self.playback_timer.isActive():
            self.pause_all_videos()
        else:
            self.play_all_videos()

    def pause_all_videos(self):
        self.playback_timer.stop()
        self.playPauseButton.setText("PLAY")

        preview_mps = getattr(self, 'videoPreview_MPs', [])
        compare_mps = getattr(self, 'videoCompare_MPs', [])

        for mp in chain(preview_mps, compare_mps):
            mp.pause()

    def play_all_videos(self):
        pos = self.timelineSlider.value() * getattr(self, 'time_scale', 1)
        
        self.playback_timer.start(33)
        self.playPauseButton.setText("PAUSE")

        preview_mps = getattr(self, 'videoPreview_MPs', [])
        compare_mps = getattr(self, 'videoCompare_MPs', [])

        for mp in chain(preview_mps, compare_mps):
            file = mp.source().toString().replace("file:///", "")
            createdtime = get_file_birthtime(file)
            start_offset = createdtime - self.firstCreated
            local_pos = pos - start_offset
            
            video_widget = mp.videoOutput()
            
            if 0 <= local_pos <= mp.duration():
                if video_widget:
                    video_widget.show()
                mp.setPosition(int(local_pos))
                mp.play()
            else:
                if video_widget:
                    video_widget.hide()
                mp.pause()

    def seek(self, pos):
        # Convert scaled slider position back to real milliseconds
        real_pos = pos * getattr(self, 'time_scale', 1)

        self.apply_all_keyframes(real_pos)
        self.update_tracking_markers(real_pos)

        preview_mps = getattr(self, 'videoPreview_MPs', [])
        compare_mps = getattr(self, 'videoCompare_MPs', [])

        # Stop everything and move to specific frames
        for mp in chain(preview_mps, compare_mps):
            file = mp.source().toString().replace("file:///", "")
            createdtime = get_file_birthtime(file)
            
            video_start_relative = createdtime - self.firstCreated
            local_pos = real_pos - video_start_relative
            
            mp.pause()
            
            # Set position boundaries so videos don't break when seeking past their ends
            if local_pos < 0:
                mp.setPosition(0)
            elif local_pos > mp.duration():
                mp.setPosition(mp.duration())
            else:
                mp.setPosition(int(local_pos))

    def play_video(self, file_path):
        self.videoQuickPreview_MP.setSource(QUrl.fromLocalFile(file_path))
        self.videoQuickPreview_MP.setPosition(0)
        self.videoQuickPreview_MP.play()

    # @group Context/Dialog Menus:
    def open_add_video_dialog(self):
        """Opens a file dialog, then a metadata/coordinate dialog, and adds the video to the map."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*)"
        )
        
        if not file_path:
            return

        # Pass the map's default center coordinates to the dialog
        dialog = AddVideoDialog(file_path, self.lat, self.lon, self)
        
        if dialog.exec() == QDialog.Accepted:
            lat, lon = dialog.get_coordinates()
            
            # Mock the JSON result format that place_video_marker expects
            js_result = json.dumps({'lat': lat, 'lng': lon})
            
            self.place_video_marker(js_result, file_path)
            self.statusbar.showMessage(f"Added video marker at ({lat}, {lon})", 4000)

    def show_about_dialog(self):
        """Displays the About dialog containing the required GPLv3 legal notices."""
        dialog = AboutDialog(self)
        dialog.exec()

    def showCompareContextMenu(self, global_pos, index):
        """Displays a context menu at the global cursor position."""
        context_menu = QMenu(self)
        remove_action = context_menu.addAction("Remove from comparison")
        
        selected_action = context_menu.exec(global_pos)
        
        if selected_action == remove_action:
            self.removeVideoFromComparison(index)

    def showPreviewContextMenu(self, global_pos, index=None):
        """Displays a context menu at the global cursor position for the quick preview."""
        # Only show the menu if a video is currently selected/active
        if self.active_marker_id is None:
            return

        context_menu = QMenu(self)
        add_action = context_menu.addAction("Add to comparison")
        
        selected_action = context_menu.exec(global_pos)
        
        if selected_action == add_action:
            self.moveQuickPreviewToComparisonArea()

    def showPreviewGridContextMenu(self, global_pos, index):
        """Displays a context menu for the bottom video preview grid."""
        context_menu = QMenu(self)
        remove_action = context_menu.addAction("Remove Video")
        
        selected_action = context_menu.exec(global_pos)
        
        if selected_action == remove_action:
            self.remove_specific_video_marker(index)

    # @group Keyframes & Interpolation:
    def add_keyframe(self):
        """Saves the current parameters at the timeline's current global position."""
        if not self.active_marker_id:
            return
            
        try:
            r = float(self.paramRadiusInput.text())
            arc = self.paramArcSlider.value() % 360
            direction = int((self.paramDirDial.value() + 180) % 360)
            
            # Get the real global time in milliseconds from the slider
            global_pos = self.timelineSlider.value() * getattr(self, 'time_scale', 1)
            
            file_path = self.video_markers[self.active_marker_id]['file']
            createdtime = get_file_birthtime(file_path)
            start_offset = createdtime - getattr(self, 'firstCreated', 0)
            
            local_time = global_pos - start_offset
            
            # Ensure we don't accidentally save a negative time if the timeline
            local_time = max(0, local_time)

            lat = self.video_markers[self.active_marker_id].get('lat', 0.0)
            lon = self.video_markers[self.active_marker_id].get('lon', 0.0)
            
            kf = {'time': local_time, 'r': r, 'dir': direction, 'arc': arc, 'lat': lat, 'lon': lon}
            
            kfs = self.video_markers[self.active_marker_id].setdefault('keyframes', [])
            # Overwrite if a keyframe exists at this exact millisecond, otherwise append
            kfs = [k for k in kfs if k['time'] != local_time]
            kfs.append(kf)
            
            # Keep keyframes chronological
            kfs.sort(key=lambda x: x['time'])
            self.video_markers[self.active_marker_id]['keyframes'] = kfs
            
            # Refresh the timeline to paint the new keyframe dot
            self.setup_timelineSlider()
            
            self.statusbar.showMessage(f"Keyframe added to {self.active_marker_id} at {int(local_time)}ms", 3000)
            
        except ValueError:
            self.statusbar.showMessage("Invalid parameters for keyframe.", 3000)

    def remove_last_keyframe(self):
        """Removes the last added parameter keyframe for the currently active video."""
        if not getattr(self, 'active_marker_id', None):
            self.statusbar.showMessage("No active video selected.", 3000)
            return
            
        kf_list = self.video_markers[self.active_marker_id].get('keyframes', [])
        
        if not kf_list:
            self.statusbar.showMessage("No keyframes to remove.", 3000)
            return

        removed_kf = kf_list.pop()
        
        # Ensure the list remains sorted chronologically
        kf_list.sort(key=lambda x: x['time'])
        
        # Re-draw the timeline to remove the visual tick mark
        self.setup_timelineSlider()
        
        global_pos = self.timelineSlider.value() * getattr(self, 'time_scale', 1)
        self.apply_all_keyframes(global_pos)
        
        self.statusbar.showMessage(f"Removed keyframe at {int(removed_kf['time'])}ms", 4000)

    def get_interpolated_params(self, marker_id, local_time):
        """Calculates interpolated parameters based on surrounding keyframes."""
        kfs = self.video_markers[marker_id].get('keyframes', [])
        if not kfs: return None
        
        # If before first or after last keyframe, clamp to nearest
        if local_time <= kfs[0]['time']: return kfs[0]
        if local_time >= kfs[-1]['time']: return kfs[-1]
        
        # Find surrounding keyframes
        for i in range(len(kfs) - 1):
            k1, k2 = kfs[i], kfs[i+1]
            if k1['time'] <= local_time <= k2['time']:
                t_diff = k2['time'] - k1['time']
                if t_diff == 0: return k1
                
                factor = (local_time - k1['time']) / t_diff
                
                # Linear interpolation for Radius and Arc
                r = k1['r'] + (k2['r'] - k1['r']) * factor
                arc = k1['arc'] + (k2['arc'] - k1['arc']) * factor
                
                current_lat = self.video_markers[marker_id].get('lat', 0.0)
                current_lon = self.video_markers[marker_id].get('lon', 0.0)

                lat1 = k1.get('lat', current_lat)
                lon1 = k1.get('lon', current_lon)
                lat2 = k2.get('lat', current_lat)
                lon2 = k2.get('lon', current_lon)
                
                lat = lat1 + (lat2 - lat1) * factor
                lon = lon1 + (lon2 - lon1) * factor

                # Shortest-path circular interpolation for Direction
                d1, d2 = k1['dir'], k2['dir']
                diff = (d2 - d1 + 180) % 360 - 180
                dir_interp = (d1 + diff * factor) % 360
                
                return {'r': r, 'dir': dir_interp, 'arc': arc, 'lat': lat, 'lon': lon}
        return None

    def apply_all_keyframes(self, global_pos):
        """Applies interpolated keyframe data to all markers at the current global timeline position."""
        for marker_id, m_data in self.video_markers.items():
            if not m_data.get('keyframes'):
                continue
                
            createdtime = get_file_birthtime(m_data['file'])
            local_pos = global_pos - (createdtime - getattr(self, 'firstCreated', 0))
            
            interp = self.get_interpolated_params(marker_id, local_pos)
            if interp:
                js_code = (
                    f"updateSemiCircle('{marker_id}', {interp['r']}, {interp['dir']}, {interp['arc']}); "
                    f"updateMarkerPosition('{marker_id}', {interp['lat']}, {interp['lon']});"
                )
                self.map_view.page().runJavaScript(js_code)
                
                # Save the interpolated position so new keyframes use the exact current location
                self.video_markers[marker_id]['lat'] = interp['lat']
                self.video_markers[marker_id]['lon'] = interp['lon']
                
                # If this is the active marker, dynamically update the UI parameter dials
                if marker_id == self.active_marker_id:
                    self.paramRadiusInput.blockSignals(True)
                    self.paramDirDial.blockSignals(True)
                    self.paramArcSlider.blockSignals(True)

                    self.paramRadiusInput.setText(f"{interp['r']:.1f}")
                    self.paramDirDial.setValue(int((interp['dir'] + 180) % 360))
                    self.paramArcSlider.setValue(int(interp['arc']))

                    self.arcLabel.setText(f"Arc: {int(interp['arc'])}°")
                    self.dirLabel.setText(f"Dir: {int(interp['dir'])}°")

                    self.paramRadiusInput.blockSignals(False)
                    self.paramDirDial.blockSignals(False)
                    self.paramArcSlider.blockSignals(False)

    def playback_tick(self):
        """Called by QTimer during playback to update slider and apply keyframes."""
        mp = None
        createdtime = 0
        
        # Find ANY actively playing video to base our global timeline position on
        preview_mps = getattr(self, 'videoPreview_MPs', [])
        compare_mps = getattr(self, 'videoCompare_MPs', [])

        for player in chain(preview_mps, compare_mps):
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                mp = player
                createdtime = get_file_birthtime(mp.source().toString().replace("file:///", ""))
                break  # We just need one active player to establish the global time
             
        if not mp: 
             # If no videos are playing (all have ended or paused), stop ticking forward
             return
             
        local_pos = mp.position()
        global_pos = local_pos + (createdtime - getattr(self, 'firstCreated', 0))
        
        # Advance the UI slider visually
        scaled_pos = int(global_pos // getattr(self, 'time_scale', 1))
        self.timelineSlider.blockSignals(True)
        self.timelineSlider.setValue(scaled_pos)
        self.timelineSlider.blockSignals(False)
        
        # Interpolate and apply
        self.apply_all_keyframes(global_pos)
        self.update_tracking_markers(global_pos)

    # @group Recent Files:
    def add_recent_file(self, file_path):
        """Adds a file to the recent files list in QSettings."""
        settings = QSettings("Hochschule Mittweida", "ConeTrace")
        recent_files = settings.value("recent_files", [])
        
        # Ensure it's a list (QSettings can sometimes return strings if there is only 1 item)
        if not isinstance(recent_files, list):
            recent_files = [recent_files] if recent_files else []
            
        # Remove it if it already exists to move it to the top
        if file_path in recent_files:
            recent_files.remove(file_path)
            
        recent_files.insert(0, file_path)
        
        # Keep only the 5 most recent files
        recent_files = recent_files[:5]
        
        settings.setValue("recent_files", recent_files)
        self.update_recent_files_menu()

    def remove_recent_file(self, file_path):
        """Removes a file from the recent list (e.g., if it was deleted)."""
        settings = QSettings("Hochschule Mittweida", "ConeTrace")
        recent_files = settings.value("recent_files", [])
        
        if not isinstance(recent_files, list):
            recent_files = [recent_files] if recent_files else []
            
        if file_path in recent_files:
            recent_files.remove(file_path)
            settings.setValue("recent_files", recent_files)
            self.update_recent_files_menu()

    def update_recent_files_menu(self):
        """Clears and repopulates the Recent Files QMenu."""
        self.recent_menu.clear()
        
        settings = QSettings("Hochschule Mittweida", "ConeTrace")
        recent_files = settings.value("recent_files", [])
        
        if not isinstance(recent_files, list):
            recent_files = [recent_files] if recent_files else []
            
        if not recent_files:
            empty_action = QAction("No Recent Files", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return

        for i, file_path in enumerate(recent_files):
            action = QAction(file_path, self)
            # Default argument `path=file_path` captures the variable properly in the loop closure
            action.triggered.connect(lambda checked=False, path=file_path: self._load_file_from_path(path))
            self.recent_menu.addAction(action)
            
        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self.clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def clear_recent_files(self):
        """Wipes the recent files history."""
        settings = QSettings("Hochschule Mittweida", "ConeTrace")
        settings.setValue("recent_files", [])
        self.update_recent_files_menu()

    # @group dark mode:
    def toggle_dark_mode(self, checked):
        """Toggles the global application stylesheet and map tiles between dark and light themes."""
        
        # ==========================================
        # SHARED STRUCTURAL PARAMETERS
        # ==========================================
        panel_radius         = "0px"
        btn_radius           = "3px"
        btn_padding          = "5px"
        input_padding        = "5px"
        slider_groove_height = "10px"
        slider_handle_width  = "10px"
        slider_handle_radius = "3px"

        if checked:
            # ==========================================
            # DARK THEME PALETTE
            # ==========================================
            dark_bg                    = "#1e1e1e"  # Main window & background
            dark_text                  = "#ffffff"  # Foreground text & handles
            dark_panel_bg              = "#2b2b2b"  # Elevated containers & inputs
            dark_border                = "#555555"  # Standard borders
            dark_btn_bg                = "#333333"  # Button rest state
            dark_btn_hover             = "#444444"  # Button hover state
            dark_btn_pressed           = "#555555"  # Button pressed state
            dark_slider_groove_border  = "#999999"  # Timeline track border
            dark_slider_handle_border  = "#5c5c5c"  # Timeline handle border
            dark_tick_color            = "#ffffff"  # Pure white for crisp contrast against dark_bg

            dark_stylesheet = f"""
                QMainWindow, QDialog {{ background-color: {dark_bg}; color: {dark_text}; }}
                QWidget {{ color: {dark_text}; }}
                QLabel {{ color: {dark_text}; }}
                
                #parameterContainer {{ 
                    background-color: {dark_panel_bg}; 
                    border: 1px solid {dark_border}; 
                    border-radius: {panel_radius}; 
                }}

                QPushButton {{ 
                    background-color: {dark_btn_bg}; 
                    color: {dark_text}; 
                    border: 1px solid {dark_border}; 
                    padding: {btn_padding}; 
                    border-radius: {btn_radius}; 
                }}
                QPushButton:hover {{ background-color: {dark_btn_hover}; }}
                QPushButton:pressed {{ background-color: {dark_btn_pressed}; }}
                
                QLineEdit {{ 
                    background-color: {dark_panel_bg}; 
                    color: {dark_text}; 
                    border: 1px solid {dark_border}; 
                    padding: {input_padding}; 
                }}
                
                QMenuBar {{ background-color: {dark_bg}; color: {dark_text}; }}
                QMenuBar::item:selected {{ background-color: {dark_btn_bg}; }}
                
                QMenu {{ background-color: {dark_panel_bg}; color: {dark_text}; border: 1px solid {dark_border}; }}
                QMenu::item:selected {{ background-color: {dark_btn_hover}; }}
                
                QStatusBar {{ background-color: {dark_bg}; color: {dark_text}; }}
                
                QSlider::groove:horizontal {{ 
                    border: 1px solid {dark_slider_groove_border}; 
                    height: {slider_groove_height}; 
                    background: {dark_bg}; 
                    margin: 2px 0; 
                }}
                QSlider::handle:horizontal {{ 
                    background: {dark_text}; 
                    border: 1px solid {dark_slider_handle_border}; 
                    width: {slider_handle_width}; 
                    margin: -2px 0; 
                    border-radius: {slider_handle_radius}; 
                }}
                QSlider::tick-mark:horizontal {{
                    background: {dark_tick_color};
                }}
            """
            self.setStyleSheet(dark_stylesheet)
            self.statusbar.showMessage("Dark Mode Enabled", 3000)

        else:
            # ==========================================
            # LIGHT THEME PALETTE
            # ==========================================
            light_bg           = "#ffffff"  # Main window & crisp canvas backgrounds
            light_text         = "#000000"  # Standard high-contrast text
            light_panel_bg     = "#f0f0f0"  # Softly dimmed panels, menu bars, buttons
            light_border       = "#cccccc"  # Subtle borders
            light_btn_hover    = "#e0e0e0"  # Interactive hover state
            light_btn_pressed  = "#d0d0d0"  # Selection & press states
            light_tick_color   = "#555555"  # Defined dark gray for clean light mode tracking

            light_stylesheet = f"""
                QMainWindow, QDialog {{ background-color: {light_bg}; color: {light_text}; }}
                QWidget {{ color: {light_text}; }}
                QLabel {{ color: {light_text}; }}
                
                #parameterContainer {{ 
                    background-color: {light_panel_bg}; 
                    border: 1px solid {light_border}; 
                    border-radius: {panel_radius}; 
                }}

                QPushButton {{ 
                    background-color: {light_panel_bg}; 
                    color: {light_text}; 
                    border: 1px solid {light_border}; 
                    padding: {btn_padding}; 
                    border-radius: {btn_radius}; 
                }}
                QPushButton:hover {{ background-color: {light_btn_hover}; }}
                QPushButton:pressed {{ background-color: {light_btn_pressed}; }}
                
                QLineEdit {{ 
                    background-color: {light_bg}; 
                    color: {light_text}; 
                    border: 1px solid {light_border}; 
                    padding: {input_padding}; 
                }}
                
                QMenuBar {{ background-color: {light_panel_bg}; color: {light_text}; }}
                QMenuBar::item:selected {{ background-color: {light_btn_pressed}; }}
                
                QMenu {{ background-color: {light_bg}; color: {light_text}; border: 1px solid {light_border}; }}
                QMenu::item:selected {{ background-color: {light_btn_hover}; }}
                
                QStatusBar {{ background-color: {light_bg}; color: {light_text}; }}
                
                QSlider::tick-mark:horizontal {{
                    background: {light_tick_color};
                }}
            """
            self.setStyleSheet(light_stylesheet)
            self.statusbar.showMessage("Light Mode Enabled", 3000)

        if hasattr(self, 'timelineSlider'):
            self.timelineSlider.is_dark = checked
            self.timelineSlider.update()
            
    # @group End of Main Window:

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())