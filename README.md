# Discord 代理佣金系统 Bot

一个基于 Discord.py 的邀请代理佣金系统，支持多级会员等级、自动佣金计算和结算功能。

## 功能特性

- 🤝 邀请链接管理：自动生成和管理永久邀请链接
- 💰 自动佣金计算：根据邀请者等级和被邀请者升级自动计算佣金
- 📊 佣金统计：查看累计佣金、已结算、待结算金额
- 🎯 多级会员系统：支持月费、年费、合伙人三个等级
- 📜 详细记录：记录所有邀请和佣金事件
- 🔧 管理员工具：支持佣金结算和用户统计

## 环境要求

- Python 3.8 或更高版本
- Discord Bot Token
- Discord 服务器管理员权限（用于创建邀请链接）

## 安装步骤

### 1. 克隆或下载项目

```bash
cd /Users/wanghaixin/Development/DiscordBotWork/commissionBot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

或者使用虚拟环境（推荐）：

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
# macOS/Linux:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

## 配置说明

### 1. 创建 `.env` 文件

在项目根目录创建 `.env` 文件，配置以下环境变量：

```env
# ===== 必需配置 =====

# Discord Bot Token（从 Discord Developer Portal 获取）
DISCORD_TOKEN=your_bot_token_here

# 数据库路径
DATABASE_PATH=affiliate_system.db

# 允许使用的频道ID（逗号分隔，支持多个频道）
ALLOWED_CHANNEL_ID=123456789,987654321

# 通知频道配置
# 新成员通知频道ID（必需，用于向后兼容）
NOTIFICATION_CHANNEL_ID=123456789

# 邀请通知频道ID（可选，新成员加入提醒，不设置则使用 NOTIFICATION_CHANNEL_ID）
INVITE_NOTIFICATION_CHANNEL_ID=123456789

# 佣金通知频道ID（可选，佣金奖励提醒，不设置则使用 NOTIFICATION_CHANNEL_ID）
COMMISSION_NOTIFICATION_CHANNEL_ID=987654321

# ===== 等级配置（新版，支持任意数量的等级）=====
# JSON格式配置，支持3个、4个或更多等级
# 直接将JSON字符串放在环境变量中，支持单行或多行格式

# 三个等级配置示例（推荐单行格式）：
LEVELS_CONFIG=[{"name": "月费会员", "tier": 1, "role_ids": "111111111,222222222", "commission": 20, "price": 100.0}, {"name": "年费会员", "tier": 2, "role_ids": "333333333", "commission": 40, "price": 1000.0}, {"name": "合伙人", "tier": 3, "role_ids": "444444444", "commission": 70, "price": 5000.0}]

# 四个等级配置示例（推荐单行格式）：
LEVELS_CONFIG=[{"name": "月费会员", "tier": 1, "role_ids": "111111111,222222222", "commission": 20, "price": 100.0}, {"name": "年费会员", "tier": 2, "role_ids": "333333333", "commission": 40, "price": 1000.0}, {"name": "合伙人", "tier": 3, "role_ids": "444444444", "commission": 70, "price": 5000.0}, {"name": "钻石合伙人", "tier": 4, "role_ids": "555555555", "commission": 80, "price": 10000.0}]

# 多行格式示例（可读性更好，但.env文件可能不支持）：
# LEVELS_CONFIG=[
#   {"name": "月费会员", "tier": 1, "role_ids": "111111111,222222222", "commission": 20, "price": 100.0},
#   {"name": "年费会员", "tier": 2, "role_ids": "333333333", "commission": 40, "price": 1000.0},
#   {"name": "合伙人", "tier": 3, "role_ids": "444444444", "commission": 70, "price": 5000.0},
#   {"name": "钻石合伙人", "tier": 4, "role_ids": "555555555", "commission": 80, "price": 10000.0}
# ]

# ===== 向后兼容：旧版三个等级配置（可选）=====
# 如果不使用LEVELS_CONFIG，可以使用以下旧版配置
MONTHLY_FEE_ROLE_IDS=111111111,222222222
ANNUAL_FEE_ROLE_IDS=333333333
PARTNER_ROLE_IDS=444444444

# ===== 佣金比例配置（新版在LEVELS_CONFIG中配置）=====
# 如果使用LEVELS_CONFIG，则佣金比例和价格在上面配置
# 普通会员佣金比例（如果允许普通会员邀请）
BASIC_INVITE_COMMISSION=0

# ===== 向后兼容：旧版佣金和价格配置 =====
# 如果不使用LEVELS_CONFIG，使用以下配置
MONTHLY_FEE_COMMISSION=20
ANNUAL_FEE_COMMISSION=40
PARTNER_COMMISSION=70
MONTHLY_FEE_PRICE=100
ANNUAL_FEE_PRICE=1000
PARTNER_FEE_PRICE=5000

# ===== 可选配置 =====
# 是否允许普通会员邀请（true/false）
ALLOW_BASIC_INVITER=false

# 用于创建邀请链接的频道ID（可选，不设置则使用第一个允许的频道）
INVITE_CHANNEL_ID=123456789

# 服务器显示名称（用于通知消息）
GUILD_DISPLAY_NAME=我的服务器

# 代理URL（可选，如果需要代理访问 Discord）
# PROXY_URL=http://proxy.example.com:8080

# Slash 指令白名单（逗号分隔的用户ID，留空则不限制）
# SLASH_ALLOWED_USER_IDS=123456789,987654321

# 日志配置（可选）
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
LOG_TO_CONSOLE=true
```

### 2. 获取 Discord Bot Token

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)
2. 创建新应用或选择现有应用
3. 进入 "Bot" 页面
4. 点击 "Reset Token" 或 "Copy" 获取 Token
5. 将 Token 填入 `.env` 文件的 `DISCORD_TOKEN`

### 3. 获取角色 ID 和频道 ID

在 Discord 中启用开发者模式：

1. 打开 Discord 设置 → 高级 → 启用开发者模式
2. 右键点击角色或频道 → 复制 ID

### 4. 邀请 Bot 到服务器

1. 在 Discord Developer Portal 的 "OAuth2" → "URL Generator" 中：
   - 勾选 `bot` 权限
   - 勾选以下权限：
     - `Manage Server`（管理服务器）
     - `Create Instant Invite`（创建邀请）
     - `Manage Invites`（管理邀请）
     - `View Channels`（查看频道）
     - `Send Messages`（发送消息）
     - `Embed Links`（嵌入链接）
     - `Read Message History`（读取消息历史）
2. 复制生成的 URL，在浏览器中打开并授权

## 运行程序

### 方式一：直接运行

```bash
python main.py
```

### 方式二：使用 Python 模块方式

```bash
python -m main
```

### 方式三：后台运行（Linux/macOS）

```bash
# 使用 nohup
nohup python main.py > bot_output.log 2>&1 &

# 或使用 screen
screen -S discord_bot
python main.py
# 按 Ctrl+A 然后 D 来分离会话
```

### 方式四：使用 systemd（Linux）

创建服务文件 `/etc/systemd/system/discord-bot.service`：

```ini
[Unit]
Description=Discord Commission Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/Users/wanghaixin/Development/DiscordBotWork/commissionBot
ExecStart=/usr/bin/python3 /Users/wanghaixin/Development/DiscordBotWork/commissionBot/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

然后启动服务：

```bash
sudo systemctl enable discord-bot
sudo systemctl start discord-bot
sudo systemctl status discord-bot
```

## 使用说明

### 用户命令

1. **`/bthlp`** - 打开邀请系统面板
   - 点击 "邀请好友" 获取邀请链接
   - 点击 "查看记录" 查看邀请的成员
   - 点击 "查看佣金" 查看佣金统计

### 管理员命令

1. **`/userstats [用户]`** - 查看用户统计

   - 不指定用户：列出所有有佣金的用户
   - 指定用户：查看该用户的详细信息

2. **`/settle <用户> [金额]`** - 结算佣金
   - 不指定金额：结算全部待结算金额
   - 指定金额：结算指定金额

## 佣金计算规则

系统支持配置任意数量的会员等级，每个等级都有对应的佣金比例和价格。

- 当被邀请者升级到某个等级时，邀请者获得 `(当前等级价格 - 之前等级价格) × 邀请者等级佣金比例%` 的佣金
- 佣金按增量计算，避免重复计费
- 邀请者等级越高，获得的佣金比例越高

**示例**（假设配置了4个等级）：
- 月费会员（20%佣金）：100 USDT
- 年费会员（40%佣金）：1000 USDT
- 合伙人（70%佣金）：5000 USDT
- 钻石合伙人（80%佣金）：10000 USDT

当被邀请者从普通会员升级到年费会员时，邀请者获得 `1000 × 邀请者佣金比例%` 的佣金。

## 日志文件

日志文件默认保存在 `logs/bot.log`，可以通过 `.env` 文件中的 `LOG_FILE` 配置修改。

## 故障排查

1. **Bot 无法启动**

   - 检查 `.env` 文件是否存在且配置正确
   - 检查 `DISCORD_TOKEN` 是否有效
   - 检查 Python 版本是否符合要求

2. **无法创建邀请链接**

   - 确保 Bot 有 "Create Instant Invite" 和 "Manage Invites" 权限
   - 检查 `INVITE_CHANNEL_ID` 或 `ALLOWED_CHANNEL_ID` 是否正确

3. **佣金计算不正确**
   - 检查角色 ID 配置是否正确
   - 检查价格配置是否正确
   - 查看日志文件了解详细错误信息

## 注意事项

- 确保 Bot 有足够的权限（特别是管理邀请的权限）
- 定期备份数据库文件（`affiliate_system.db`）
- 角色 ID 配置错误会导致佣金计算失败
- 建议在测试服务器上先测试配置

## 许可证

本项目仅供学习和个人使用。
