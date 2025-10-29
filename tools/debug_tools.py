#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTK系统调试工具集
整合了NMEA调试、系统测试等功能
"""

import serial
import time
import json
import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rtk_positioning import RTKPositioningSystem, NMEAParser

class RTKDebugTools:
    """RTK调试工具集"""
    
    def __init__(self):
        self.config = self._load_config()
        self.parser = NMEAParser()
    
    def _load_config(self):
        """加载配置文件"""
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ 配置文件加载失败: {e}")
            sys.exit(1)
    
    def quick_test(self, duration: int = 15):
        """快速系统测试"""
        print("🚀 RTK系统快速测试")
        print("=" * 50)
        
        # 创建RTK系统
        rtk_system = RTKPositioningSystem()
        
        try:
            # 配置系统
            serial_config = self.config['serial']
            rtk_system.configure_serial(
                port=serial_config['port'],
                baudrate=serial_config['baudrate']
            )
            print(f"✅ 串口配置: {serial_config['port']} @ {serial_config['baudrate']}")
            
            # 启动系统
            if not rtk_system.start():
                print("❌ 系统启动失败")
                return
            
            print(f"✅ 系统启动成功，开始测试 ({duration}秒)...")
            print("-" * 50)
            
            # 运行测试
            start_time = time.time()
            position_count = 0
            last_position = None
            
            while time.time() - start_time < duration:
                current_position = rtk_system.get_position()
                
                if current_position != last_position:
                    position_count += 1
                    timestamp = time.strftime("%H:%M:%S")
                    
                    if current_position.fix_quality.value > 0:
                        print(f"[{timestamp}] 📍 {current_position.latitude:.6f}, {current_position.longitude:.6f}")
                        print(f"           🛰️  {current_position.fix_quality.name}, 卫星: {current_position.satellites_used}")
                    else:
                        print(f"[{timestamp}] 🔍 搜索卫星中...")
                    
                    last_position = current_position
                
                time.sleep(0.5)
            
            # 测试结果
            print("\n" + "=" * 50)
            print("📊 测试结果:")
            print(f"   位置更新: {position_count} 次")
            if last_position:
                print(f"   定位质量: {last_position.fix_quality.name}")
                if last_position.fix_quality.value > 0:
                    print("✅ 系统正常，已获得GPS定位")
                else:
                    print("⏳ 系统正常，等待GPS信号")
            
        except KeyboardInterrupt:
            print("\n⏹️  用户中断测试")
        finally:
            rtk_system.stop()
            print("🔚 系统已停止")
    
    def nmea_analysis(self, duration: int = 30, show_raw: bool = False):
        """NMEA数据分析"""
        print("🔍 NMEA数据分析")
        print("=" * 50)
        
        serial_config = self.config['serial']
        print(f"连接串口: {serial_config['port']} @ {serial_config['baudrate']}")
        
        if show_raw:
            print("📡 原始数据输出模式已启用")
        
        try:
            # 连接串口
            ser = serial.Serial(
                port=serial_config['port'],
                baudrate=serial_config['baudrate'],
                timeout=1.0
            )
            
            buffer = ""
            stats = {
                'total_bytes': 0,
                'total_lines': 0,
                'valid_nmea': 0,
                'checksum_errors': 0,
                'incomplete_lines': 0,
                'message_types': {}
            }
            
            print(f"开始分析数据 ({duration}秒)...")
            if show_raw:
                print("-" * 80)
            
            start_time = time.time()
            
            while time.time() - start_time < duration:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    stats['total_bytes'] += len(data)
                    
                    # 显示原始字节数据
                    if show_raw and data:
                        timestamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
                        hex_data = ' '.join(f'{b:02X}' for b in data)
                        print(f"[{timestamp}] RAW ({len(data)} bytes): {hex_data}")
                        
                        # 尝试显示ASCII表示
                        try:
                            ascii_data = data.decode('ascii', errors='replace')
                            ascii_repr = repr(ascii_data)
                            print(f"[{timestamp}] ASCII: {ascii_repr}")
                        except:
                            pass
                        print()
                    
                    try:
                        text_data = data.decode('ascii', errors='ignore')
                        buffer += text_data
                        
                        # 处理完整的行
                        while '\n' in buffer:
                            line_end = buffer.find('\n')
                            line = buffer[:line_end].strip()
                            buffer = buffer[line_end + 1:]
                            
                            if not line or not line.startswith('$'):
                                continue
                                
                            stats['total_lines'] += 1
                            
                            # 显示NMEA消息
                            if show_raw:
                                timestamp = time.strftime("%H:%M:%S")
                                print(f"[{timestamp}] NMEA: {line}")
                            
                            # 检查完整性
                            if '*' not in line:
                                stats['incomplete_lines'] += 1
                                if show_raw:
                                    print(f"           ❌ 不完整消息 (缺少校验和)")
                                continue
                            
                            # 检查校验和
                            if not self.parser.validate_checksum(line):
                                stats['checksum_errors'] += 1
                                if show_raw:
                                    print(f"           ❌ 校验和错误")
                                continue
                            
                            # 统计消息类型
                            fields = line.split(',')
                            if len(fields) > 0:
                                message_type = fields[0][3:] if len(fields[0]) > 3 else fields[0]
                                stats['message_types'][message_type] = stats['message_types'].get(message_type, 0) + 1
                                
                                if show_raw:
                                    print(f"           ✅ 有效的 {message_type} 消息")
                            
                            stats['valid_nmea'] += 1
                            
                            if show_raw:
                                print()
                    
                    except Exception as e:
                        print(f"⚠️  数据处理错误: {e}")
                
                time.sleep(0.01)
            
            # 打印统计结果
            if show_raw:
                print("-" * 80)
            self._print_nmea_stats(stats)
            ser.close()
            
        except Exception as e:
            print(f"❌ 串口连接失败: {e}")
    
    def raw_data_monitor(self, duration: int = 10):
        """原始数据监控"""
        print("📡 原始数据监控")
        print("=" * 50)
        
        serial_config = self.config['serial']
        print(f"连接串口: {serial_config['port']} @ {serial_config['baudrate']}")
        print(f"监控时长: {duration}秒")
        print("=" * 80)
        
        try:
            # 连接串口
            ser = serial.Serial(
                port=serial_config['port'],
                baudrate=serial_config['baudrate'],
                timeout=1.0
            )
            
            start_time = time.time()
            total_bytes = 0
            
            while time.time() - start_time < duration:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    total_bytes += len(data)
                    
                    timestamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
                    
                    # 显示十六进制数据
                    hex_data = ' '.join(f'{b:02X}' for b in data)
                    print(f"[{timestamp}] HEX ({len(data):3d}): {hex_data}")
                    
                    # 显示ASCII数据
                    try:
                        ascii_data = data.decode('ascii', errors='replace')
                        # 替换不可打印字符
                        display_data = ''.join(c if c.isprintable() or c in '\r\n' else f'\\x{ord(c):02x}' for c in ascii_data)
                        print(f"[{timestamp}] ASC ({len(data):3d}): {repr(display_data)}")
                    except:
                        print(f"[{timestamp}] ASC ({len(data):3d}): <decode error>")
                    
                    print("-" * 80)
                
                time.sleep(0.01)
            
            print(f"\n📊 监控完成，总接收字节数: {total_bytes:,}")
            ser.close()
            
        except Exception as e:
            print(f"❌ 串口连接失败: {e}")
    
    def _print_nmea_stats(self, stats):
        """打印NMEA统计信息"""
        print("\n" + "=" * 50)
        print("📊 NMEA数据统计:")
        print(f"   总字节数: {stats['total_bytes']:,}")
        print(f"   总行数: {stats['total_lines']:,}")
        print(f"   有效NMEA: {stats['valid_nmea']:,}")
        print(f"   校验和错误: {stats['checksum_errors']:,}")
        print(f"   不完整消息: {stats['incomplete_lines']:,}")
        
        if stats['message_types']:
            print("\n📡 消息类型分布:")
            for msg_type, count in sorted(stats['message_types'].items()):
                print(f"   {msg_type}: {count:,}")
        
        # 计算成功率
        total_attempts = stats['valid_nmea'] + stats['checksum_errors'] + stats['incomplete_lines']
        if total_attempts > 0:
            success_rate = (stats['valid_nmea'] / total_attempts) * 100
            print(f"\n✅ 解析成功率: {success_rate:.1f}%")
    
    def system_info(self):
        """显示系统信息"""
        print("ℹ️  RTK系统信息")
        print("=" * 50)
        print(f"串口: {self.config['serial']['port']} @ {self.config['serial']['baudrate']}")
        
        ntrip_config = self.config.get('ntrip', {})
        if ntrip_config.get('enabled', False):
            print(f"NTRIP: {ntrip_config['host']}:{ntrip_config['port']}/{ntrip_config['mountpoint']}")
        else:
            print("NTRIP: 未启用")
        
        print(f"坐标系: {self.config.get('positioning', {}).get('coordinate_system', 'WGS84')}")

def main():
    """主函数"""
    tools = RTKDebugTools()
    
    while True:
        print("\n🛠️  RTK调试工具集")
        print("=" * 30)
        print("1. 快速系统测试 (15秒)")
        print("2. NMEA数据分析 (30秒)")
        print("3. NMEA数据分析 (显示原始数据)")
        print("4. 原始数据监控 (10秒)")
        print("5. 系统信息")
        print("6. 退出")
        
        try:
            choice = input("\n请选择功能 (1-6): ").strip()
            
            if choice == '1':
                duration = input("测试时长(秒，默认15): ").strip()
                duration = int(duration) if duration else 15
                tools.quick_test(duration)
            
            elif choice == '2':
                duration = input("分析时长(秒，默认30): ").strip()
                duration = int(duration) if duration else 30
                tools.nmea_analysis(duration, show_raw=False)
            
            elif choice == '3':
                duration = input("分析时长(秒，默认30): ").strip()
                duration = int(duration) if duration else 30
                tools.nmea_analysis(duration, show_raw=True)
            
            elif choice == '4':
                duration = input("监控时长(秒，默认10): ").strip()
                duration = int(duration) if duration else 10
                tools.raw_data_monitor(duration)
            
            elif choice == '5':
                tools.system_info()
            
            elif choice == '6':
                print("👋 再见!")
                break
            
            else:
                print("❌ 无效选择，请重试")
        
        except KeyboardInterrupt:
            print("\n👋 再见!")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")

if __name__ == "__main__":
    main()