"""
RTK定位系统核心模块

该模块提供RTK定位系统的核心功能，包括：
- NMEA消息解析
- 坐标转换
- RTK定位系统管理
"""

from .rtk_positioning import RTKPositioningSystem, NMEAParser, GPSPosition, FixQuality

__version__ = "1.0.0"
__all__ = ["RTKPositioningSystem", "NMEAParser", "GPSPosition", "FixQuality"]