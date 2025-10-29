#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTK定位系统使用示例
"""

import json
import time
import logging
import sys
import os

from src.rtk_positioning import RTKPositioningSystem, FixQuality

def load_config(config_file: str = 'config.json') -> dict:
    """加载配置文件"""
    # 如果是相对路径，则相对于项目根目录
    if not os.path.isabs(config_file):
        project_root = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(project_root, config_file)
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"配置文件 {config_file} 不存在，使用默认配置")
        return {
            "serial": {"port": "COM3", "baudrate": 115200, "timeout": 1.0},
            "ntrip": {
                "host": "your-ntrip-server.com",
                "port": 2101,
                "mountpoint": "MOUNT_POINT",
                "username": "",
                "password": ""
            }
        }

def setup_logging(config: dict):
    """设置日志"""
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO'))
    format_str = log_config.get('format', '%(asctime)s - %(levelname)s - %(message)s')
    
    # 清除现有的处理器
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_config.get('file', 'rtk_positioning.log'), encoding='utf-8')
        ],
        force=True
    )

def test_nmea_parsing():
    """测试NMEA解析功能"""
    from src.rtk_positioning import NMEAParser
    
    print("测试NMEA解析功能")
    print("-" * 30)
    
    parser = NMEAParser()
    
    # 测试GGA消息
    gga_sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    position = parser.parse_sentence(gga_sentence)
    
    if position:
        print(f"GGA解析结果:")
        print(f"  纬度: {position.latitude:.6f}°")
        print(f"  经度: {position.longitude:.6f}°")
        print(f"  海拔: {position.altitude:.1f}m")
        print(f"  定位质量: {position.fix_quality.name}")
        print(f"  卫星数: {position.satellites_used}")
        print(f"  HDOP: {position.hdop}")
    
    # 测试RMC消息
    rmc_sentence = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    position = parser.parse_sentence(rmc_sentence)
    
    if position:
        print(f"\nRMC解析结果:")
        print(f"  纬度: {position.latitude:.6f}°")
        print(f"  经度: {position.longitude:.6f}°")
        print(f"  速度: {position.speed:.1f} km/h")
        print(f"  航向: {position.course:.1f}°")

def test_coordinate_conversion():
    """测试坐标转换功能"""
    from src.rtk_positioning import CoordinateConverter
    
    print("\n测试坐标转换功能")
    print("-" * 30)
    
    # WGS84坐标
    lat, lon = 39.9042, 116.4074  # 北京天安门
    print(f"WGS84坐标: {lat:.6f}°, {lon:.6f}°")
    
    # 转换为UTM
    x, y, zone, hemisphere = CoordinateConverter.wgs84_to_utm(lat, lon)
    print(f"UTM坐标: {x:.2f}, {y:.2f} (Zone: {zone}{hemisphere})")
    
    # 转换回WGS84
    lat2, lon2 = CoordinateConverter.utm_to_wgs84(x, y, zone, hemisphere)
    print(f"转换回WGS84: {lat2:.6f}°, {lon2:.6f}°")

def test_nmea_message_filtering():
    """测试NMEA消息过滤功能"""
    
    print("\nNMEA消息过滤测试")
    print("-" * 30)
    
    # 测试只解析GGA消息
    print("1. 创建只解析GGA消息的系统")
    rtk_gga_only = RTKPositioningSystem(enabled_nmea_messages=['GGA'])
    print(f"   启用的消息类型: {rtk_gga_only.get_enabled_nmea_messages()}")
    
    # 测试只解析RMC消息
    print("2. 创建只解析RMC消息的系统")
    rtk_rmc_only = RTKPositioningSystem(enabled_nmea_messages=['RMC'])
    print(f"   启用的消息类型: {rtk_rmc_only.get_enabled_nmea_messages()}")
    
    # 测试解析所有消息
    print("3. 创建解析所有消息的系统")
    rtk_all = RTKPositioningSystem(enabled_nmea_messages=['GGA', 'RMC'])
    print(f"   启用的消息类型: {rtk_all.get_enabled_nmea_messages()}")
    
    # 测试动态切换消息类型
    print("4. 动态切换消息类型")
    rtk_all.set_nmea_message_filter(['GGA'])
    print(f"   切换后启用的消息类型: {rtk_all.get_enabled_nmea_messages()}")
    
    print("✓ NMEA消息过滤功能测试完成")

def main():
    """主函数"""
    print("RTK定位系统示例程序")
    print("=" * 50)
    
    # 创建RTK定位系统 - 只解析GGA消息
    print("配置NMEA消息解析: 只解析GGA消息")
    rtk_system = RTKPositioningSystem(enabled_nmea_messages=['GGA'])
    
    # 配置串口
    serial_config = config['serial']
    rtk_system.configure_serial(
        port=serial_config['port'],
        baudrate=serial_config['baudrate']
    )
    print(f"串口配置: {serial_config['port']} @ {serial_config['baudrate']}")
    
    # 配置NTRIP
    ntrip_config = config['ntrip']
    rtk_system.configure_ntrip(
        host=ntrip_config['host'],
        port=ntrip_config['port'],
        mountpoint=ntrip_config['mountpoint'],
        username=ntrip_config.get('username', ''),
        password=ntrip_config.get('password', '')
    )
    print(f"NTRIP配置: {ntrip_config['host']}:{ntrip_config['port']}/{ntrip_config['mountpoint']}")
    
    try:
        # 启动系统
        print("\n正在启动RTK定位系统...")
        if rtk_system.start():
            print("✓ RTK定位系统启动成功")
            print("注意: 系统只会解析GGA消息，RMC消息将被忽略")
            print("\n实时定位信息:")
            print("-" * 80)
            
            # 主循环
            while True:
                time.sleep(1)
                position = rtk_system.get_position()
                
                # 显示信息
                current_time = time.strftime("%H:%M:%S")
                print(f"[{current_time}] ", end="")
                
                if position.fix_quality == FixQuality.INVALID:
                    print("等待GPS信号...")
                else:
                    # 位置信息
                    lat_str = f"{position.latitude:>12.8f}°"
                    lon_str = f"{position.longitude:>12.8f}°"
                    alt_str = f"{position.altitude:>8.2f}m"
                    
                    print(f"纬度:{lat_str} 经度:{lon_str} 海拔:{alt_str} "
                          f"质量:{position.fix_quality.name:>10} 卫星数:{position.satellites_used:>5} "
                          f"HDOP:{position.hdop:>5.2f}")
                    
                    # 速度和航向信息
                    if position.speed > 0:
                        print(f"        速度: {position.speed:>6.2f} km/h  航向: {position.course:>6.1f}°")
                
        else:
            print("✗ RTK定位系统启动失败")
            return
            
    except KeyboardInterrupt:
        print("\n\n收到停止信号，正在关闭系统...")
    except Exception as e:
        print(f"\n程序异常: {e}")
    finally:
        rtk_system.stop()
        print("RTK定位系统已停止")

if __name__ == "__main__":
    import sys
    # 加载配置
    config = load_config()
    setup_logging(config)

    if len(sys.argv) > 1:
        if sys.argv[1] == "test-nmea":
            test_nmea_parsing()
        elif sys.argv[1] == "test-coord":
            test_coordinate_conversion()
        elif sys.argv[1] == "test-filter":
            test_nmea_message_filtering()
        elif sys.argv[1] == "test-all":
            test_nmea_parsing()
            test_coordinate_conversion()
            test_nmea_message_filtering()
        else:
            print("可用的测试选项:")
            print("  test-nmea   - 测试NMEA解析")
            print("  test-coord  - 测试坐标转换")
            print("  test-filter - 测试NMEA消息过滤")
            print("  test-all    - 运行所有测试")
    else:
        main()