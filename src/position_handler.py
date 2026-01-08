#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定位数据处理模块
负责定位数据的解析、存储和可视化
"""

import os
import time
import logging
import threading
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
        
        self.first_fix = True # 是否是第一次定位，用于自动中心化
        
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
        
        ttk.Checkbutton(control_frame, text="GPS Fix (Red)", variable=self.show_gps, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="RTK Float (Yellow)", variable=self.show_float, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="RTK Fixed (Green)", variable=self.show_fixed, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="Base Station (Blue)", variable=self.show_base, command=self._refresh_visibility).pack(side=tk.LEFT, padx=5)
        
        # 功能按钮
        ttk.Button(control_frame, text="Zoom Last", command=self._zoom_to_last).pack(side=tk.LEFT, padx=10)
        
        # 绑定ESC退出
        self.root.bind("<Escape>", lambda e: self.close())
        
        # 状态栏
        self.status_label = ttk.Label(self.root, text="Waiting for position data...", relief=tk.SUNKEN)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        
        if tkintermapview:
            # 使用 TkinterMapView
            self.map_widget = tkintermapview.TkinterMapView(self.root, width=self.width, height=self.height, corner_radius=0)
            self.map_widget.pack(fill="both", expand=True)
            
            # 设置默认位置 (北京)
            self.map_widget.set_position(39.9042, 116.4074)
            self.map_widget.set_zoom(15)
            
            # 设置瓦片服务器 (可选: 使用 Google Maps 或 OpenStreetMap)
            # self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
            self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
            
        else:
            # 回退到 Canvas
            logger.warning("tkintermapview not found, falling back to simple canvas.")
            self.canvas = tk.Canvas(self.root, bg="white", width=self.width, height=self.height)
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.canvas.bind("<Configure>", self._on_resize)
        
        self.is_running = True
        self.root.mainloop()
        self.is_running = False

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
        # 红点: GPS_FIX (1)
        # 绿点: RTK_FIXED (4)
        # 黄点: RTK_FLOAT (5)
        color = "gray"
        marker_color = "gray"
        
        if position.fix_quality == FixQuality.GPS_FIX:
            color = "red"
            marker_color = "#FF0000"
        elif position.fix_quality == FixQuality.RTK_FIXED:
            color = "green"
            marker_color = "#00FF00"
        elif position.fix_quality == FixQuality.RTK_FLOAT:
            color = "yellow"
            marker_color = "#FFFF00"
            
        lat = position.latitude
        lon = position.longitude
        
        # 在主线程中调度绘图
        try:
            self.root.after(0, lambda: self._update_gui(lat, lon, color, marker_color, position))
        except Exception as e:
            logger.error(f"GUI update error: {e}")

    def _update_gui(self, lat, lon, color, marker_color, position):
        """在主线程执行GUI更新"""
        # 更新状态栏
        status_text = f"Lat: {lat:.8f}, Lon: {lon:.8f}, Alt: {position.altitude:.2f}m, Quality: {position.fix_quality.name} ({position.satellites_used} sats)"
        if self.status_label:
            self.status_label.config(text=status_text)
            
        if self.map_widget:
            # MapView 模式
            # 添加路径点
            self.path_points.append((lat, lon))
            if len(self.path_points) > 1:
                self.map_widget.set_path(self.path_points, color="blue", width=2)
            
            # 移动地图中心 (可选：如果偏离太远)
            # self.map_widget.set_position(lat, lon) 
            
            # 首次定位自动居中
            if self.first_fix:
                self.map_widget.set_position(lat, lon)
                self.first_fix = False
            
            # 检查可见性
            visible = False
            if color == "red" and self.show_gps.get(): visible = True
            elif color == "green" and self.show_fixed.get(): visible = True
            elif color == "yellow" and self.show_float.get(): visible = True
            elif color == "gray": visible = True
            
            if visible:
                # 添加标记
                icon = self._create_circle_icon(marker_color, size=10)
                if icon:
                    marker = self.map_widget.set_marker(lat, lon, icon=icon, text="") # 不显示文字
                else:
                    marker = self.map_widget.set_marker(lat, lon, text="")
                    # 设置颜色
                    if hasattr(marker, "marker_color_circle"):
                        marker.marker_color_circle = marker_color
                        marker.marker_color_outside = marker_color
                        marker.draw() # 触发重绘
                        
                self.markers.append(marker)
                
        elif self.canvas:
            # Canvas 模式
            self.points.append((lat, lon, color))
            
            # 更新范围
            changed = False
            if lat < self.min_lat: self.min_lat = lat; changed = True
            if lat > self.max_lat: self.max_lat = lat; changed = True
            if lon < self.min_lon: self.min_lon = lon; changed = True
            if lon > self.max_lon: self.max_lon = lon; changed = True
            
            if changed:
                self._redraw_canvas()
            else:
                self._draw_canvas_point(lat, lon, color)

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
    
    def __init__(self, log_file="rtk.log", enable_gui=True):
        self.log_file = log_file
        self.parser = NMEAParser()
        self.visualizer = PositionVisualizer() if enable_gui else None
        
        # 确保日志文件存在或创建头部
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("Timestamp,Latitude,Longitude,Altitude,Quality,Satellites,HDOP\n")
                
    def process_data(self, data: str):
        """
        处理定位数据
        Args:
            data: 原始数据字符串 (如NMEA语句)
        """
        data = data.strip()
        if not data:
            return
            
        # 识别格式并解析
        position = None
        
        # 简单判断是否为GGA (也可以通过NMEAParser自动判断)
        if "GGA" in data:
            # 确保是完整的NMEA语句格式 (简单的检查)
            if not data.startswith('$'):
                # 尝试修复或忽略
                if 'GPGGA' in data or 'GNGGA' in data:
                     idx = data.find('$')
                     if idx != -1: data = data[idx:]
                     else: 
                         # 可能是没有$前缀
                         pass 
            
            position = self.parser.parse_sentence(data)
            
        # 如果解析成功且有效
        if position:
            self.handle_position(position)
            
    def handle_position(self, position: GPSPosition):
        """处理解析后的位置信息"""
        
        # 处理基站数据
        if position.type == PositionType.BASE:
            self.update_base_position(position.latitude, position.longitude)
            # 基站数据也可以记录到日志，或者单独记录
            return

        # 过滤无效数据 (Invalid = 0)
        if position.fix_quality == FixQuality.INVALID:
            return
            
        # 1. 存储到日志
        self._save_to_log(position)
        
        # 2. 可视化更新
        if self.visualizer:
            self.visualizer.update_position(position)
            
    def _save_to_log(self, position: GPSPosition):
        """保存到日志文件"""
        try:
            timestamp_str = position.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            log_line = (f"{timestamp_str},{position.latitude:.8f},{position.longitude:.8f},"
                        f"{position.altitude:.3f},{position.fix_quality.name},{position.satellites_used},"
                        f"{position.hdop:.2f}\n")
            
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_line)
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

def evaluate_online_map():
    """
    评估在线地图加载方案 (暂不实现)
    
    1. tkintermapview
       - 优点: 专为Tkinter设计，集成简单，支持OSM/Google/Bing瓦片，支持标记和路径。
       - 缺点: 需要依赖库 (pip install tkintermapview)。
       - 适用性: 最佳选择，如果允许添加依赖。
       
    2. folium
       - 优点: 功能强大，基于Leaflet.js。
       - 缺点: 生成HTML文件，需要在浏览器中打开或使用WebEngine嵌入，不适合实时高频更新。
       - 适用性: 适合事后分析或低频更新。
       
    3. matplotlib + contextily
       - 优点: 科学计算常用。
       - 缺点: 交互性较差，刷新率低。
       
    结论: 推荐使用 tkintermapview 作为后续在线地图可视化的实现方案。
    """
    pass

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
            
            # 构造伪造的 GPSPosition 对象直接调用 (跳过 parser 校验和麻烦)
            # 但为了测试 process_data，我们应该构造字符串。
            # 这里为了演示 Visualizer 效果，直接调用内部方法
            
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
