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
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


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
        self.enabled_messages = set(enabled_messages) if enabled_messages else {'GGA', 'RMC'}
        self.supported_messages = {'GGA', 'RMC'}  # 当前支持的消息类型
    
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
            
            self.position = GPSPosition(
                latitude=lat,
                longitude=lon,
                altitude=altitude,
                fix_quality=fix_quality,
                satellites_used=satellites,
                hdop=hdop,
                timestamp=timestamp
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
            return False
        
        try:
            self.serial_conn.write(data)
            self.serial_conn.flush()
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


class RTKPositioningSystem:
    """RTK定位系统主类"""
    
    def __init__(self, enabled_nmea_messages: Optional[List[str]] = None):
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
                       username: str = "", password: str = ""):
        """配置NTRIP客户端"""
        if self.ntrip_client:
            self.ntrip_client.disconnect()
        
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
            logger.info("RTK定位系统启动成功")
        else:
            logger.error("RTK定位系统启动失败")
        
        return success
    
    def stop(self):
        """停止RTK定位系统"""
        self.is_running = False
        
        if self.serial_comm:
            self.serial_comm.disconnect()
        
        if self.ntrip_client:
            self.ntrip_client.disconnect()
        
        logger.info("RTK定位系统已停止")
    
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
            # 解析RTCM数据
            messages = self.rtcm_parser.parse_message(data)
            
            # 将RTCM数据转发给GPS设备
            if self.serial_comm and messages:
                self.serial_comm.send_data(data)
                
        except Exception as e:
            logger.error(f"处理NTRIP数据失败: {e}")
    
    def _on_gga_received(self, fields: List[str], position: GPSPosition):
        """GGA消息回调"""
        if position and position.fix_quality != FixQuality.INVALID:
            # 发送GGA到NTRIP服务器
            if self.ntrip_client and self.ntrip_client.is_connected:
                gga_sentence = ','.join(fields)
                self.ntrip_client.send_gga(gga_sentence)
    
    def _on_rmc_received(self, fields: List[str], position: GPSPosition):
        """RMC消息回调"""
        logger.debug(f"收到RMC: 位置({position.latitude:.6f}, {position.longitude:.6f})")
    
    def _on_rtcm_1005(self, message: Dict):
        """RTCM 1005消息回调 (基站坐标)"""
        logger.debug("收到RTCM 1005消息 (基站坐标)")
    
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