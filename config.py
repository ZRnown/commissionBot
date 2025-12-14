import os
import logging
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

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

# 通过角色ID配置三个等级（逗号分隔，支持多个角色ID）
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

# 新成员通知频道配置
NOTIFICATION_CHANNEL_ID = os.getenv('NOTIFICATION_CHANNEL_ID')
if NOTIFICATION_CHANNEL_ID is None:
    logging.error("NOTIFICATION_CHANNEL_ID is not set in the .env file.")
    raise ValueError("NOTIFICATION_CHANNEL_ID must be set in the .env file.")
NOTIFICATION_CHANNEL_ID = int(NOTIFICATION_CHANNEL_ID.strip())

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
