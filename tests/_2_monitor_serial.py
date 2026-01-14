#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串口原始数据监控脚本
用于检查GPS接收机是否有数据输出，以及波特率是否正确
"""

import sys
import os
import serial
import serial.tools.list_ports
import time

def list_ports():
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def monitor(port, baudrate=115200):
    print(f"正在打开串口 {port} (波特率: {baudrate})...")
    print("按 Ctrl+C 退出")
    print("-" * 50)
    
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        
        while True:
            if ser.in_waiting:
                try:
                    # Try to read a line
                    line = ser.readline()
                    
                    # Try to decode as ASCII/UTF-8
                    try:
                        decoded = line.decode('utf-8', errors='replace').strip()
                        print(f"[{time.strftime('%H:%M:%S')}] {decoded}")
                        
                        # Simple heuristic for baud rate check
                        if len(decoded) > 5 and all(c == '\x00' or c == '' for c in decoded):
                             print("⚠️  警告: 收到大量乱码，可能是波特率设置错误！")
                             
                    except Exception:
                        print(f"[{time.strftime('%H:%M:%S')}] RAW: {line}")
                        
                except Exception as e:
                    print(f"读取错误: {e}")
            else:
                time.sleep(0.01)
                
    except serial.SerialException as e:
        print(f"❌ 串口错误: {e}")
    except KeyboardInterrupt:
        print("\n已停止监控")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    ports = list_ports()
    if not ports:
        print("未找到串口设备")
        sys.exit(1)
        
    target_port = ports[0]
    target_baud = 115200
    
    # Simple CLI args
    if len(sys.argv) > 1:
        target_port = sys.argv[1]
    if len(sys.argv) > 2:
        target_baud = int(sys.argv[2])
        
    if target_port not in ports:
        print(f"警告: 端口 {target_port} 不在检测列表中: {ports}")
        
    monitor(target_port, target_baud)
