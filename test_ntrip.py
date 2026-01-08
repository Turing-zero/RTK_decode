#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NTRIP功能测试脚本
用于单独测试NTRIP客户端连接和数据接收
"""

import sys
import os
import time
import json
import logging
import threading

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.rtk_positioning import NTRIPClient, MockNTRIPClient, SerialCommunicator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NTRIP_TEST")

class NTRIPTester:
    def __init__(self, config_file='config.json'):
        self.config = self._load_config(config_file)
        self.client = None
        self.serial = None
        self.received_bytes = 0
        self.received_packages = 0
        self.start_time = 0
        self.last_data_time = 0
        
    def _load_config(self, config_file):
        """加载配置文件"""
        if not os.path.exists(config_file):
            logger.warning(f"配置文件 {config_file} 不存在，将使用默认/空配置")
            return {}
            
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return {}

    def _setup_serial(self):
        """设置串口"""
        serial_config = self.config.get('serial', {})
        if not serial_config:
            logger.warning("未配置串口，将只测试NTRIP接收，不转发数据")
            return False
            
        try:
            self.serial = SerialCommunicator(
                port=serial_config.get('port'),
                baudrate=serial_config.get('baudrate', 115200)
            )
            if self.serial.connect():
                logger.info(f"串口连接成功: {serial_config.get('port')}")
                return True
            else:
                logger.error("串口连接失败")
                return False
        except Exception as e:
            logger.error(f"串口设置失败: {e}")
            return False

    def on_data_received(self, data: bytes):
        """数据接收回调"""
        self.received_bytes += len(data)
        self.received_packages += 1
        self.last_data_time = time.time()
        
        # 转发到串口
        if self.serial and self.serial.is_connected:
            self.serial.send_data(data)
            
        # 打印少量数据用于调试 (前16字节)
        hex_data = " ".join([f"{b:02X}" for b in data[:16]])
        if len(data) > 16:
            hex_data += "..."
        # logger.debug(f"收到数据: {len(data)} bytes | {hex_data}")
        # 每接收10个包打印一次，避免刷屏
        if self.received_packages % 10 == 0:
             print(f"\r已接收: {self.received_packages} 包, {self.received_bytes} 字节...", end="", flush=True)

    def run_test(self, duration=10, force_real=False):
        """运行测试"""
        ntrip_config = self.config.get('ntrip', {})
        
        if not ntrip_config:
            logger.error("配置文件中缺少 'ntrip' 配置项")
            return

        # 先连接串口
        self._setup_serial()

        host = ntrip_config.get('host')
        port = ntrip_config.get('port')
        mountpoint = ntrip_config.get('mountpoint')
        username = ntrip_config.get('username', '')
        password = ntrip_config.get('password', '')
        
        # 检查是否使用模拟模式
        use_mock = ntrip_config.get('mock', False)
        if force_real:
            use_mock = False
            logger.info("强制使用真实连接模式")
            
        logger.info("=" * 50)
        logger.info("NTRIP 测试开始")
        logger.info(f"服务器: {host}:{port}")
        logger.info(f"挂载点: {mountpoint}")
        logger.info(f"用户: {username}")
        logger.info(f"模式: {'模拟 (Mock)' if use_mock else '真实连接'}")
        logger.info("=" * 50)

        if use_mock:
            self.client = MockNTRIPClient(host, port, mountpoint, username, password)
        else:
            self.client = NTRIPClient(host, port, mountpoint, username, password)
            
        # 注册回调
        self.client.add_data_callback(self.on_data_received)
        
        # 连接
        logger.info("正在连接...")
        if not self.client.connect():
            logger.error("连接失败!")
            return

        logger.info("连接成功! 开始接收数据...")
        
        # 发送GGA数据 (很多NTRIP服务器需要先收到GGA才发送数据)
        if not use_mock:
            # 使用一个示例GGA (北京坐标)
            gga = "$GPGGA,065957.00,3013.3614985,N,12021.3076056,E,1,26,0.8,7.7131,M,7.953,M,,*67"
            logger.info(f"发送GGA数据: {gga}")
            self.client.send_gga(gga)
            
        self.start_time = time.time()
        
        try:
            # 运行指定时长
            end_time = self.start_time + duration
            while time.time() < end_time:
                remaining = int(end_time - time.time())
                # logger.info(f"测试进行中... 剩余 {remaining} 秒")
                time.sleep(1)
                
                # 检查连接状态
                if not self.client.is_connected:
                    logger.error("连接意外断开!")
                    break
                    
        except KeyboardInterrupt:
            logger.info("\n测试被用户中断")
        finally:
            print("") # 换行
            self.client.disconnect()
            if self.serial:
                self.serial.disconnect()
            self._print_stats()

    def _print_stats(self):
        """打印统计信息"""
        duration = time.time() - self.start_time
        logger.info("-" * 50)
        logger.info("测试结果统计:")
        logger.info(f"持续时间: {duration:.2f} 秒")
        logger.info(f"接收数据包: {self.received_packages}")
        logger.info(f"接收总字节: {self.received_bytes}")
        if duration > 0:
            logger.info(f"平均速率: {self.received_bytes/duration:.2f} bytes/sec")
        
        if self.received_packages > 0:
            logger.info("✅ NTRIP数据接收正常")
        else:
            logger.warning("⚠️  未收到任何数据")
        logger.info("-" * 50)

if __name__ == "__main__":
    tester = NTRIPTester()
    
    # 简单的参数处理
    duration = 10
    force_real = False
    
    if len(sys.argv) > 1:
        if sys.argv[1].isdigit():
            duration = int(sys.argv[1])
        elif sys.argv[1] == '--real':
            force_real = True
            
    if len(sys.argv) > 2:
        if sys.argv[2] == '--real':
            force_real = True
            
    tester.run_test(duration, force_real)
