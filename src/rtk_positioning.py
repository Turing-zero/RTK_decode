#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTK定位系统
支持NMEA、RTCM协议解析，串口通信和NTRIP客户端功能
"""

import serial
import socket
import threading
import time
import struct
import math
import base64
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass
from enum import Enum

# 尝试导入PositionHandler
try:
    from .position_handler import PositionHandler
except ImportError:
    # 如果在同一目录下
    try:
        from position_handler import PositionHandler
    except ImportError:
        PositionHandler = None

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FixQuality(Enum):
    """定位质量枚举"""
    INVALID = 0
    GPS_FIX = 1
    DGPS_FIX = 2
    PPS_FIX = 3
    RTK_FIXED = 4
    RTK_FLOAT = 5
    ESTIMATED = 6
    MANUAL = 7
    SIMULATION = 8


class PositionType(Enum):
    """位置类型枚举"""
    ROVER = 0
    BASE = 1


@dataclass
class GPSPosition:
    """GPS位置信息"""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    fix_quality: FixQuality = FixQuality.INVALID
    satellites_used: int = 0
    hdop: float = 0.0
    timestamp: datetime = None
    speed: float = 0.0
    course: float = 0.0

    age: float = 0.0
    stn_id: int = 0
    type: PositionType = PositionType.ROVER
    extra_info: Dict = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.extra_info is None:
            self.extra_info = {}

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'fix_quality': self.fix_quality.name,
            'satellites_used': self.satellites_used,
            'hdop': self.hdop,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'speed': self.speed,
            'course': self.course,
            'age': self.age,
            'stn_id': self.stn_id,
            'type': self.type.name,
            'extra_info': self.extra_info
        }

    @classmethod
    def from_dict(cls, data: Dict):
        """从字典创建对象"""
        try:
            timestamp = datetime.fromisoformat(data['timestamp']) if data.get('timestamp') else None
        except:
            timestamp = None

        return cls(
            latitude=data.get('latitude', 0.0),
            longitude=data.get('longitude', 0.0),
            altitude=data.get('altitude', 0.0),
            fix_quality=FixQuality[data.get('fix_quality', 'INVALID')],
            satellites_used=data.get('satellites_used', 0),
            hdop=data.get('hdop', 0.0),
            timestamp=timestamp,
            speed=data.get('speed', 0.0),
            course=data.get('course', 0.0),
            age=data.get('age', 0.0),
            stn_id=data.get('stn_id', 0),
            type=PositionType[data.get('type', 'ROVER')],
            extra_info=data.get('extra_info', {})
        )


class NMEAParser:
    """NMEA协议解析器"""
    
    def __init__(self, enabled_messages: Optional[List[str]] = None):
        """
        初始化NMEA解析器
        
        Args:
            enabled_messages: 启用的NMEA消息类型列表，如['GGA', 'RMC']
                            如果为None，则解析所有支持的消息类型
        """
        self.position = GPSPosition()
        self.callbacks = {}
        # 设置启用的消息类型，默认解析所有支持的类型
        self.enabled_messages = set(enabled_messages) if enabled_messages else {'GGA', 'RMC', 'GLL'}
        self.supported_messages = {'GGA', 'RMC', 'GLL'}  # 当前支持的消息类型
    
    def register_callback(self, message_type: str, callback: Callable):
        """注册消息回调函数"""
        self.callbacks[message_type] = callback
    
    def calculate_checksum(self, sentence: str) -> str:
        """计算NMEA校验和"""
        checksum = 0
        for char in sentence:
            checksum ^= ord(char)
        return f"{checksum:02X}"
    
    def validate_checksum(self, sentence: str) -> bool:
        """验证NMEA校验和"""
        if not sentence or len(sentence) < 8:
            return False
            
        if '*' not in sentence:
            return False
        
        try:
            data, checksum = sentence.split('*', 1)
            if len(checksum) != 2:
                return False
                
            calculated = self.calculate_checksum(data[1:])  # 去掉$符号
            return calculated == checksum.upper()
        except (ValueError, IndexError):
            return False
    
    def parse_coordinate(self, coord_str: str, direction: str) -> float:
        """解析坐标格式 (DDMM.MMMM)"""
        if not coord_str or not direction:
            return 0.0
        
        try:
            coord = float(coord_str)
            degrees = int(coord / 100)
            minutes = coord - (degrees * 100)
            decimal_degrees = degrees + (minutes / 60)
            
            if direction in ['S', 'W']:
                decimal_degrees = -decimal_degrees
            
            return decimal_degrees
        except ValueError:
            return 0.0
    
    def parse_gga(self, fields: List[str]) -> GPSPosition:
        """解析GGA消息 (全球定位系统定位数据)"""
        if len(fields) < 15:
            return self.position
        
        try:
            # 时间
            time_str = fields[1]
            if time_str:
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                second = int(float(time_str[4:]))
                now = datetime.now()
                timestamp = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            else:
                timestamp = datetime.now()
            
            # 位置
            lat = self.parse_coordinate(fields[2], fields[3])
            lon = self.parse_coordinate(fields[4], fields[5])
            
            # 定位质量
            quality = int(fields[6]) if fields[6] else 0
            fix_quality = FixQuality(quality) if quality <= 8 else FixQuality.INVALID
            
            # 卫星数量
            satellites = int(fields[7]) if fields[7] else 0
            
            # HDOP
            hdop = float(fields[8]) if fields[8] else 0.0
            
            # 海拔
            altitude = float(fields[9]) if fields[9] else 0.0

            # 差分数据丢失时间
            age = float(fields[13]) if fields[13] else 0.0

            # 基站ID
            stn_id = int(fields[14]) if fields[14] else 0
            
            self.position = GPSPosition(
                latitude=lat,
                longitude=lon,
                altitude=altitude,
                fix_quality=fix_quality,
                satellites_used=satellites,
                hdop=hdop,
                timestamp=timestamp,
                age=age,
                stn_id=stn_id,
            )
            
        except (ValueError, IndexError) as e:
            logger.warning(f"解析GGA消息失败: {e}")
        
        return self.position
    
    def parse_rmc(self, fields: List[str]) -> GPSPosition:
        """解析RMC消息 (推荐最小定位信息)"""
        if len(fields) < 12:
            return self.position
        
        try:
            # 状态
            status = fields[2]
            if status != 'A':  # A=有效, V=无效
                return self.position
            
            # 位置
            lat = self.parse_coordinate(fields[3], fields[4])
            lon = self.parse_coordinate(fields[5], fields[6])
            
            # 速度 (节转换为km/h)
            speed = float(fields[7]) * 1.852 if fields[7] else 0.0
            
            # 航向
            course = float(fields[8]) if fields[8] else 0.0
            
            # 日期和时间
            date_str = fields[9]
            time_str = fields[1]
            if date_str and time_str:
                day = int(date_str[:2])
                month = int(date_str[2:4])
                year = 2000 + int(date_str[4:6])
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                second = int(float(time_str[4:]))
                timestamp = datetime(year, month, day, hour, minute, second)
            else:
                timestamp = datetime.now()
            
            # 更新位置信息
            self.position.latitude = lat
            self.position.longitude = lon
            self.position.speed = speed
            self.position.course = course
            self.position.timestamp = timestamp
            
        except (ValueError, IndexError) as e:
            logger.warning(f"解析RMC消息失败: {e}")
        
        return self.position

    def parse_gll(self, fields: List[str]) -> GPSPosition:
        """解析GLL消息 (地理定位信息)"""
        # Format: $GNGLL,lat,N/S,lon,E/W,time,status,mode*cs
        if len(fields) < 7:
            return self.position

        try:
            # 位置
            lat = self.parse_coordinate(fields[1], fields[2])
            lon = self.parse_coordinate(fields[3], fields[4])

            # 时间
            time_str = fields[5]
            if time_str:
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                second = int(float(time_str[4:]))
                now = datetime.now()
                timestamp = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            else:
                timestamp = datetime.now()

            # 状态 (A=有效, V=无效)
            status = fields[6]
            quality = FixQuality.GPS_FIX if status == 'A' else FixQuality.INVALID

            # 更新位置信息
            self.position.latitude = lat
            self.position.longitude = lon
            self.position.timestamp = timestamp
            self.position.fix_quality = quality

        except (ValueError, IndexError) as e:
            logger.warning(f"解析GLL消息失败: {e}")

        return self.position

    def parse_sentence(self, sentence: str) -> Optional[GPSPosition]:
        """解析NMEA语句"""
        sentence = sentence.strip()
        if not sentence.startswith('$'):
            return None
        
        if not self.validate_checksum(sentence):
            logger.warning(f"NMEA校验和错误: {sentence}")
            return None
        
        # 移除校验和部分
        if '*' in sentence:
            sentence = sentence.split('*')[0]
        
        fields = sentence.split(',')
        message_type = fields[0][3:]  # 去掉$GP前缀
        
        # 检查是否启用了该消息类型
        if message_type not in self.enabled_messages:
            return None
        
        position = None
        if message_type == 'GGA':
            position = self.parse_gga(fields)
        elif message_type == 'RMC':
            position = self.parse_rmc(fields)
        elif message_type == 'GLL':
            position = self.parse_gll(fields)
        
        # 调用回调函数
        if message_type in self.callbacks:
            self.callbacks[message_type](fields, position)
        
        return position
    
    def set_enabled_messages(self, enabled_messages: List[str]):
        """
        设置启用的NMEA消息类型
        
        Args:
            enabled_messages: 启用的消息类型列表，如['GGA', 'RMC']
        """
        # 只启用支持的消息类型
        valid_messages = [msg for msg in enabled_messages if msg in self.supported_messages]
        self.enabled_messages = set(valid_messages)
        logger.info(f"已设置启用的NMEA消息类型: {list(self.enabled_messages)}")
    
    def get_enabled_messages(self) -> List[str]:
        """获取当前启用的NMEA消息类型"""
        return list(self.enabled_messages)
    
    def get_supported_messages(self) -> List[str]:
        """获取支持的NMEA消息类型"""
        return list(self.supported_messages)


class RTCMParser:
    """RTCM协议解析器"""
    
    def __init__(self):
        self.buffer = bytearray()
        self.callbacks = {}
    
    def register_callback(self, message_type: int, callback: Callable):
        """注册消息回调函数"""
        self.callbacks[message_type] = callback
    
    def crc24(self, data: bytes) -> int:
        """计算CRC24校验"""
        crc = 0
        for byte in data:
            crc ^= byte << 16
            for _ in range(8):
                if crc & 0x800000:
                    crc = (crc << 1) ^ 0x1864CFB
                else:
                    crc <<= 1
                crc &= 0xFFFFFF
        return crc
    
    def parse_message(self, data: bytes) -> List[Dict]:
        """解析RTCM消息"""
        messages = []
        self.buffer.extend(data)
        
        while len(self.buffer) >= 3:
            # 查找RTCM帧头 (0xD3)
            start_idx = -1
            for i in range(len(self.buffer)):
                if self.buffer[i] == 0xD3:
                    start_idx = i
                    break
            
            if start_idx == -1:
                self.buffer.clear()
                break
            
            if start_idx > 0:
                self.buffer = self.buffer[start_idx:]
            
            if len(self.buffer) < 6:
                break
            
            # 解析消息长度
            length = ((self.buffer[1] & 0x03) << 8) | self.buffer[2]
            total_length = length + 6  # 3字节头 + 数据 + 3字节CRC
            
            if len(self.buffer) < total_length:
                break
            
            # 提取完整消息
            message_data = bytes(self.buffer[:total_length])
            self.buffer = self.buffer[total_length:]
            
            # 验证CRC
            payload = message_data[3:-3]
            received_crc = struct.unpack('>I', b'\x00' + message_data[-3:])[0]
            calculated_crc = self.crc24(message_data[:-3])
            
            if received_crc != calculated_crc:
                logger.warning("RTCM CRC校验失败")
                continue
            
            # 解析消息类型
            if len(payload) >= 2:
                message_type = struct.unpack('>H', payload[:2])[0] >> 4
                
                message_info = {
                    'type': message_type,
                    'length': length,
                    'data': payload,
                    'timestamp': datetime.now()
                }
                
                messages.append(message_info)
                
                # 调用回调函数
                if message_type in self.callbacks:
                    self.callbacks[message_type](message_info)
                
                logger.debug(f"收到RTCM消息类型: {message_type}, 长度: {length}")
        
        return messages


class SerialCommunicator:
    """串口通信类"""
    
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.is_connected = False
        self.read_thread = None
        self.stop_event = threading.Event()
        self.data_callbacks = []
    
    def add_data_callback(self, callback: Callable[[bytes], None]):
        """添加数据接收回调函数"""
        self.data_callbacks.append(callback)
    
    def connect(self) -> bool:
        """连接串口"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            self.is_connected = True
            logger.info(f"串口连接成功: {self.port}")
            
            # 启动读取线程
            self.stop_event.clear()
            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()
            
            return True
        except Exception as e:
            logger.error(f"串口连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开串口连接"""
        self.stop_event.set()
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        
        self.is_connected = False
        logger.info("串口连接已断开")
    
    def send_data(self, data: bytes) -> bool:
        """发送数据"""
        if not self.is_connected or not self.serial_conn:
            logger.warning("尝试发送数据但串口未连接")
            return False
        
        try:
            bytes_written = self.serial_conn.write(data)
            self.serial_conn.flush()
            # 仅在DEBUG模式或每隔一定次数打印，避免刷屏
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"已写入串口: {bytes_written} 字节")
            return True
        except Exception as e:
            logger.error(f"发送数据失败: {e}")
            return False
    
    def _read_loop(self):
        """数据读取循环"""
        while not self.stop_event.is_set() and self.is_connected:
            try:
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    if data:
                        for callback in self.data_callbacks:
                            try:
                                callback(data)
                            except Exception as e:
                                logger.error(f"数据回调函数执行失败: {e}")
                
                time.sleep(0.01)  # 避免CPU占用过高
            except Exception as e:
                logger.error(f"串口读取错误: {e}")
                break


class NTRIPClient:
    """NTRIP客户端"""
    
    def __init__(self, host: str, port: int, mountpoint: str, 
                 username: str = "", password: str = ""):
        self.host = host
        self.port = port
        self.mountpoint = mountpoint
        self.username = username
        self.password = password
        self.socket = None
        self.is_connected = False
        self.receive_thread = None
        self.stop_event = threading.Event()
        self.data_callbacks = []
    
    def add_data_callback(self, callback: Callable[[bytes], None]):
        """添加数据接收回调函数"""
        self.data_callbacks.append(callback)
    
    def connect(self) -> bool:
        """连接NTRIP服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((self.host, self.port))
            
            # 构建HTTP请求
            request = f"GET /{self.mountpoint} HTTP/1.1\r\n"
            request += f"Host: {self.host}:{self.port}\r\n"
            request += "User-Agent: RTK-Client/1.0\r\n"
            request += "Accept: */*\r\n"
            request += "Connection: close\r\n"
            
            # 添加认证信息
            if self.username and self.password:
                auth_string = f"{self.username}:{self.password}"
                auth_bytes = base64.b64encode(auth_string.encode()).decode()
                request += f"Authorization: Basic {auth_bytes}\r\n"
            
            request += "\r\n"
            
            # 发送请求
            self.socket.send(request.encode())
            
            # 接收响应
            response = self.socket.recv(1024).decode()
            if "200 OK" not in response:
                logger.error(f"NTRIP连接失败: {response}")
                return False
            
            self.is_connected = True
            logger.info(f"NTRIP连接成功: {self.host}:{self.port}/{self.mountpoint}")
            
            # 启动接收线程
            self.stop_event.clear()
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            return True
            
        except Exception as e:
            logger.error(f"NTRIP连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开NTRIP连接"""
        self.stop_event.set()
        if self.receive_thread:
            self.receive_thread.join(timeout=2.0)
        
        if self.socket:
            self.socket.close()
        
        self.is_connected = False
        logger.info("NTRIP连接已断开")
    
    def send_gga(self, gga_sentence: str):
        """发送GGA语句到NTRIP服务器"""
        if not self.is_connected or not self.socket:
            return
        
        try:
            self.socket.send(gga_sentence.encode() + b'\r\n')
        except Exception as e:
            logger.error(f"发送GGA失败: {e}")
    
    def _receive_loop(self):
        """数据接收循环"""
        while not self.stop_event.is_set() and self.is_connected:
            try:
                data = self.socket.recv(4096)
                if not data:
                    break
                
                for callback in self.data_callbacks:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"NTRIP数据回调函数执行失败: {e}")
                        
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"NTRIP接收错误: {e}")
                break
        
        self.is_connected = False


class MockNTRIPClient(NTRIPClient):
    """Mock NTRIP客户端，用于测试"""

    def __init__(self, host: str, port: int, mountpoint: str, username: str = "", password: str = ""):
        super().__init__(host, port, mountpoint, username, password)
        self.mock_thread = None

    def connect(self) -> bool:
        """连接Mock NTRIP客户端"""
        self.is_connected = True
        logger.info(f"Mock NTRIP客户端连接成功 (模拟模式): {self.host}:{self.port}/{self.mountpoint}")

        # 启动模拟线程
        self.stop_event.clear()
        self.mock_thread = threading.Thread(target=self._mock_loop, daemon=True)
        self.mock_thread.start()

        return True

    def disconnect(self):
        """断开Mock NTRIP客户端"""
        self.stop_event.set()
        if self.mock_thread:
            self.mock_thread.join(timeout=2.0)

        self.is_connected = False
        logger.info("Mock NTRIP客户端已断开")

    def _mock_loop(self):
        """模拟数据发送循环"""
        while not self.stop_event.is_set():
            try:
                # 构造一个符合RTCM格式的Mock数据包
                # Header: 0xD3
                # Length: 4 (0x00 0x04)
                # Payload: 4 bytes (dummy)
                # Total length = 3 (header) + 4 (payload) + 3 (CRC) = 10 bytes

                header_payload = b'\xd3\x00\x04\xaa\xbb\xcc\xdd'
                crc = self._calculate_crc24(header_payload)
                full_msg = header_payload + struct.pack('>I', crc)[1:]

                for callback in self.data_callbacks:
                    try:
                        callback(full_msg)
                        logger.debug(f"Mock发送数据: {len(full_msg)} bytes")
                    except Exception as e:
                        logger.error(f"Mock回调执行失败: {e}")

                time.sleep(0.05)  # 20Hz发送频率
            except Exception as e:
                logger.error(f"Mock循环错误: {e}")
                break

    def _calculate_crc24(self, data: bytes) -> int:
        """计算CRC24校验"""
        crc = 0
        for byte in data:
            crc ^= byte << 16
            for _ in range(8):
                if crc & 0x800000:
                    crc = (crc << 1) ^ 0x1864CFB
                else:
                    crc <<= 1
                crc &= 0xFFFFFF
        return crc

class CoordinateConverter:
    """坐标转换工具"""
    
    @staticmethod
    def wgs84_to_utm(lat: float, lon: float) -> Tuple[float, float, int, str]:
        """WGS84转UTM坐标"""
        # 简化的UTM转换实现
        zone = int((lon + 180) / 6) + 1
        hemisphere = 'N' if lat >= 0 else 'S'
        
        # 这里应该实现完整的UTM转换算法
        # 为简化示例，返回近似值
        x = (lon + 180) * 111320  # 近似转换
        y = lat * 110540  # 近似转换
        
        return x, y, zone, hemisphere
    
    @staticmethod
    def utm_to_wgs84(x: float, y: float, zone: int, hemisphere: str) -> Tuple[float, float]:
        """UTM转WGS84坐标"""
        # 简化的逆向转换
        lon = x / 111320 - 180
        lat = y / 110540
        
        if hemisphere == 'S':
            lat = -lat
        
        return lat, lon

    @staticmethod
    def ecef_to_lla(x: float, y: float, z: float) -> Tuple[float, float, float]:
        """ECEF坐标转LLA (WGS84)"""
        # WGS84椭球参数
        a = 6378137.0
        f = 1 / 298.257223563
        b = a * (1 - f)
        e2 = 2 * f - f * f
        ep2 = (a * a - b * b) / (b * b)
        
        p = math.sqrt(x * x + y * y)
        theta = math.atan2(z * a, p * b)
        
        lon = math.atan2(y, x)
        lat = math.atan2(z + ep2 * b * math.pow(math.sin(theta), 3),
                         p - e2 * a * math.pow(math.cos(theta), 3))
        
        # 转换为度
        lat_deg = math.degrees(lat)
        lon_deg = math.degrees(lon)
        alt = p / math.cos(lat) - a / math.sqrt(1 - e2 * math.sin(lat) * math.sin(lat))
        
        return lat_deg, lon_deg, alt


class RTKPositioningSystem:
    """RTK定位系统主类"""
    
    def __init__(self, enabled_nmea_messages: Optional[List[str]] = None, log_file = None):
        """
        初始化RTK定位系统
        
        Args:
            enabled_nmea_messages: 启用的NMEA消息类型列表，如['GGA', 'RMC']
                                 如果为None，则解析所有支持的消息类型
        """
        self.nmea_parser = NMEAParser(enabled_nmea_messages)
        self.rtcm_parser = RTCMParser()
        self.serial_comm = None
        self.ntrip_client = None
        self.current_position = GPSPosition()
        self.is_running = False
        self.nmea_buffer = ""  # 添加NMEA数据缓冲区
        self.logger = logging.getLogger(f"{__name__}.RTKPositioningSystem")
        
        # 初始化PositionHandler
        self.position_handler = PositionHandler(log_file=log_file if log_file else "rtk.log") if PositionHandler else None
        
        # 监控相关
        self.rtcm_stats = {}  # NTRIP数据统计 {msg_type: count}
        self.last_gga_time = time.time()
        self.monitor_thread = None
        self.monitor_stop_event = threading.Event()
        # 默认GGA (北京坐标)，用于串口无数据时保活
        self.default_gga = "$GPGGA,065956.60,3013.3614955,N,12021.3076062,E,1,25,0.8,7.7175,M,7.953,M,,*69"
        
        # 注册回调函数
        self.nmea_parser.register_callback('GGA', self._on_gga_received)
        self.nmea_parser.register_callback('RMC', self._on_rmc_received)
        self.rtcm_parser.register_callback(1005, self._on_rtcm_1005)
        self.rtcm_parser.register_callback(1077, self._on_rtcm_1077)
    
    def configure_serial(self, port: str, baudrate: int = 115200):
        """配置串口通信"""
        if self.serial_comm:
            self.serial_comm.disconnect()
        
        self.serial_comm = SerialCommunicator(port, baudrate)
        self.serial_comm.add_data_callback(self._on_serial_data)
    
    def configure_ntrip(self, host: str, port: int, mountpoint: str,
                       username: str = "", password: str = "", mock: bool = False):
        """配置NTRIP客户端"""
        if self.ntrip_client:
            self.ntrip_client.disconnect()
        
        if mock:
            self.ntrip_client = MockNTRIPClient(host, port, mountpoint, username, password)
        else:
            self.ntrip_client = NTRIPClient(host, port, mountpoint, username, password)

        self.ntrip_client.add_data_callback(self._on_ntrip_data)
    
    def start(self) -> bool:
        """启动RTK定位系统"""
        success = True
        
        # 连接串口
        if self.serial_comm:
            if not self.serial_comm.connect():
                success = False
        
        # 连接NTRIP
        if self.ntrip_client:
            if not self.ntrip_client.connect():
                success = False
        
        if success:
            self.is_running = True

            # 启动监控线程
            self.monitor_stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

            logger.info("RTK定位系统启动成功")
        else:
            logger.error("RTK定位系统启动失败")
        
        return success
    
    def stop(self):
        """停止RTK定位系统"""
        self.is_running = False

        # 停止监控线程
        self.monitor_stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)

        if self.serial_comm:
            self.serial_comm.disconnect()
        
        if self.ntrip_client:
            self.ntrip_client.disconnect()
            
        if self.position_handler:
            self.position_handler.close()
        
        logger.info("RTK定位系统已停止")

    def _monitor_loop(self):
        """系统监控循环"""
        while not self.monitor_stop_event.is_set():
            current_time = time.time()
            
            # 1. 检查GGA数据超时 (10秒)
            if self.ntrip_client and self.ntrip_client.is_connected:
                if current_time - self.last_gga_time > 2:
                    logger.warning("未检测到串口GGA数据输入，发送默认GGA以保持NTRIP连接")
                    self.ntrip_client.send_gga(self.default_gga)
                    
                    # 避免立即重复发送，重置计时器或稍微推后
                    # 这里我们不更新last_gga_time，因为那代表真实收到数据的时间
                    # 但为了防止循环太快，我们在循环末尾有sleep
            
            # 2. 输出NTRIP数据统计 (每10秒)
            if int(current_time) % 10 == 0:
                if self.rtcm_stats:
                    stats_str = ", ".join([f"Type {k}: {v}" for k, v in sorted(self.rtcm_stats.items())])
                    logger.info(f"NTRIP数据统计 (累计): {stats_str}")

            time.sleep(1.0) # 每秒检查一次

    def get_position(self) -> GPSPosition:
        """获取当前位置"""
        return self.current_position
    
    def set_nmea_message_filter(self, enabled_messages: List[str]):
        """
        设置NMEA消息类型过滤器
        
        Args:
            enabled_messages: 启用的消息类型列表，如['GGA', 'RMC']
        """
        self.nmea_parser.set_enabled_messages(enabled_messages)
    
    def get_enabled_nmea_messages(self) -> List[str]:
        """获取当前启用的NMEA消息类型"""
        return self.nmea_parser.get_enabled_messages()
    
    def get_supported_nmea_messages(self) -> List[str]:
        """获取支持的NMEA消息类型"""
        return self.nmea_parser.get_supported_messages()
    
    def _on_serial_data(self, data: bytes):
        """处理串口数据"""
        try:
            # 将新数据添加到缓冲区，使用更宽松的错误处理
            text_data = data.decode('ascii', errors='replace')
            self.nmea_buffer += text_data
            
            # 处理完整的NMEA消息
            while '\n' in self.nmea_buffer:
                line_end = self.nmea_buffer.find('\n')
                line = self.nmea_buffer[:line_end].strip()
                self.nmea_buffer = self.nmea_buffer[line_end + 1:]
                
                if not line:
                    continue
                
                # 处理NMEA消息
                if line.startswith('$') and len(line) > 6:
                    # 只处理包含校验和的完整消息
                    if '*' in line and len(line.split('*')) == 2:
                        # 验证校验和
                        if not self.nmea_parser.validate_checksum(line):
                            continue
                        
                        try:
                            position = self.nmea_parser.parse_sentence(line)
                            if position:
                                self.current_position = position
                                # print(position)
                                # 只在有有效定位时记录详细信息
                                if position.fix_quality.value > 0:
                                    self.logger.debug(f"位置更新: {position.latitude:.6f}, {position.longitude:.6f}, 质量: {position.fix_quality.name}")
                        except Exception as e:
                            self.logger.debug(f"解析NMEA消息失败: {e}")
            
            # 防止缓冲区过大
            if len(self.nmea_buffer) > 10000:
                self.nmea_buffer = self.nmea_buffer[-5000:]
                self.logger.warning("NMEA缓冲区过大，已清理")
                
        except Exception as e:
            self.logger.error(f"处理串口数据失败: {e}")
    
    def _on_ntrip_data(self, data: bytes):
        """处理NTRIP数据"""
        try:
            # 优先转发数据给GPS设备 (无论解析是否成功，原始数据都必须转发)
            if self.serial_comm:
                if not self.serial_comm.send_data(data):
                    logger.warning(f"转发NTRIP数据到串口失败 ({len(data)} bytes)")
            else:
                logger.warning("收到NTRIP数据但未配置串口，无法转发")

            # 解析RTCM数据 (仅用于统计)
            messages = self.rtcm_parser.parse_message(data)

            # 统计消息类型
            for msg in messages:
                msg_type = msg.get('type')
                if msg_type:
                    self.rtcm_stats[msg_type] = self.rtcm_stats.get(msg_type, 0) + 1
                
        except Exception as e:
            logger.error(f"处理NTRIP数据失败: {e}")
    
    def _on_gga_received(self, fields: List[str], position: GPSPosition):
        """GGA消息回调"""
        self.last_gga_time = time.time()  # 更新收到GGA的时间
        
        # 使用PositionHandler处理 (存储、可视化)
        if self.position_handler:
            self.position_handler.handle_position(position)
        
        if position and position.fix_quality != FixQuality.INVALID:
            # 发送GGA到NTRIP服务器
            if self.ntrip_client and self.ntrip_client.is_connected:
                gga_sentence = ','.join(fields)
                self.ntrip_client.send_gga(gga_sentence)
                logger.debug(f"发送GGA到NTRIP服务器: {gga_sentence}")
        else:
            # 添加了这条日志，方便调试
            logger.info(f"收到GGA消息但定位无效 (Quality: {position.fix_quality.name if position else 'None'}), 发送默认GGA以保持NTRIP连接")
            if self.ntrip_client and self.ntrip_client.is_connected:
                self.ntrip_client.send_gga(self.default_gga)

    def _on_rmc_received(self, fields: List[str], position: GPSPosition):
        """RMC消息回调"""
        logger.debug(f"收到RMC: 位置({position.latitude:.6f}, {position.longitude:.6f})")
    
    def _on_rtcm_1005(self, message: Dict):
        """RTCM 1005消息回调 (基站坐标)"""
        try:
            payload = message['data']
            if not payload:
                return

            # 将bytes转换为大整数以便位操作
            # RTCM消息是大端序
            bits_val = int.from_bytes(payload, 'big')
            total_bits = len(payload) * 8
            
            # 辅助函数：提取指定位
            def get_bits(start_bit, length):
                # start_bit: 从0开始，高位在前
                shift = total_bits - (start_bit + length)
                mask = (1 << length) - 1
                return (bits_val >> shift) & mask
            
            # 提取带符号位
            def get_signed_bits(start_bit, length):
                val = get_bits(start_bit, length)
                if val & (1 << (length - 1)):
                    val -= (1 << length)
                return val

            # RTCM 1005 结构解析 (Message Number 12 bits starts at 0)
            # DF025: 38 bits (Antenna Reference Point ECEF-X) - offset 34
            # DF028: 38 bits (Antenna Reference Point ECEF-Y) - offset 74
            # DF030: 38 bits (Antenna Reference Point ECEF-Z) - offset 114
            
            # ECEF X
            x_int = get_signed_bits(34, 38)
            x = x_int * 0.0001
            
            # ECEF Y
            y_int = get_signed_bits(74, 38)
            y = y_int * 0.0001
            
            # ECEF Z
            z_int = get_signed_bits(114, 38)
            z = z_int * 0.0001
            
            logger.debug(f"基站ECEF坐标: X={x:.4f}, Y={y:.4f}, Z={z:.4f}")
            
            # 转换为LLA
            lat, lon, alt = CoordinateConverter.ecef_to_lla(x, y, z)
            logger.info(f"基站位置更新: Lat={lat:.8f}, Lon={lon:.8f}, Alt={alt:.3f}")
            
            # 构造GPSPosition对象并传递给PositionHandler
            if self.position_handler:
                base_position = GPSPosition(
                    latitude=lat,
                    longitude=lon,
                    altitude=alt,
                    fix_quality=FixQuality.SIMULATION, # 基站坐标通常是固定的
                    type=PositionType.BASE,
                    timestamp=datetime.now()
                )
                self.position_handler.handle_position(base_position)
                
        except Exception as e:
            logger.error(f"解析RTCM 1005失败: {e}")
    
    def _on_rtcm_1077(self, message: Dict):
        """RTCM 1077消息回调 (GPS MSM7)"""
        logger.debug("收到RTCM 1077消息 (GPS MSM7)")


def main():
    """主函数示例"""
    # 创建RTK定位系统
    rtk_system = RTKPositioningSystem()
    
    # 配置串口 (根据实际情况修改)
    rtk_system.configure_serial('COM3', 115200)
    
    # 配置NTRIP (根据实际情况修改)
    rtk_system.configure_ntrip(
        host='your-ntrip-server.com',
        port=8002,
        mountpoint='MOUNT_POINT',
        username='your_username',
        password='your_password'
    )
    
    try:
        # 启动系统
        if rtk_system.start():
            print("RTK定位系统运行中...")
            print("按Ctrl+C停止")
            
            # 主循环
            while True:
                time.sleep(1)
                position = rtk_system.get_position()
                
                if position.fix_quality != FixQuality.INVALID:
                    print(f"位置: {position.latitude:.8f}, {position.longitude:.8f}")
                    print(f"海拔: {position.altitude:.2f}m")
                    print(f"定位质量: {position.fix_quality.name}")
                    print(f"卫星数: {position.satellites_used}")
                    print(f"HDOP: {position.hdop:.2f}")
                    print("-" * 50)
                
    except KeyboardInterrupt:
        print("\n正在停止系统...")
    finally:
        rtk_system.stop()


if __name__ == "__main__":
    main()