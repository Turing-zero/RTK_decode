#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定位数据处理模块
负责定位数据的解析、存储和可视化
"""

import os
import time
import json
import logging
import threading
import queue
from typing import Optional, List, Dict
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from PIL import Image, ImageDraw, ImageTk # 导入PIL
try:
    import tkintermapview
except ImportError:
    tkintermapview = None

# 尝试导入项目中的类
try:
    from .rtk_positioning import NMEAParser, GPSPosition, FixQuality, PositionType
except ImportError:
    # 如果作为脚本直接运行
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from rtk_positioning import NMEAParser, GPSPosition, FixQuality, PositionType

logger = logging.getLogger(__name__)

class PositionVisualizer:
    """定位结果可视化组件"""
    
    def __init__(self, title="RTK Positioning Visualization"):
        self.root = None
        self.map_widget = None
        self.canvas = None
        self.status_label = None
        self.title = title
        self.is_running = False
        self.points = [] # list of (lat, lon, color)
        self.path_points = [] # list of (lat, lon) for drawing path

        # 回放控制相关
        self.player_controls = None
        self.progress_var = None
        self.time_label_var = None
        self.is_dragging = False
        self.on_seek_callback = None
        self.on_play_pause_callback = None

        # 标记列表
        self.markers = [] # list of (marker_obj, type_str)
        self.base_marker = None
        self.base_pos_data = None # (lat, lon)

        # 过滤选项
        self.show_gps = None
        self.show_float = None
        self.show_fixed = None
        self.show_base = None

        # 地图范围 (自适应 - 仅用于Canvas模式)
        self.min_lat = 90.0
        self.max_lat = -90.0
        self.min_lon = 180.0
        self.max_lon = -180.0

        # 窗口大小
        self.width = 1000
        self.height = 800

        # 性能优化：最大显示点数
        self.max_points = 3000 # 限制显示最近的3000个点，防止卡顿

        self.first_fix = True # 是否是第一次定位，用于自动中心化

        # 性能优化：数据队列
        self.data_queue = queue.Queue()
        self.update_interval_ms = 100 # GUI刷新间隔 (ms)
        
        # 图标缓存
        self.icons = {}

        # 启动GUI线程
        self.gui_thread = threading.Thread(target=self._run_gui, daemon=True)
        self.gui_thread.start()
        
    def _create_circle_icon(self, color, size=10):
        """创建圆形图标"""
        key = f"{color}_{size}"
        if key in self.icons:
            return self.icons[key]
            
        try:
            image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((0, 0, size-1, size-1), fill=color, outline="white", width=1)
            icon = ImageTk.PhotoImage(image)
            self.icons[key] = icon
            return icon
        except Exception as e:
            logger.error(f"Failed to create icon: {e}")
            return None

    def _run_gui(self):
        """运行GUI循环"""
        try:
            self.root = tk.Tk()
        except Exception as e:
            logger.warning(f"无法启动GUI (可能是无头环境): {e}")
            self.is_running = False
            return

        self.root.title(self.title)
        self.root.geometry(f"{self.width}x{self.height}")

        # 初始化变量
        self.show_gps = tk.BooleanVar(value=True)
        self.show_float = tk.BooleanVar(value=True)
        self.show_fixed = tk.BooleanVar(value=True)
        self.show_base = tk.BooleanVar(value=True)

        # 控制面板
        control_frame = ttk.Frame(self.root)
        control_frame.pack(side=tk.TOP, fill=tk.X)

        ttk.Checkbutton(control_frame, text="GPS 定位 (红)", variable=self.show_gps, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="RTK 浮点解 (黄)", variable=self.show_float, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="RTK 固定解 (绿)", variable=self.show_fixed, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="基站 (蓝)", variable=self.show_base, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)

        # 功能按钮
        ttk.Button(control_frame, text="缩放至最新", command=self._zoom_to_last).pack(side=tk.LEFT, padx=10)

        # 地图源选择
        if tkintermapview:
            self.map_source_var = tk.StringVar(value="Google Standard")
            map_sources = ["Google Satellite", "Google Standard", "Google Hybrid", "OpenStreetMap", "OpenTopoMap"]
            source_menu = ttk.OptionMenu(control_frame, self.map_source_var, map_sources[0], *map_sources, command=self._change_map_source)
            source_menu.pack(side=tk.LEFT, padx=10)

        # 绑定ESC退出
        self.root.bind("<Escape>", lambda e: self.close())

        # 状态栏 (最底部)
        self.status_label = ttk.Label(self.root, text="Waiting for position data...", relief=tk.SUNKEN)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        # 回放控制面板 (状态栏上方)
        self.player_frame = ttk.Frame(self.root)
        self.player_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=0)

        if tkintermapview:
            # 使用 TkinterMapView
            # 设置离线地图数据库路径
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(root_dir, "offline_tiles.db")

            self.map_widget = tkintermapview.TkinterMapView(self.root, width=self.width, height=self.height, corner_radius=0, database_path=db_path)
            self.map_widget.pack(fill="both", expand=True)

            # 检查离线地图是否加载
            offline_status = "Offline Map: Disabled"
            if os.path.exists(db_path):
                offline_status = "Offline Map: Active"
            self.root.title(f"{self.title} - {offline_status}")

            # 设置默认位置 (北京)
            self.map_widget.set_position(39.9042, 116.4074)
            self.map_widget.set_zoom(15)

            # 设置瓦片服务器 (可选: 使用 Google Maps 或 OpenStreetMap)
            # self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
            # self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")

        else:
            # 回退到 Canvas
            logger.warning("tkintermapview not found, falling back to simple canvas.")
            self.canvas = tk.Canvas(self.root, bg="white", width=self.width, height=self.height)
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.canvas.bind("<Configure>", self._on_resize)

        self.is_running = True

        # 启动队列处理循环
        self.root.after(self.update_interval_ms, self._process_queue_loop)

        self.root.mainloop()
        self.is_running = False

    def _process_queue_loop(self):
        """批量处理数据队列"""
        if not self.is_running:
            return

        try:
            # 一次性取出所有积压的数据
            batch_data = []
            while not self.data_queue.empty():
                try:
                    item = self.data_queue.get_nowait()
                    batch_data.append(item)
                except queue.Empty:
                    break

            if batch_data:
                self._update_gui_batch(batch_data)

        except Exception as e:
            logger.error(f"Queue process error: {e}")
        finally:
            # 调度下一次检查
            if self.root:
                self.root.after(self.update_interval_ms, self._process_queue_loop)

    def enable_playback_controls(self, on_seek, on_play_pause):
        """启用回放控制面板 (线程安全)"""
        if not self.root:
            return False

        self.on_seek_callback = on_seek
        self.on_play_pause_callback = on_play_pause

        # 在GUI线程中执行UI创建
        self.root.after(0, self._create_playback_ui)
        return True

    def _create_playback_ui(self):
        """创建回放UI组件"""
        # 清除旧组件（如果有）
        for widget in self.player_frame.winfo_children():
            widget.destroy()

        # 播放/暂停按钮
        self.play_btn = ttk.Button(self.player_frame, text="Pause", command=self._toggle_play)
        self.play_btn.pack(side=tk.LEFT)

        # 进度条
        self.progress_var = tk.DoubleVar(value=0.0)
        self.scale = ttk.Scale(self.player_frame, from_=0.0, to=1.0, variable=self.progress_var, orient=tk.HORIZONTAL, command=self._on_scale_move)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 绑定鼠标释放事件 (用于seek)
        self.scale.bind("<ButtonRelease-1>", self._on_scale_release)
        self.scale.bind("<ButtonPress-1>", self._on_scale_press)

        # FPS显示
        self.fps_var = tk.StringVar(value="FPS: --")
        ttk.Label(self.player_frame, textvariable=self.fps_var, width=10).pack(side=tk.RIGHT, padx=5)

        # 时间显示
        self.time_label_var = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(self.player_frame, textvariable=self.time_label_var).pack(side=tk.RIGHT)

    def update_playback_status(self, progress, current_time_str, total_time_str, is_playing, fps=None):
        """更新回放状态"""
        if not self.root or self.is_dragging:
            return

        self.root.after(0, lambda: self._update_playback_ui(progress, current_time_str, total_time_str, is_playing, fps))

    def _update_playback_ui(self, progress, current_time_str, total_time_str, is_playing, fps):
        if self.progress_var:
            self.progress_var.set(progress)
        if self.time_label_var:
            self.time_label_var.set(f"{current_time_str} / {total_time_str}")
        if fps is not None and hasattr(self, 'fps_var'):
            self.fps_var.set(f"FPS: {fps:.1f}")
        if hasattr(self, 'play_btn'):
            self.play_btn.config(text="暂停" if is_playing else "播放")

    def _toggle_play(self):
        if self.on_play_pause_callback:
            self.on_play_pause_callback()
            
    def _on_scale_press(self, event):
        self.is_dragging = True

    def _on_scale_move(self, value):
        pass # 拖动中不实时更新，以免卡顿，释放时更新

    def _on_scale_release(self, event):
        self.is_dragging = False
        if self.on_seek_callback:
            self.on_seek_callback(self.progress_var.get())

    def _on_space_key(self, event):
        """空格键切换播放/暂停"""
        self._toggle_play()

    def _on_right_key(self, event):
        """右方向键快进"""
        if not self.progress_var or not self.on_seek_callback:
            return
        current = self.progress_var.get()
        new_val = min(1.0, current + 0.05) # +5%
        self.progress_var.set(new_val)
        self.on_seek_callback(new_val)

    def _on_left_key(self, event):
        """左方向键快退"""
        if not self.progress_var or not self.on_seek_callback:
            return
        current = self.progress_var.get()
        new_val = max(0.0, current - 0.05) # -5%
        self.progress_var.set(new_val)
        self.on_seek_callback(new_val)

    def _change_map_source(self, selection):
        """切换地图源"""
        if not self.map_widget:
            return

        if selection == "Google Standard":
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        elif selection == "Google Satellite":
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        elif selection == "Google Hybrid":
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        elif selection == "OpenStreetMap":
            self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        elif selection == "OpenTopoMap":
            self.map_widget.set_tile_server("https://a.tile.opentopomap.org/{z}/{x}/{y}.png")

    def _on_resize(self, event):
        """窗口大小改变 (仅Canvas模式)"""
        if self.canvas:
            self.width = event.width
            self.height = event.height
            self._redraw_canvas()

    def _zoom_to_last(self):
        """缩放到最后一个点"""
        if not self.map_widget:
            return
            
        target = None
        
        # 如果是MapView模式，位置数据在path_points中
        if self.path_points:
            target = self.path_points[-1]
        # 如果是Canvas模式，位置数据在points中
        elif self.points:
            lat, lon, _ = self.points[-1]
            target = (lat, lon)
        # 最后使用基站位置
        elif self.base_pos_data:
            target = self.base_pos_data
            
        if target:
            self.map_widget.set_position(target[0], target[1])
            self.map_widget.set_zoom(19) # 缩放到较高等级

    def _refresh_visibility(self):
        """刷新标记可见性"""
        if not self.map_widget:
            return
            
        # 清除所有标记
        self.map_widget.delete_all_marker()
        self.markers.clear()
        self.base_marker = None
        
        # 重绘解算点
        for lat, lon, color in self.points:
            visible = False
            if color == "red" and self.show_gps.get(): visible = True
            elif color == "green" and self.show_fixed.get(): visible = True
            elif color == "yellow" and self.show_float.get(): visible = True
            elif color == "gray": visible = True
            
            if visible:
                m_color = color
                if color == "red": m_color = "#FF0000"
                elif color == "green": m_color = "#00FF00"
                elif color == "yellow": m_color = "#FFFF00"
                
                # 创建标记
                icon = self._create_circle_icon(m_color, size=10)
                if icon:
                    m = self.map_widget.set_marker(lat, lon, icon=icon, text="") # 使用图标，不带文字
                else:
                    m = self.map_widget.set_marker(lat, lon, marker_color_circle=m_color, marker_color_outside=m_color, text="")
                
                # 不显示文字以防拥挤，或者只显示特定状态
                self.markers.append(m)
                
        # 重绘基站
        if self.base_pos_data and self.show_base.get():
            lat, lon = self.base_pos_data
            self._draw_base_station(lat, lon, force=True)
            
    def update_base_position(self, lat, lon):
        """更新基站位置"""
        if not self.is_running:
            return
        try:
            self.root.after(0, lambda: self._draw_base_station(lat, lon))
        except:
            pass

    def _draw_base_station(self, lat, lon, force=False):
        """绘制基站"""
        self.base_pos_data = (lat, lon)
        if not self.show_base.get() and not force:
            return
            
        if self.map_widget:
            if self.base_marker:
                self.base_marker.delete()
            # 基站显示为蓝色
            icon = self._create_circle_icon("blue", size=12) # 基站稍微大一点
            if icon:
                self.base_marker = self.map_widget.set_marker(lat, lon, text="BASE", icon=icon)
            else:
                self.base_marker = self.map_widget.set_marker(lat, lon, text="BASE", marker_color_circle="blue", marker_color_outside="blue")
            
            # 如果是第一次定位，自动居中
            if self.first_fix:
                self.map_widget.set_position(lat, lon)
                self.first_fix = False

    def update_position(self, position: GPSPosition):
        """更新位置并在地图上显示"""
        if not self.is_running or not self.root:
            return
            
        # 确定颜色
        # 红点: GPS_FIX (1), DGPS_FIX (2), PPS_FIX (3)
        # 绿点: RTK_FIXED (4)
        # 黄点: RTK_FLOAT (5)
        color = "gray"
        marker_color = "gray"
        
        # Debug logging
        # logger.info(f"Position Quality: {position.fix_quality} ({type(position.fix_quality)}), Expected: {FixQuality.GPS_FIX} ({type(FixQuality.GPS_FIX)})")
        
        # 使用 .name 或 .value 进行比较，避免类不一致问题
        quality_val = position.fix_quality.value if hasattr(position.fix_quality, 'value') else position.fix_quality
        
        if quality_val in [1, 2, 3]: # GPS_FIX, DGPS_FIX, PPS_FIX
            color = "red"
            marker_color = "#FF0000"
        elif quality_val == 4: # RTK_FIXED
            color = "green"
            marker_color = "#00FF00"
        elif quality_val == 5: # RTK_FLOAT
            color = "yellow"
            marker_color = "#FFFF00"
            
        lat = position.latitude
        lon = position.longitude
        
        # 放入队列进行批量处理，而不是直接调度
        self.data_queue.put({
            'type': 'pos',
            'lat': lat,
            'lon': lon,
            'color': color,
            'marker_color': marker_color,
            'position': position
        })

    def _update_gui_batch(self, batch_data):
        """批量更新GUI"""
        if not batch_data:
            return

        # 1. 批量更新数据结构
        new_path_points = []
        new_markers_data = []
        last_pos_data = None
        
        for item in batch_data:
            if item['type'] == 'pos':
                lat, lon = item['lat'], item['lon']
                color = item['color']
                marker_color = item['marker_color']
                
                # 保存到总列表 (移除窗口限制，保留所有历史数据)
                self.points.append((lat, lon, color))
                # 为了性能，如果点数过多(如>10000)，Canvas模式可能会卡顿，但用户要求不清除数据
                # if len(self.points) > self.max_points:
                #     self.points.pop(0)
                
                # 准备路径数据
                if self.map_widget:
                    self.path_points.append((lat, lon))
                    # 路径也不进行限制，确保轨迹完整
                    # if len(self.path_points) > self.max_points:
                    #     self.path_points.pop(0)
                
                # 收集需要绘制的标记
                new_markers_data.append(item)
                last_pos_data = item
                
            elif item['type'] == 'base':
                # 基站位置更新 (直接处理)
                self.base_pos_data = (item['lat'], item['lon'])
                if self.show_base.get():
                    self._draw_base_station(item['lat'], item['lon'], force=True)

        # 2. 更新 GUI 组件
        
        # 更新状态栏 (使用最后一条数据)
        if last_pos_data and self.status_label:
            pos = last_pos_data['position']
            status_text = f"Lat: {pos.latitude:.8f}, Lon: {pos.longitude:.8f}, Alt: {pos.altitude:.2f}m, Quality: {pos.fix_quality.name} ({pos.satellites_used} sats)"
            self.status_label.config(text=status_text)
            
        if self.map_widget:
            # A. 批量更新路径 (只调用一次 set_path)
            if len(self.path_points) > 1:
                self.map_widget.set_path(self.path_points, color="blue", width=2)
            
            # B. 批量添加标记
            for item in new_markers_data:
                color = item['color']
                marker_color = item['marker_color']
                lat, lon = item['lat'], item['lon']
                
                # 检查可见性
                visible = False
                if color == "red" and self.show_gps.get(): visible = True
                elif color == "green" and self.show_fixed.get(): visible = True
                elif color == "yellow" and self.show_float.get(): visible = True
                elif color == "gray": visible = True
                
                if visible:
                    icon = self._create_circle_icon(marker_color, size=10)
                    if icon:
                        marker = self.map_widget.set_marker(lat, lon, icon=icon, text="")
                    else:
                        marker = self.map_widget.set_marker(lat, lon, text="")
                        if hasattr(marker, "marker_color_circle"):
                            marker.marker_color_circle = marker_color
                            marker.marker_color_outside = marker_color
                            marker.draw()
                    self.markers.append(marker)
            
            # C. 批量清理旧标记
            while len(self.markers) > self.max_points:
                old_marker = self.markers.pop(0)
                old_marker.delete()
                
            # D. 自动居中 (如果是第一次)
            if self.first_fix and last_pos_data:
                self.map_widget.set_position(last_pos_data['lat'], last_pos_data['lon'])
                self.first_fix = False
                
        elif self.canvas:
            # Canvas 模式重绘
            # 由于 Canvas 绘制很快，可以直接重绘或增量绘制
            # 这里简单起见，如果数据量不大，直接重绘；如果很大，增量绘制
            # 为了保持一致性，使用 _redraw_canvas (重绘整个窗口)
            # 或者只绘制新点
            
            # 更新范围
            changed = False
            for item in new_markers_data:
                lat, lon = item['lat'], item['lon']
                if lat < self.min_lat: self.min_lat = lat; changed = True
                if lat > self.max_lat: self.max_lat = lat; changed = True
                if lon < self.min_lon: self.min_lon = lon; changed = True
                if lon > self.max_lon: self.max_lon = lon; changed = True
                
            if changed:
                self._redraw_canvas()
            else:
                for item in new_markers_data:
                    self._draw_canvas_point(item['lat'], item['lon'], item['color'])


    def _coord_to_pixel(self, lat, lon):
        """坐标转像素 (Canvas模式)"""
        lat_range = self.max_lat - self.min_lat
        lon_range = self.max_lon - self.min_lon
        
        if lat_range == 0: lat_range = 0.0001
        if lon_range == 0: lon_range = 0.0001
        
        # 增加边距
        lat_range *= 1.2
        lon_range *= 1.2
        
        mid_lat = (self.max_lat + self.min_lat) / 2
        mid_lon = (self.max_lon + self.min_lon) / 2
        
        x = (lon - (mid_lon - lon_range/2)) / lon_range * self.width
        y = self.height - ((lat - (mid_lat - lat_range/2)) / lat_range * self.height)
        
        return x, y

    def _redraw_canvas(self):
        """重绘Canvas"""
        if not self.canvas: return
        self.canvas.delete("all")
        for lat, lon, color in self.points:
            x, y = self._coord_to_pixel(lat, lon)
            self.canvas.create_oval(x-2, y-2, x+2, y+2, fill=color, outline=color)

    def _draw_canvas_point(self, lat, lon, color):
        """绘制单个Canvas点"""
        if not self.canvas: return
        x, y = self._coord_to_pixel(lat, lon)
        self.canvas.create_oval(x-2, y-2, x+2, y+2, fill=color, outline=color)

    def close(self):
        """关闭窗口"""
        if self.root:
            self.root.quit()



class PositionHandler:
    """
    定位数据处理器
    
    功能：
    1. 解析不同格式的定位数据 (目前支持GGA)
    2. 存储有效数据到日志文件
    3. 可视化显示定位结果
    """
    
    def __init__(self, log_file="rtk.log", enable_gui=True, enabled_messages: Optional[List[str]] = None):
        self.log_file = log_file
        
        # 改为 JSON Lines 格式，不再需要 separate sys log file
        # base, ext = os.path.splitext(self.log_file)
        # self.sys_log_file = f"{base}_sys{ext}"
        
        self.parser = NMEAParser(enabled_messages=enabled_messages)
        self.visualizer = PositionVisualizer() if enable_gui else None
        
        # JSON Lines 格式不需要文本头，追加模式即可
                
    def handle_position(self, position: GPSPosition):
        """处理解析后的位置信息"""
        
        # 处理基站数据
        if position.type == PositionType.BASE:
            self.update_base_position(position.latitude, position.longitude)
            # 基站数据也可以记录到日志，或者单独记录
            return

        # 过滤无效数据 (Invalid = 0)
        # 注意: SYSRTS消息即使fix_quality无效，也可能包含有用的系统状态信息
        # 但如果是纯位置消息且无效，则跳过
        has_sys_info = position.extra_info and position.extra_info.get('msg_type') == 'SYSRTS'
        
        if position.fix_quality == FixQuality.INVALID and not has_sys_info:
            return
            
        # 1. 存储到日志 (存储 GPSPosition 对象为 JSON)
        self._save_to_log(position)
        
        # 2. 可视化更新
        if self.visualizer and position.fix_quality != FixQuality.INVALID:
            self.visualizer.update_position(position)
            
    def _save_to_log(self, position: GPSPosition):
        """保存到日志文件 (JSON Lines)"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json_str = json.dumps(position.to_dict(), ensure_ascii=False)
                f.write(json_str + '\n')
        except Exception as e:
            logger.error(f"Write log failed: {e}")

    def update_base_position(self, lat, lon):
        """更新基站位置"""
        if self.visualizer:
            self.visualizer.update_base_position(lat, lon)

    def close(self):
        """清理资源"""
        if self.visualizer:
            self.visualizer.close()

if __name__ == "__main__":
    # 测试代码
    print("Testing PositionHandler...")
    handler = PositionHandler(enable_gui=True)
    
    # 模拟数据
    test_data = [
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47", # GPS Fix (Red)
        "$GPGGA,123520,4807.040,N,01131.002,E,4,10,0.8,545.5,M,46.9,M,,*47", # RTK Fixed (Green) (Checksum invalid here but parser handles it if mocked or calc'd)
        "$GPGGA,123521,4807.042,N,01131.004,E,5,12,0.8,545.6,M,46.9,M,,*47", # RTK Float (Yellow)
        "$GPGGA,123522,4807.035,N,01131.010,E,0,00,0.0,0.0,M,0.0,M,,*47"     # Invalid (Ignored)
    ]
    
    # 为了测试，我们需要手动计算校验和或让Parser宽容，或者使用正确的示例
    # 这里我们直接构造 GPSPosition 对象来测试 Visualizer，或者确保字符串正确
    # 为了简单演示，我们循环发送模拟数据
    
    try:
        print("Simulating data stream (Ctrl+C to stop)...")
        import time
        import random
        
        base_lat = 39.90
        base_lon = 116.40
        
        while True:
            # 生成随机偏移
            lat = base_lat + random.uniform(-0.001, 0.001)
            lon = base_lon + random.uniform(-0.001, 0.001)
            quality = random.choice([1, 4, 5, 0])

            pos = GPSPosition(
                latitude=lat,
                longitude=lon,
                altitude=100.0,
                fix_quality=FixQuality(quality),
                satellites_used=10,
                timestamp=datetime.now()
            )
            
            handler.handle_position(pos)
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        handler.close()
