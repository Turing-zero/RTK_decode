# RTK定位系统

一个基于Python的RTK（Real-Time Kinematic）定位系统，支持NMEA、RTCM协议解析，串口通信和NTRIP客户端功能。

## 系统要求

- Python 3.7+
- Windows/Linux
- GPS接收机设备
- NTRIP差分数据服务

## 项目结构

```
RTK/
├── src/                    # 核心源代码
│   ├── __init__.py         # 包初始化文件
│   └── rtk_positioning.py  # RTK定位系统核心模块
├── tools/                  # 调试和工具脚本
│   └── debug_tools.py      # RTK系统调试工具
├── config.json             # 系统配置文件
├── test_rtk.py             # 测试脚本
├── requirements.txt        # Python依赖包列表
└── README.md               # 项目说明文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置系统

编辑 `config.json` 文件，配置串口和NTRIP参数：

```json
{
    "serial": {
        "port": "COM3",          // Windows: COM3, Linux: /dev/ttyUSB0
        "baudrate": 115200,
        "timeout": 1.0
    },
    "ntrip": {
        "host": "your-ntrip-server.com",
        "port": 2101,
        "mountpoint": "MOUNT_POINT",
        "username": "your_username",
        "password": "your_password"
    },
    "positioning": {
        "coordinate_system": "WGS84"
    }
}
```

### 3. 运行测试

```bash
# 测试NMEA解析
python test_rtk.py test-nmea

# 测试坐标转换
python test_rtk.py test-coord

# 测试NMEA消息过滤
python test_rtk.py test-filter

# 运行所有测试
python test_rtk.py test-all
```

### 4. 使用调试工具

```bash
python tools/debug_tools.py
```

## 编程接口

### 基本使用

```python
from rtk_positioning import RTKPositioningSystem

# 创建RTK系统（默认解析所有NMEA消息）
rtk_system = RTKPositioningSystem()

# 配置串口
rtk_system.configure_serial('COM3', 115200)

# 配置NTRIP
rtk_system.configure_ntrip(
    host='ntrip-server.com',
    port=2101,
    mountpoint='MOUNT_POINT',
    username='user',
    password='pass'
)

# 启动系统
if rtk_system.start():
    # 获取位置信息
    position = rtk_system.get_position()
    print(f"位置: {position.latitude}, {position.longitude}")
    print(f"定位质量: {position.fix_quality.name}")

# 停止系统
rtk_system.stop()
```

### NMEA消息选择性解析

```python
# 只解析GGA消息（位置信息）
rtk_gga_only = RTKPositioningSystem(enabled_nmea_messages=['GGA'])

# 只解析RMC消息（导航信息）
rtk_rmc_only = RTKPositioningSystem(enabled_nmea_messages=['RMC'])

# 解析指定的多种消息类型
rtk_custom = RTKPositioningSystem(enabled_nmea_messages=['GGA', 'RMC'])

# 动态切换消息类型
rtk_system.set_nmea_message_filter(['GGA'])  # 切换到只解析GGA

# 查看当前配置
enabled = rtk_system.get_enabled_nmea_messages()
supported = rtk_system.get_supported_nmea_messages()
print(f"支持的消息类型: {supported}")
print(f"当前启用的消息类型: {enabled}")
```

### Position位置信息

系统返回的位置信息包含以下字段：

```python
@dataclass
class Position:
    """GPS位置信息"""
    latitude: float = 0.0          # 纬度（度）
    longitude: float = 0.0         # 经度（度）
    altitude: float = 0.0          # 海拔高度（米）
    fix_quality: FixQuality = FixQuality.INVALID  # 定位质量
    satellites_used: int = 0       # 使用的卫星数量
    hdop: float = 0.0             # 水平精度因子
    timestamp: datetime = None     # 时间戳
    speed: float = 0.0            # 速度（km/h）
    course: float = 0.0           # 航向角（度，0-360）
```

#### 字段说明

- **latitude**: 纬度，正值表示北纬，负值表示南纬
- **longitude**: 经度，正值表示东经，负值表示西经  
- **altitude**: 海拔高度，单位为米，相对于WGS84椭球面
- **fix_quality**: 定位质量枚举值
  - **INVALID**: 无效定位
  - **GPS_FIX**: 标准GPS定位
  - **DGPS_FIX**: 差分GPS定位
  - **RTK_FIXED**: RTK固定解（厘米级精度）
  - **RTK_FLOAT**: RTK浮点解（分米级精度）
  - **ESTIMATED**: 估算（航位推算）
- **satellites_used**: 参与定位计算的卫星数量，数量越多精度越高
- **hdop**: 水平精度稀释因子，值越小精度越高（<2为优秀，2-5为良好，>5为较差）
- **timestamp**: GPS时间戳，UTC时间
- **speed**: 地面速度，单位为km/h
- **course**: 航向角，以正北为0度，顺时针方向0-360度

#### 使用示例

```python
position = rtk_system.get_position()

# 检查定位状态
if position.fix_quality != FixQuality.INVALID:
    print(f"当前位置: {position.latitude:.6f}°, {position.longitude:.6f}°")
    print(f"海拔: {position.altitude:.1f}m")
    print(f"精度: HDOP={position.hdop:.1f}, 卫星数={position.satellites_used}")
    
    # RTK高精度定位
    if position.fix_quality == FixQuality.RTK_FIXED:
        print("✓ RTK固定解 - 厘米级精度")
    elif position.fix_quality == FixQuality.RTK_FLOAT:
        print("⚠ RTK浮点解 - 分米级精度")
    
    # 运动信息
    if position.speed > 0:
        print(f"速度: {position.speed:.1f} km/h, 航向: {position.course:.1f}°")
else:
    print("❌ 无有效定位信号")
```

### 支持的协议

#### NMEA消息

- **GGA**: 全球定位系统定位数据
- **RMC**: 推荐最小定位信息

#### RTCM消息

- **1005**: 基站坐标信息
- **1077**: GPS MSM7观测数据
- 其他标准RTCM 3.x消息

## 故障排除

### 串口连接问题
- 检查串口号是否正确
- 确认波特率设置匹配GPS设备
- 检查串口权限（Linux需要用户在dialout组）

### NTRIP连接问题
- 验证服务器地址和端口
- 检查用户名和密码
- 确认挂载点名称正确

### 定位精度问题
- 确保GPS设备支持RTK功能
- 检查NTRIP数据流是否正常
- 验证基站距离（建议<20km）