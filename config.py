import os
import logging
import json
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any

# 加载 .env 文件中的变量（务必在读取任何环境变量之前调用）
load_dotenv()

# 开关：是否允许普通会员拥有邀请资格，以及普通会员邀请的佣金比例（仅在允许时使用）
ALLOW_BASIC_INVITER = os.getenv('ALLOW_BASIC_INVITER', 'true').lower() in ('1', 'true', 'yes')
BASIC_INVITE_COMMISSION = float(os.getenv('BASIC_INVITE_COMMISSION', '0'))

# 获取 Discord Token 和数据库路径
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_PATH = os.getenv('DATABASE_PATH')

# 佣金比例（基于名称关键字识别到的目标角色）
MONTHLY_FEE_COMMISSION = int(os.getenv('MONTHLY_FEE_COMMISSION', 20))  # 月费会员佣金
ANNUAL_FEE_COMMISSION = int(os.getenv('ANNUAL_FEE_COMMISSION', 40))  # 年费会员佣金
PARTNER_COMMISSION = int(os.getenv('PARTNER_COMMISSION', 70))  # 合伙人佣金

# 新增价格环境变量
MONTHLY_FEE_PRICE = float(os.getenv('MONTHLY_FEE_PRICE', '0'))
ANNUAL_FEE_PRICE = float(os.getenv('ANNUAL_FEE_PRICE', '0'))
PARTNER_FEE_PRICE = float(os.getenv('PARTNER_FEE_PRICE', '0'))  # 合伙人价格

# ===== 等级配置系统 =====

# 等级配置数据结构
class LevelConfig:
    def __init__(self, name: str, tier: int, role_ids: List[int], commission: int, price: float):
        self.name = name
        self.tier = tier
        self.role_ids = role_ids
        self.commission = commission
        self.price = price

# 解析等级配置
def parse_levels_config(config_str: str) -> List[LevelConfig]:
    """解析等级配置JSON字符串"""
    if not config_str or not config_str.strip():
        return []

    try:
        levels_data = json.loads(config_str)
        levels = []
        for level_data in levels_data:
            role_ids_str = level_data.get('role_ids', '')
            if isinstance(role_ids_str, str):
                role_ids = [int(x.strip()) for x in role_ids_str.split(',') if x.strip()]
            elif isinstance(role_ids_str, list):
                role_ids = [int(x) for x in role_ids_str]
            else:
                role_ids = []

            level = LevelConfig(
                name=level_data['name'],
                tier=int(level_data['tier']),
                role_ids=role_ids,
                commission=int(level_data['commission']),
                price=float(level_data['price'])
            )
            levels.append(level)

        # 按tier排序
        levels.sort(key=lambda x: x.tier)
        return levels
    except Exception as e:
        logging.error(f"Failed to parse LEVELS_CONFIG: {e}")
        return []

# 新版等级配置（支持任意数量的等级）
LEVELS_CONFIG_STR = os.getenv('LEVELS_CONFIG', '').strip()
LEVELS_CONFIG: List[LevelConfig] = parse_levels_config(LEVELS_CONFIG_STR)

# 向后兼容：旧版三个等级配置
MONTHLY_FEE_ROLE_IDS = os.getenv('MONTHLY_FEE_ROLE_IDS', '').strip()
MONTHLY_FEE_ROLE_ID_SET: set[int] = set()
if MONTHLY_FEE_ROLE_IDS:
    try:
        MONTHLY_FEE_ROLE_ID_SET = {int(x.strip()) for x in MONTHLY_FEE_ROLE_IDS.split(',') if x.strip()}
        logging.info(f"Monthly fee role IDs: {MONTHLY_FEE_ROLE_ID_SET}")
    except Exception:
        logging.warning("Invalid MONTHLY_FEE_ROLE_IDS format; expected comma-separated integers.")

ANNUAL_FEE_ROLE_IDS = os.getenv('ANNUAL_FEE_ROLE_IDS', '').strip()
ANNUAL_FEE_ROLE_ID_SET: set[int] = set()
if ANNUAL_FEE_ROLE_IDS:
    try:
        ANNUAL_FEE_ROLE_ID_SET = {int(x.strip()) for x in ANNUAL_FEE_ROLE_IDS.split(',') if x.strip()}
        logging.info(f"Annual fee role IDs: {ANNUAL_FEE_ROLE_ID_SET}")
    except Exception:
        logging.warning("Invalid ANNUAL_FEE_ROLE_IDS format; expected comma-separated integers.")

PARTNER_ROLE_IDS = os.getenv('PARTNER_ROLE_IDS', '').strip()
PARTNER_ROLE_ID_SET: set[int] = set()
if PARTNER_ROLE_IDS:
    try:
        PARTNER_ROLE_ID_SET = {int(x.strip()) for x in PARTNER_ROLE_IDS.split(',') if x.strip()}
        logging.info(f"Partner role IDs: {PARTNER_ROLE_ID_SET}")
    except Exception:
        logging.warning("Invalid PARTNER_ROLE_IDS format; expected comma-separated integers.")

# 如果新版配置存在，使用新版；否则使用旧版配置
if LEVELS_CONFIG:
    logging.info(f"Using new level configuration with {len(LEVELS_CONFIG)} levels:")
    for level in LEVELS_CONFIG:
        logging.info(f"  Level {level.tier}: {level.name} (commission: {level.commission}%, price: {level.price}, roles: {level.role_ids})")
else:
    # 使用旧版配置，转换为新格式
    logging.info("Using legacy 3-level configuration")
    LEVELS_CONFIG = []
    if MONTHLY_FEE_ROLE_ID_SET:
        LEVELS_CONFIG.append(LevelConfig("月费会员", 1, list(MONTHLY_FEE_ROLE_ID_SET), MONTHLY_FEE_COMMISSION, MONTHLY_FEE_PRICE))
    if ANNUAL_FEE_ROLE_ID_SET:
        LEVELS_CONFIG.append(LevelConfig("年费会员", 2, list(ANNUAL_FEE_ROLE_ID_SET), ANNUAL_FEE_COMMISSION, ANNUAL_FEE_PRICE))
    if PARTNER_ROLE_ID_SET:
        LEVELS_CONFIG.append(LevelConfig("合伙人", 3, list(PARTNER_ROLE_ID_SET), PARTNER_COMMISSION, PARTNER_FEE_PRICE))

# 创建角色ID到等级的映射
ROLE_TO_LEVEL_MAP: Dict[int, LevelConfig] = {}
for level in LEVELS_CONFIG:
    for role_id in level.role_ids:
        ROLE_TO_LEVEL_MAP[role_id] = level

# 创建所有付费角色ID集合
ALL_PAID_ROLE_ID_SET: set[int] = set()
for level in LEVELS_CONFIG:
    ALL_PAID_ROLE_ID_SET.update(level.role_ids)

# 读取 ALLOWED_CHANNEL_ID，确保它不是 None
ALLOWED_CHANNEL_IDS = os.getenv('ALLOWED_CHANNEL_ID')

# 如果 ALLOWED_CHANNEL_IDS 为 None，打印错误并终止程序
if ALLOWED_CHANNEL_IDS is None:
    logging.error("ALLOWED_CHANNEL_ID is not set in the .env file.")
    raise ValueError("ALLOWED_CHANNEL_ID must be set in the .env file.")

# 将 ALLOWED_CHANNEL_ID 字符串分割并转换为整型列表
ALLOWED_CHANNEL_IDS = [int(id.strip()) for id in ALLOWED_CHANNEL_IDS.split(',')]
logging.info(f"Allowed Channel IDs: {ALLOWED_CHANNEL_IDS}")  # 输出调试信息，检查频道 ID 是否正确

# 指定用于创建邀请链接的频道（可选）
INVITE_CHANNEL_ID = int(os.getenv('INVITE_CHANNEL_ID', '0')) or None

# 新成员通知频道配置（邀请提醒，向后兼容）
NOTIFICATION_CHANNEL_ID = os.getenv('NOTIFICATION_CHANNEL_ID')
if NOTIFICATION_CHANNEL_ID is None:
    logging.error("NOTIFICATION_CHANNEL_ID is not set in the .env file.")
    raise ValueError("NOTIFICATION_CHANNEL_ID must be set in the .env file.")
NOTIFICATION_CHANNEL_ID = int(NOTIFICATION_CHANNEL_ID.strip())

# 邀请通知频道（新成员加入提醒）
INVITE_NOTIFICATION_CHANNEL_ID = os.getenv('INVITE_NOTIFICATION_CHANNEL_ID')
if INVITE_NOTIFICATION_CHANNEL_ID:
    INVITE_NOTIFICATION_CHANNEL_ID = int(INVITE_NOTIFICATION_CHANNEL_ID.strip())
else:
    # 如果未配置，使用旧的 NOTIFICATION_CHANNEL_ID 作为默认值（向后兼容）
    INVITE_NOTIFICATION_CHANNEL_ID = NOTIFICATION_CHANNEL_ID
    logging.info(f"INVITE_NOTIFICATION_CHANNEL_ID not set, using NOTIFICATION_CHANNEL_ID: {INVITE_NOTIFICATION_CHANNEL_ID}")

# 佣金通知频道（佣金奖励提醒）
COMMISSION_NOTIFICATION_CHANNEL_ID = os.getenv('COMMISSION_NOTIFICATION_CHANNEL_ID')
if COMMISSION_NOTIFICATION_CHANNEL_ID:
    COMMISSION_NOTIFICATION_CHANNEL_ID = int(COMMISSION_NOTIFICATION_CHANNEL_ID.strip())
else:
    # 如果未配置，使用旧的 NOTIFICATION_CHANNEL_ID 作为默认值（向后兼容）
    COMMISSION_NOTIFICATION_CHANNEL_ID = NOTIFICATION_CHANNEL_ID
    logging.info(f"COMMISSION_NOTIFICATION_CHANNEL_ID not set, using NOTIFICATION_CHANNEL_ID: {COMMISSION_NOTIFICATION_CHANNEL_ID}")

# 公告中使用的服务器名称
GUILD_DISPLAY_NAME = os.getenv('GUILD_DISPLAY_NAME', '')

# 代理配置（可选）
PROXY_URL = os.getenv('PROXY_URL')

# 日志配置（可通过环境变量控制）
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FILE = os.getenv('LOG_FILE', 'logs/bot.log')
LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(1 * 1024 * 1024)))  # 1MB
LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '5'))
LOG_TO_CONSOLE = os.getenv('LOG_TO_CONSOLE', 'true').lower() in ('1', 'true', 'yes')

# 确保日志目录存在
log_dir = os.path.dirname(LOG_FILE)
if log_dir:
    os.makedirs(log_dir, exist_ok=True)

# 构建日志器
root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# 清空可能已有的处理器（避免重复添加）
for h in list(root_logger.handlers):
    root_logger.removeHandler(h)

fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
file_handler.setFormatter(fmt)
root_logger.addHandler(file_handler)

if LOG_TO_CONSOLE:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root_logger.addHandler(console_handler)

# 降低第三方库日志噪声
logging.getLogger('discord').setLevel(logging.INFO)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.INFO)
logging.getLogger('aiohttp').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)

# Slash 指令白名单（逗号分隔的用户ID）。为空则不启用白名单限制。
SLASH_ALLOWED_USER_IDS = os.getenv('SLASH_ALLOWED_USER_IDS', '').strip()
SLASH_ALLOWED_USER_ID_SET: set[int] = set()
if SLASH_ALLOWED_USER_IDS:
    try:
        SLASH_ALLOWED_USER_ID_SET = {int(x.strip()) for x in SLASH_ALLOWED_USER_IDS.split(',') if x.strip()}
    except Exception:
        logging.warning("Invalid SLASH_ALLOWED_USER_IDS format; expected comma-separated integers.")
