#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境检查脚本
用于户外测试前快速检查硬件和网络状态
"""

import sys
import os
import time
import socket
import shutil
import serial.tools.list_ports
import platform
import subprocess

def check_serial_ports():
    print("\n[1] 检查串口设备...")
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("❌ 未发现任何串口设备!")
        return False
    
    print(f"发现 {len(ports)} 个串口设备:")
    for port in ports:
        print(f"  - {port.device}: {port.description} [{port.hwid}]")
    return True

def check_internet():
    print("\n[2] 检查网络连接...")
    
    # Check DNS/Ping
    host = "8.8.8.8"
    print(f"  正在 Ping {host} ...")
    
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '1', host]
    
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            print("  ✅ 互联网连接正常 (Ping成功)")
        else:
            print("  ❌ 互联网连接失败 (Ping超时)")
            return False
    except Exception as e:
        print(f"  ❌ 执行Ping命令失败: {e}")
        return False
        
    # Check DNS resolution
    try:
        socket.gethostbyname("www.google.com")
        print("  ✅ DNS解析正常")
    except:
        print("  ⚠️ DNS解析失败 (可能无法连接域名)")
        
    return True

def check_disk_space():
    print("\n[3] 检查磁盘空间...")
    try:
        # Get current directory drive
        current_drive = os.path.abspath(__file__)[:3] if platform.system() == 'Windows' else '/'
        total, used, free = shutil.disk_usage(current_drive)
        
        free_gb = free // (2**30)
        print(f"  当前磁盘可用空间: {free_gb} GB")
        
        if free_gb < 1:
            print("  ❌ 磁盘空间不足 (<1GB)!")
            return False
        else:
            print("  ✅ 磁盘空间充足")
            return True
    except Exception as e:
        print(f"  检查磁盘失败: {e}")
        return False

def main():
    print("=" * 50)
    print("RTK系统 户外环境自检程序")
    print("=" * 50)
    
    status = True
    
    if not check_serial_ports(): status = False
    if not check_internet(): status = False
    if not check_disk_space(): status = False
    
    print("\n" + "=" * 50)
    if status:
        print("✅ 所有检查通过，系统准备就绪")
    else:
        print("❌ 存在环境问题，请检查上述错误")
    print("=" * 50)

if __name__ == "__main__":
    main()
