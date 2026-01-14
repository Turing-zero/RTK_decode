
import time
import logging
import threading
import sys
import os
from typing import List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rtk_positioning import RTKPositioningSystem, SerialCommunicator

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LinkVerifier")

class MockSerialCommunicator:
    """Mock serial communicator to capture output data"""
    def __init__(self):
        self.received_data = bytearray()
        self.is_connected = False
        self.lock = threading.Lock()
        
    def connect(self):
        self.is_connected = True
        return True
        
    def disconnect(self):
        self.is_connected = False
        
    def send_data(self, data: bytes):
        """Capture data sent to serial port"""
        with self.lock:
            self.received_data.extend(data)
            
    def get_received_data(self) -> bytes:
        with self.lock:
            return bytes(self.received_data)
            
    def clear_buffer(self):
        with self.lock:
            self.received_data = bytearray()

def verify_link():
    print("=" * 60)
    print("开始验证 NTRIP -> 串口 数据传输链路完整性")
    print("=" * 60)

    # 1. Initialize System
    rtk = RTKPositioningSystem()
    
    # 2. Inject Mock Serial
    mock_serial = MockSerialCommunicator()
    rtk.serial_comm = mock_serial
    # Manually set connected status as if start() was called for serial
    mock_serial.connect() 
    
    print("[1] 环境初始化完成")

    # 3. Define Test Cases
    test_cases = [
        {
            "name": "完整单包传输",
            "chunks": [b'\xd3\x00\x04\x01\x02\x03\x04\x12\x34\x56'], # A valid-looking RTCM packet
            "desc": "发送一个完整的RTCM包"
        },
        {
            "name": "分包传输 (Fragmentation)",
            "chunks": [b'\xd3\x00\x04\xAA', b'\xBB\xCC\xDD\xEE\xFF\x99'], # Split in middle
            "desc": "模拟网络分包：先发送头部和部分数据，再发送剩余数据"
        },
        {
            "name": "多包粘连 (Coalescence)",
            "chunks": [b'\xd3\x00\x04\x11\x11\x11\x11\xAA\xAA\xAA' + b'\xd3\x00\x04\x22\x22\x22\x22\xBB\xBB\xBB'],
            "desc": "模拟TCP粘包：一次性收到两个RTCM包"
        },
        {
            "name": "非RTCM垃圾数据",
            "chunks": [b'Not RTCM Data', b' garbage \n'],
            "desc": "发送非RTCM格式的干扰数据"
        }
    ]

    total_passed = 0
    
    for i, case in enumerate(test_cases):
        print(f"\n测试用例 {i+1}: {case['name']}")
        print(f"描述: {case['desc']}")
        
        # Clear buffer
        mock_serial.clear_buffer()
        
        # Calculate expected total data
        expected_data = b"".join(case['chunks'])
        
        # Simulate data arrival
        for chunk in case['chunks']:
            # Simulate calling the callback directly (bypassing socket layer for unit testing logic)
            # This tests the _on_ntrip_data logic specifically
            rtk._on_ntrip_data(chunk)
            
        # Verify
        received = mock_serial.get_received_data()
        
        print(f"发送数据量: {len(expected_data)} bytes")
        print(f"接收数据量: {len(received)} bytes")
        
        if received == expected_data:
            print("✅ 验证通过: 数据完全一致")
            total_passed += 1
        else:
            print("❌ 验证失败: 数据不一致")
            print(f"期望: {expected_data.hex().upper()}")
            print(f"实际: {received.hex().upper()}")
            
    print("\n" + "=" * 60)
    print(f"测试总结: {total_passed}/{len(test_cases)} 通过")
    
    if total_passed == len(test_cases):
        print("结论: 数据传输链路完整，分包/粘包/非标准数据均能正确透传。")
    else:
        print("结论: 存在数据丢失或损坏风险！")
    print("=" * 60)

if __name__ == "__main__":
    verify_link()
