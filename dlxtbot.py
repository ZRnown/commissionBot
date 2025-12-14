# 此文件已重构，请使用 bot.py 作为主入口
# 为了向后兼容，这里导入新的 bot 模块
from bot import bot
from config import DISCORD_TOKEN

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
