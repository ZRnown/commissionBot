import discord
from discord.ext import commands
from discord.ui import Button, View
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from discord import app_commands
from config import (
    DISCORD_TOKEN,
    ALLOWED_CHANNEL_IDS,
    NOTIFICATION_CHANNEL_ID,
    INVITE_NOTIFICATION_CHANNEL_ID,
    COMMISSION_NOTIFICATION_CHANNEL_ID,
    GUILD_DISPLAY_NAME,
    PROXY_URL,
    INVITE_CHANNEL_ID,
    ALLOW_BASIC_INVITER,
    BASIC_INVITE_COMMISSION,
    MONTHLY_FEE_COMMISSION,
    ANNUAL_FEE_COMMISSION,
    PARTNER_COMMISSION,
    MONTHLY_FEE_PRICE,
    ANNUAL_FEE_PRICE,
    PARTNER_FEE_PRICE,
    MONTHLY_FEE_ROLE_ID_SET,
    ANNUAL_FEE_ROLE_ID_SET,
    PARTNER_ROLE_ID_SET,
    LEVELS_CONFIG,
    ROLE_TO_LEVEL_MAP,
    ALL_PAID_ROLE_ID_SET,
    SLASH_ALLOWED_USER_ID_SET,
)
from database import Database


# 创建 Bot 实例
intents = discord.Intents.default()
intents.members = True  # 启用成员相关事件
intents.message_content = True  # 启用获取消息内容

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    proxy=PROXY_URL,
)
invite_cache = {}

LOCAL_TZ = ZoneInfo("Asia/Shanghai")

# 付费角色ID合集，便于批量处理
PAID_ROLE_ID_SET = ALL_PAID_ROLE_ID_SET

async def get_channel_by_id(guild: discord.Guild | None, channel_id: int | None):
    """尝试通过 ID 获取频道或线程，先本地缓存再 fetch。"""
    if not guild or not channel_id:
        return None
    ch = guild.get_channel(channel_id)
    if ch:
        return ch
    try:
        ch = await guild.fetch_channel(channel_id)
    except Exception:
        ch = None
    return ch

def format_dt_local(dt: datetime) -> str:
    try:
        if dt.tzinfo is None:
            # Assume UTC if naive (Discord usually provides aware UTC for joined_at)
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

def resolve_member(guild: discord.Guild, query: str) -> discord.Member | None:
    if not query:
        return None
    query = query.strip()
    # Mention format <@123> or <@!123>
    if query.startswith("<@") and query.endswith(">"):
        digits = ''.join(ch for ch in query if ch.isdigit())
        if digits.isdigit():
            m = guild.get_member(int(digits))
            if m:
                return m
    # Raw ID
    if query.isdigit():
        m = guild.get_member(int(query))
        if m:
            return m
    # Name#discrim (pre username changes) or display/name fuzzy
    m = guild.get_member_named(query)
    if m:
        return m
    # Fallback: case-insensitive match on display_name or name
    lowered = query.lower()
    for m in guild.members:
        if (m.display_name and m.display_name.lower() == lowered) or (m.name and m.name.lower() == lowered):
            return m
    return None

def is_paid_role(role: discord.Role | None) -> bool:
    """通过角色ID判断是否为付费角色"""
    if not role:
        return False
    role_id = role.id
    # 检查是否在配置的等级中
    return role_id in ROLE_TO_LEVEL_MAP

def role_tier(role: discord.Role | None) -> int:
    """付费层级：普通=0，其他等级根据配置的tier值"""
    if not role:
        return 0
    role_id = role.id
    level = ROLE_TO_LEVEL_MAP.get(role_id)
    return level.tier if level else 0

def get_highest_paid_role(user_roles):
    paid_roles = [r for r in (user_roles or []) if is_paid_role(r)]
    if not paid_roles:
        return None
    return max(paid_roles, key=role_tier)

def get_user_role_name(user_roles, guild: discord.Guild | None = None):
    role = get_highest_paid_role(user_roles)
    return role.name if role else "普通会员"

def _chunk_text(text: str, limit: int = 1000) -> list[str]:
    """Split text into chunks not exceeding limit, breaking on line boundaries when possible."""
    if not text:
        return [""]
    lines = text.split("\n")
    chunks: list[str] = []
    buf = ""
    for ln in lines:
        add = ("\n" if buf else "") + ln
        if len(buf) + len(add) > limit:
            if buf:
                chunks.append(buf)
                buf = ln
            else:
                # single line longer than limit, hard cut
                chunks.append(ln[:limit])
                buf = ln[limit:]
        else:
            buf += add
    if buf:
        chunks.append(buf)
    return chunks

def commission_percent_for_inviter(member: discord.Member) -> int:
    """通过角色ID获取邀请者的佣金比例"""
    role = get_highest_paid_role(member.roles)
    if role:
        level = ROLE_TO_LEVEL_MAP.get(role.id)
        if level:
            return level.commission
    return BASIC_INVITE_COMMISSION if ALLOW_BASIC_INVITER else 0

def price_for_role(role: discord.Role) -> float:
    """通过角色ID获取角色价格"""
    if not role:
        return 0.0
    level = ROLE_TO_LEVEL_MAP.get(role.id)
    return level.price if level else 0.0

async def cache_guild_invites(guild: discord.Guild):
    try:
        invites = await guild.invites()
        invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
        logging.debug(f"Invite cache refreshed for guild {guild.id}: {invite_cache[guild.id]}")
        return invites
    except discord.Forbidden:
        logging.warning(f"Missing permissions to fetch invites for guild {guild.id}. Invite tracking disabled.")
    except Exception as exc:
        logging.error(f"Failed to refresh invites for guild {guild.id}: {exc}")
    return []


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        invites = await cache_guild_invites(guild)
        if invites:
            logging.info(f"Invite cache primed for guild {guild.id} with {len(invites)} entries.")
    # 启动时全库自拉自清理
    try:
        with Database() as db:
            db.purge_all_self_invites()
    except Exception as exc:
        logging.error(f"Failed to purge self-invites on startup: {exc}")
    # 同步斜杠指令（先全局，再逐服复制并快速生效）
    try:
        await bot.tree.sync()
        logging.info("Global slash commands synced.")
    except Exception as exc:
        logging.error(f"Failed to sync global slash commands: {exc}")
    # 将全局指令复制到各个公会并进行 guild 级同步（更快生效）
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            logging.info(f"Guild slash commands synced for guild {guild.id}.")
        except Exception as exc:
            logging.error(f"Failed to sync slash commands for guild {guild.id}: {exc}")


# Slash: /bthlp
@bot.tree.command(name="bthlp", description="打开邀请系统面板")
async def slash_bthlp(interaction: discord.Interaction):
    # 白名单：若已配置，仅允许名单内用户使用
    if SLASH_ALLOWED_USER_ID_SET and interaction.user.id not in SLASH_ALLOWED_USER_ID_SET:
        await interaction.response.send_message("该命令仅限指定用户使用。", ephemeral=True)
        return
    if interaction.channel.id not in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("此频道不允许交互！", ephemeral=True)
        return
    button1 = Button(label="邀请好友", style=discord.ButtonStyle.primary, custom_id="invite_friend", emoji="🤝")
    button2 = Button(label="查看记录", style=discord.ButtonStyle.green, custom_id="check_records", emoji="📜")
    button3 = Button(label="查看佣金", style=discord.ButtonStyle.green, custom_id="check_commission", emoji="💵")
    view = View()
    view.add_item(button1)
    view.add_item(button2)
    view.add_item(button3)
    embed = discord.Embed(
        title="邀请系统",
        description="点击下方按钮来管理你的邀请链接",
        color=discord.Color.blue()
    )
    # 增加功能与提示字段
    embed.add_field(
        name="💎代理系统                💰自动分佣",
        value="获取你的永久邀请链接 查看你的邀请统计和记录",
        inline=False
    )
    # 动态生成佣金分配比例显示
    commission_lines = []
    for level in LEVELS_CONFIG:
        commission_lines.append(f"{level.name} | {level.commission}% 佣金分成")
    commission_text = "```\n" + "\n".join(commission_lines) + "\n```" if commission_lines else "暂无配置"

    embed.add_field(
        name="🎉佣金分配比例",
        value=commission_text,
        inline=False
    )
    embed.add_field(
        name="\u200b",
        value="----------------------------------------",
        inline=False
    )
    embed.set_footer(text="交易总归有风险加入我们一起赚市场上的钱💸")
    # 面板需要所有人可见
    await interaction.response.send_message(embed=embed, view=view)


# Slash: /userstats（仅管理员）
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="userstats", description="查看用户统计或列出累计佣金用户（管理员）")
@app_commands.describe(user="要查询的用户（可选）")
async def slash_userstats(interaction: discord.Interaction, user: discord.Member | None = None):
    # 白名单：若已配置，仅允许名单内用户使用
    if SLASH_ALLOWED_USER_ID_SET and interaction.user.id not in SLASH_ALLOWED_USER_ID_SET:
        await interaction.response.send_message("该命令仅限指定用户使用。", ephemeral=True)
        return
    # 运行时权限兜底校验
    if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理员可以使用该命令。", ephemeral=True)
        return
    try:
        with Database() as db:
            if user is None:
                positive_users = db.get_positive_balance_users()
                if not positive_users:
                    await interaction.response.send_message("暂无累计佣金>0的用户。", ephemeral=True)
                    return
                lines = []
                for uid, username, balance, role_id in positive_users:
                    # 优先使用实时角色名称，回退到 DB 标记
                    live_role_name = None
                    member_obj = interaction.guild.get_member(uid) if interaction.guild else None
                    if not member_obj and interaction.guild:
                        try:
                            member_obj = await interaction.guild.fetch_member(uid)
                        except Exception:
                            member_obj = None
                    if member_obj:
                        paid = get_highest_paid_role(member_obj.roles)
                        live_role_name = paid.name if paid else "普通会员"
                    role_name = live_role_name if live_role_name else ("付费会员" if role_id else "普通会员")
                    mention = f"<@{uid}>"
                    total, settled, unsettled = db.get_commission_stats(uid)
                    lines.append(f"**{role_name}** · {mention} — 总:{total:.2f} / 已:{settled:.2f} / 待:{unsettled:.2f} USDT")
                embed = discord.Embed(title="累计佣金用户列表", description="\n".join(lines), color=discord.Color.gold())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            # 单用户详情
            target = user
            user_row = db.get_user_by_id(target.id)
            allowed_role = get_highest_paid_role(target.roles)
            role_name = allowed_role.name if allowed_role else "普通会员"
            total, settled, unsettled = db.get_commission_stats(target.id)
            # 最新邀请链接（优先展示机器人生成的永久链接，fallback 到 v2 记录）
            invite_url = None
            row = db.get_invite_link_by_user(target.id)
            if row and row[0]:
                invite_url = row[0]
            else:
                latest_v2 = db.get_latest_invite_v2(target.id)
                if latest_v2:
                    invite_url = latest_v2[1]
            embed = discord.Embed(title="用户信息", color=discord.Color.blurple())
            embed.add_field(name=":bust_in_silhouette: 用户", value=f"{target.mention} ({target})", inline=False)
            embed.add_field(name=":bust_in_silhouette: 角色", value=f"**{role_name}**", inline=False)
            embed.add_field(name="📊 总佣金", value=f"{total:.2f} USDT", inline=False)
            embed.add_field(name="✅ 已结算", value=f"{settled:.2f} USDT", inline=False)
            embed.add_field(name="🕒 待结算", value=f"{unsettled:.2f} USDT", inline=False)
            if invite_url:
                embed.add_field(name="最新邀请链接", value=f"```{invite_url}```", inline=False)
            else:
                embed.add_field(name="最新邀请链接", value="暂无", inline=False)
            # 追加佣金记录（仅入账事件，不显示结算，不再补 +0 条目）
            try:
                lines = []
                recent_events = db.get_recent_referral_events(target.id, limit=10)
                if recent_events:
                    for nm_id, when_text, amount, settled_flag, role_id_val in recent_events:
                        # 仅展示升级入账事件：amount>0；排除自拉自
                        if amount and amount > 0 and nm_id != target.id:
                            mention = f"<@{nm_id}>"
                            role_obj = interaction.guild.get_role(role_id_val) if role_id_val and interaction.guild else None
                            role_disp = None
                            if not role_obj and interaction.guild:
                                # 尝试从成员实时角色获取（先缓存，失败则 fetch）
                                member_obj = interaction.guild.get_member(nm_id)
                                if not member_obj:
                                    try:
                                        member_obj = await interaction.guild.fetch_member(nm_id)
                                    except Exception:
                                        member_obj = None
                                live_paid = get_highest_paid_role(member_obj.roles) if member_obj else None
                                role_disp = live_paid.name if live_paid else None
                            if role_disp is None:
                                role_disp = role_obj.name if role_obj else "付费会员"
                            lines.append(f"+ {amount:.2f} ·  {mention} · 升级: {role_disp} · 时间: {when_text}")
                # 在同一 Embed 中展示记录
                embed.add_field(name="📜 佣金记录", value="\n".join(lines) if lines else "暂无佣金记录", inline=False)
            except Exception:
                pass
            # 统一发送（移除复制邀请链接按钮）
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as exc:
        logging.error(f"/userstats failed: {exc}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(f"查询失败: {exc}", ephemeral=True)
            except Exception:
                await interaction.followup.send(f"查询失败: {exc}", ephemeral=True)
        else:
            await interaction.followup.send(f"查询失败: {exc}", ephemeral=True)


# Slash: /remove_paid_roles（仅管理员）移除指定用户的付费身份
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="remove_paid_roles", description="移除指定用户的付费身份（管理员）")
@app_commands.describe(user="要移除付费身份的用户")
async def slash_remove_paid_roles(interaction: discord.Interaction, user: discord.Member):
    # 白名单检查
    if SLASH_ALLOWED_USER_ID_SET and interaction.user.id not in SLASH_ALLOWED_USER_ID_SET:
        await interaction.response.send_message("该命令仅限指定用户使用。", ephemeral=True)
        return
    # 管理员权限兜底
    if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理员可以使用该命令。", ephemeral=True)
        return
    try:
        member_roles = list(user.roles or [])
        paid_roles = [r for r in member_roles if r.id in PAID_ROLE_ID_SET]
        if not paid_roles:
            await interaction.response.send_message(f"{user.mention} 没有可移除的付费身份。", ephemeral=True)
            return
        try:
            await user.remove_roles(*paid_roles, reason="管理员移除付费身份")
        except Exception as exc:
            await interaction.response.send_message(f"移除失败：{exc}", ephemeral=True)
            return
        removed_names = ", ".join([r.name for r in paid_roles])
        embed = discord.Embed(title="已移除付费身份", color=discord.Color.orange())
        embed.add_field(name="用户", value=f"{user.mention} ({user})", inline=False)
        embed.add_field(name="移除角色", value=removed_names, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as exc:
        logging.error(f"/remove_paid_roles failed: {exc}")
        await interaction.response.send_message(f"操作失败: {exc}", ephemeral=True)

@bot.event
async def on_member_remove(member: discord.Member):
    """成员退群：标记其邀请链接失效，并尝试删除对应邀请。"""
    try:
        with Database() as db:
            # 标记 invites_v2 为 inactive
            db.cursor.execute('''UPDATE invites_v2 SET active = 0 WHERE user_id = ?''', (member.id,))
            db.conn.commit()
        # 尝试删除其名下的所有邀请（如果 inviter 记录为该用户）
        try:
            invites = await member.guild.invites()
            for inv in invites:
                try:
                    if getattr(inv, 'inviter', None) and inv.inviter and inv.inviter.id == member.id:
                        await inv.delete(reason="Member left; cleanup")
                except Exception:
                    continue
        except Exception:
            pass
        # 刷新缓存
        await cache_guild_invites(member.guild)
    except Exception as exc:
        logging.error(f"on_member_remove cleanup failed for {member.id}: {exc}")


# Slash: /settle（仅管理员）
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="settle", description="结算用户佣金（管理员）")
@app_commands.describe(user="要结算的用户", amount="结算金额（USDT，留空则结算全部待结算）")
async def slash_settle(interaction: discord.Interaction, user: discord.Member, amount: float | None = None):
    # 白名单：若已配置，仅允许名单内用户使用
    if SLASH_ALLOWED_USER_ID_SET and interaction.user.id not in SLASH_ALLOWED_USER_ID_SET:
        await interaction.response.send_message("该命令仅限指定用户使用。", ephemeral=True)
        return
    # 运行时权限兜底校验
    if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("只有管理员可以使用该命令。", ephemeral=True)
        return
    try:
        with Database() as db:
            # 若未指定金额，则结算全部待结算
            total, settled, unsettled = db.get_commission_stats(user.id)
            to_settle = unsettled if amount is None else min(max(amount, 0.0), unsettled)
            if to_settle <= 0:
                await interaction.response.send_message("无可结算金额。", ephemeral=True)
                return
            settled_sum = db.settle_user_amount(user.id, to_settle)
            embed = discord.Embed(title="佣金结算完成", color=discord.Color.green())
            embed.add_field(name="用户", value=f"{user.mention} ({user})", inline=False)
            embed.add_field(name="结算金额", value=f"{settled_sum:.2f} USDT", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as exc:
        logging.error(f"/settle failed: {exc}")
        await interaction.response.send_message(f"结算失败: {exc}", ephemeral=True)


@bot.command()
@commands.has_permissions(administrator=True)
async def settle(ctx, member: discord.Member, amount: float):
    """结算用户佣金：从余额中扣减 amount USDT。仅管理员可用。"""
    if amount <= 0:
        await ctx.send("结算金额必须大于 0。")
        return
    try:
        with Database() as db:
            user = db.get_user_by_id(member.id)
            current_balance = float(user[4] if user else 0)
            if amount > current_balance:
                await ctx.send(f"结算失败：金额超过当前余额（当前 {current_balance} USDT）。")
                return
            new_balance = db.adjust_reward_balance(member.id, -amount)
            embed = discord.Embed(title="佣金结算完成", color=discord.Color.green())
            embed.add_field(name="用户", value=f"{member.mention} ({member})", inline=False)
            embed.add_field(name="结算金额", value=f"{amount} USDT", inline=False)
            embed.add_field(name="结算后余额", value=f"{new_balance} USDT", inline=False)
            await ctx.send(embed=embed)
    except Exception as exc:
        logging.error(f"settle failed: {exc}")
        await ctx.send(f"结算失败: {exc}")


@bot.event
async def on_interaction(interaction):
    logging.debug(f"Interaction received: {interaction.data}")

    # 仅处理组件交互（按钮等），忽略斜杠指令以避免误判 custom_id
    try:
        if interaction.type != discord.InteractionType.component:
            return
    except Exception:
        # 防御：若无法判断类型，则不处理
        return

    # 放宽限制：允许所有用户点击按钮（频道限制仍保留）
    # 先进行 defer，避免 10062 Unknown interaction
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    if interaction.channel.id not in ALLOWED_CHANNEL_IDS:
        logging.debug(f"Wrong channel ID: {interaction.channel.id}.")
        await interaction.followup.send("此频道不允许交互！", ephemeral=True)
        return

    if 'custom_id' not in interaction.data:
        logging.error(f"No custom_id in interaction data for user {interaction.user.name}.")
        await interaction.followup.send("交互数据缺少 custom_id，无法继续操作！", ephemeral=True)
        return

    button_id = interaction.data['custom_id']
    logging.debug(f"Button custom_id: {button_id}")

    try:
        with Database() as db:
            if button_id == 'check_records':
                user_id = interaction.user.id
                user_data = db.get_user_by_id(user_id)
                role_name = get_user_role_name(interaction.user.roles, interaction.guild)

                embed = discord.Embed(title="📊 查看记录", color=discord.Color.blue())
                embed.add_field(name=":bust_in_silhouette: 角色", value=f"**{role_name or '普通会员'}**", inline=False)

                if user_data and user_data[2]:
                    referrer_id = user_data[2]
                    embed.add_field(name=":bust_in_silhouette: 邀请者", value=f"<@{referrer_id}>", inline=False)
                else:
                    embed.add_field(name=":bust_in_silhouette: 邀请者", value="暂无", inline=False)

                if user_data and user_data[3]:
                    join_date = user_data[3]
                    embed.add_field(name=":date: 加入时间", value=join_date, inline=False)
                else:
                    # 兜底使用 Discord 的 joined_at（本地时区）
                    if getattr(interaction.user, "joined_at", None):
                        embed.add_field(name=":date: 加入时间", value=format_dt_local(interaction.user.joined_at), inline=False)
                    else:
                        embed.add_field(name=":date: 加入时间", value="暂无", inline=False)

                referred_users = db.get_referred_users(user_id)
                # 过滤掉自拉自的记录
                filtered_referred = [ru for ru in (referred_users or []) if ru[0] != user_id]
                invited_count = len(filtered_referred)
                if filtered_referred:
                    lines = []
                    for idx, referred_user in enumerate(filtered_referred, start=1):
                        referred_user_id = referred_user[0]
                        referred_username = referred_user[1] or ""
                        join_text = referred_user[2] or ""
                        # 显示为 mm-dd HH:MM
                        try:
                            dt = datetime.strptime(join_text, "%Y-%m-%d %H:%M:%S")
                            join_display = dt.strftime("%m-%d %H:%M")
                        except Exception:
                            join_display = join_text
                        # 优先取当前在线成员的实际付费角色名称
                        cur_member = interaction.guild.get_member(referred_user_id) if interaction.guild else None
                        if cur_member:
                            live_paid = get_highest_paid_role(cur_member.roles)
                            r_role_name = live_paid.name if live_paid else "普通会员"
                        else:
                            # 若未缓存，再尝试 fetch_member
                            fetch_member_obj = None
                            if interaction.guild:
                                try:
                                    fetch_member_obj = await interaction.guild.fetch_member(referred_user_id)
                                except Exception:
                                    fetch_member_obj = None
                            if fetch_member_obj:
                                live_paid = get_highest_paid_role(fetch_member_obj.roles)
                                r_role_name = live_paid.name if live_paid else "普通会员"
                            else:
                                r_role_id = referred_user[3]
                                role_obj = interaction.guild.get_role(r_role_id) if r_role_id and interaction.guild else None
                                r_role_name = role_obj.name if role_obj else "普通会员"
                        name_part = f"{referred_username}\n" if referred_username else ""
                        lines.append(f"{idx}. <@{referred_user_id}> ({referred_user_id}) - {join_display}\n└ 用户组: {r_role_name}")
                    all_text = "\n".join(lines)
                    chunks = _chunk_text(all_text, limit=1000)
                    embed.add_field(name=":busts_in_silhouette: 你邀请的成员", value=chunks[0], inline=False)
                else:
                    embed.add_field(name=":busts_in_silhouette: 你邀请的成员", value="暂无", inline=False)

                query_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                embed.set_footer(text=f"提示: 当你邀请的成员升级用户组时,你将获得佣金奖励! \n查询时间：{query_time}")
                sent_via_response = False
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    sent_via_response = True
                else:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                # 追加长列表的后续分块
                if filtered_referred:
                    all_text = "\n".join(lines)
                    chunks = _chunk_text(all_text, limit=1000)
                    if len(chunks) > 1:
                        for extra in chunks[1:]:
                            extra_embed = discord.Embed(title="邀请系统 · 你邀请的成员(续)", color=discord.Color.blue())
                            extra_embed.add_field(name=":busts_in_silhouette: 你邀请的成员(续)", value=extra, inline=False)
                            await interaction.followup.send(embed=extra_embed, ephemeral=True)
                logging.info(f"Button '查看记录' clicked by {interaction.user.name} successfully.")
                logging.debug(f"User {user_id} has invited {invited_count} members.")

            elif button_id == 'check_commission':
                user_id = interaction.user.id
                user_data = db.get_user_by_id(user_id)
                allowed_role = get_highest_paid_role(interaction.user.roles)
                role_name = allowed_role.name if allowed_role else "普通会员"
                # 佣金比例：付费角色取其配置；普通会员在允许时取 BASIC_INVITE_COMMISSION，否则为 0
                role_commission = commission_percent_for_inviter(interaction.user)
                role_price = price_for_role(allowed_role) if allowed_role else 0
                # 统计口径：总=历史事件总和；已=settled=1 事件总和；待=总-已
                total, settled, unsettled = db.get_commission_stats(user_id)
                embed = discord.Embed(
                    title="💰 我的佣金",
                    description=(f"**{role_name}** | 佣金比例: {role_commission}%"),
                    color=discord.Color.gold()
                )
                stats = (
                    f"累计佣金: {total:.2f} USDT\n"
                    f"待结算: {unsettled:.2f} USDT\n"
                    f"已结算: {settled:.2f} USDT"
                )
                embed.add_field(name="📊 佣金统计", value=stats, inline=False)
                # 佣金记录：仅显示入账事件（升级触发）；不显示结算流水；并为没有升级记录的受邀成员补 +0
                lines = []
                try:
                    recent_events = db.get_recent_referral_events(user_id, limit=10)
                    if recent_events:
                        for nm_id, when_text, amount, settled_flag, role_id_val in recent_events:
                            # 仅展示升级入账事件：amount>0；排除自拉自
                            if amount and amount > 0 and nm_id != user_id:
                                mention = f"<@{nm_id}>"
                                role_obj = interaction.guild.get_role(role_id_val) if role_id_val and interaction.guild else None
                                role_disp = None
                                if not role_obj and interaction.guild:
                                    member_obj = interaction.guild.get_member(nm_id)
                                    if not member_obj:
                                        try:
                                            member_obj = await interaction.guild.fetch_member(nm_id)
                                        except Exception:
                                            member_obj = None
                                    live_paid = get_highest_paid_role(member_obj.roles) if member_obj else None
                                    role_disp = live_paid.name if live_paid else None
                                if role_disp is None:
                                    role_disp = role_obj.name if role_obj else "付费会员"
                                lines.append(f"+ {amount:.2f} ·  {mention} · 升级: {role_disp} · 时间: {when_text}")
                except Exception:
                    pass
                if lines:
                    chunks = _chunk_text("\n".join(lines), limit=1000)
                    embed.add_field(name="📜 佣金记录", value=chunks[0], inline=False)
                else:
                    embed.add_field(name="📜 佣金记录", value="暂无佣金记录", inline=False)
                embed.set_footer(text="💡 提示: 当你邀请的成员升级用户组时,你将获得佣金奖励!")

                sent_via_response = False
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    sent_via_response = True
                else:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                # 佣金记录追加分块
                if lines:
                    chunks = _chunk_text("\n".join(lines), limit=1000)
                    if len(chunks) > 1:
                        for extra in chunks[1:]:
                            extra_embed = discord.Embed(title="邀请系统 · 佣金记录(续)", color=discord.Color.gold())
                            extra_embed.add_field(name="📜 佣金记录(续)", value=extra, inline=False)
                            await interaction.followup.send(embed=extra_embed, ephemeral=True)
                logging.info(f"Button '查看佣金' clicked by {interaction.user.name} successfully.")
                logging.debug(
                    f"Commission query for user {user_id}: role={allowed_role.id if allowed_role else 'none'}, "
                    f"commission={role_commission}, price={role_price}, total={total}, settled={settled}, unsettled={unsettled}"
                )

            elif button_id == 'invite_friend':
                user_id = interaction.user.id
                # 获取完整的成员信息（包含所有角色）
                member = interaction.guild.get_member(user_id) if interaction.guild else None
                if not member and interaction.guild:
                    try:
                        member = await interaction.guild.fetch_member(user_id)
                    except Exception:
                        member = interaction.user
                else:
                    member = member or interaction.user
                
                # 计算角色与佣金、邀请统计
                allowed_role = get_highest_paid_role(member.roles)
                role_name = allowed_role.name if allowed_role else "普通会员"
                
                # 调试日志：输出用户的所有角色ID和配置的角色ID集合
                user_role_ids = [r.id for r in member.roles]
                logging.debug(f"User {user_id} roles: {user_role_ids}")
                logging.debug(f"Configured paid role IDs: {ALL_PAID_ROLE_ID_SET}")
                
                # 开关：普通会员邀请资格
                if (allowed_role is None) and (not ALLOW_BASIC_INVITER):
                    if not interaction.response.is_done():
                        await interaction.response.send_message("当前未开放普通会员邀请资格。", ephemeral=True)
                    else:
                        await interaction.followup.send("当前未开放普通会员邀请资格。", ephemeral=True)
                    return
                role_commission = commission_percent_for_inviter(member)
                referred_users = db.get_referred_users(user_id)
                invited_count = len(referred_users) if referred_users else 0

                # 选择用于创建邀请的频道：ENV 指定 > ALLOWED_CHANNELS[0] > 当前频道
                target_channel = None
                if INVITE_CHANNEL_ID:
                    target_channel = interaction.guild.get_channel(INVITE_CHANNEL_ID)
                if target_channel is None and ALLOWED_CHANNEL_IDS:
                    target_channel = interaction.guild.get_channel(ALLOWED_CHANNEL_IDS[0])
                if target_channel is None:
                    target_channel = interaction.channel

                # 先从 invites_v2 取最新，否则从 invites 取；仅在无效/不存在时创建
                # 优先使用机器人生成并存放在 invites 表中的“永久”链接
                existing_url = None
                row = db.get_invite_link_by_user(user_id)
                if row and row[0]:
                    existing_url = row[0]
                else:
                    latest_v2 = db.get_latest_invite_v2(user_id)
                    if latest_v2:
                        existing_url = latest_v2[1]

                valid_url = None
                if existing_url:
                    code = existing_url.rsplit('/', 1)[-1]
                    try:
                        await interaction.guild.fetch_invite(code)
                        valid_url = existing_url
                    except discord.NotFound:
                        # 只有确认为不存在才重建
                        pass
                    except Exception:
                        # 权限等其他错误一律信任已有链接，避免每次都重建
                        valid_url = existing_url

                if valid_url is None:
                    # 未找到或已失效：只创建一次，并更新 DB
                    new_invite = await target_channel.create_invite(max_age=0, max_uses=0, unique=True)
                    try:
                        await interaction.guild.fetch_invite(new_invite.code)
                    except Exception:
                        pass
                    valid_url = new_invite.url
                    db.set_invite_link(user_id, valid_url)
                    try:
                        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        db.add_invite_v2(user_id, new_invite.code, valid_url, target_channel.id, now)
                    except Exception:
                        pass
                    if interaction.guild:
                        await cache_guild_invites(interaction.guild)

                embed = discord.Embed(
                    title="邀请好友",
                    description=f"**{role_name}**，您的邀请佣金分成是 {role_commission}%",
                    color=discord.Color.green()
                )
                embed.add_field(name="邀请链接", value=f"```{valid_url}```", inline=False)
                embed.add_field(name="邀请统计", value=f"已邀请人数：{invited_count}", inline=False)
                embed.add_field(name="佣金分成", value=f"您将获得 {role_commission}% 的邀请佣金", inline=False)
                embed.set_footer(text="分享这个链接来邀请朋友加入服务器！")
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                logging.info(
                    f"Button '邀请好友' clicked by {interaction.user.name} successfully. Link delivered (reused if valid)."
                )

            elif button_id == 'noop':
                pass

            else:
                logging.error(f"Unknown custom_id: {button_id} for user {interaction.user.name}.")
                if not interaction.response.is_done():
                    await interaction.response.send_message("无效的操作！", ephemeral=True)
                else:
                    await interaction.followup.send("无效的操作！", ephemeral=True)

    except Exception as exc:
        logging.error(f"Error processing interaction for user {interaction.user.name}: {exc}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(f"发生错误: {exc}", ephemeral=True)
            except Exception:
                await interaction.followup.send(f"发生错误: {exc}", ephemeral=True)
        else:
            await interaction.followup.send(f"发生错误: {exc}", ephemeral=True)
        logging.error(f"Interaction failed for user {interaction.user.name}.")


@bot.event
async def on_member_join(member: discord.Member):
    logging.info(f"Member {member} joined guild {member.guild.id}.")

    previous_invites = invite_cache.get(member.guild.id, {}).copy()
    current_invites = await cache_guild_invites(member.guild)
    used_invite = None
    inviter_member = None
    inviter_user_id = None

    if current_invites:
        for invite in current_invites:
            previous_uses = previous_invites.get(invite.code)
            if previous_uses is not None and invite.uses > previous_uses:
                used_invite = invite
                break
        if used_invite:
            invite_code = used_invite.code
            try:
                with Database() as db:
                    # 优先用我们记录的 code→inviter 归属（适用于机器人代创建链接）
                    mapped_uid = db.get_inviter_by_code(invite_code)
                    if mapped_uid:
                        inviter_user_id = mapped_uid
                        inviter_member = member.guild.get_member(mapped_uid)
                        if inviter_member is None:
                            try:
                                inviter_member = await member.guild.fetch_member(mapped_uid)
                            except Exception:
                                inviter_member = None
                    elif used_invite.inviter:
                        # 兼容用户自行创建的邀请链接：记录一条 invites_v2 以便后续统计
                        inviter_user_id = used_invite.inviter.id
                        inviter_member = member.guild.get_member(inviter_user_id)
                        if inviter_member is None:
                            try:
                                inviter_member = await member.guild.fetch_member(inviter_user_id)
                            except Exception:
                                inviter_member = None
                        try:
                            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            url = getattr(used_invite, 'url', None) or f"https://discord.gg/{invite_code}"
                            db.add_invite_v2(inviter_user_id, invite_code, url, used_invite.channel.id if used_invite.channel else 0, now)
                        except Exception:
                            pass
            except Exception as exc:
                logging.error(f"Failed inviter attribution via code mapping: {exc}")
            if inviter_user_id:
                logging.info(f"Detected inviter {inviter_user_id} for new member {member} with invite code {invite_code}.")
        else:
            logging.debug(
                f"No matching invite usage found for member {member}. Previous cache size: {len(previous_invites)}."
            )
    else:
        logging.debug(f"Invite cache unavailable for guild {member.guild.id}; inviter cannot be resolved.")

    # 以北京时间记录加入时间（优先使用 Discord 提供的 joined_at）
    if getattr(member, "joined_at", None):
        join_time_text = format_dt_local(member.joined_at)
    else:
        # 退化为当前时间（UTC 转本地）
        join_time_text = format_dt_local(datetime.now(ZoneInfo("UTC")))
    primary_role = get_highest_paid_role(member.roles)
    role_id = primary_role.id if primary_role else None

    try:
        with Database() as db:
            db.add_or_update_user(
                user_id=member.id,
                username=str(member),
                # 自拉自不计入关联：DB 不记录 referred_by
                referred_by=(None if (inviter_user_id and inviter_user_id == member.id) else (inviter_user_id if inviter_user_id else None)),
                join_date=join_time_text,
                role_id=role_id,
            )
            # 针对该用户做一次自拉自清理，避免历史脏数据影响
            db.purge_self_invites_for_user(member.id)
            # 不在加入时计佣。佣金在 on_member_update（角色升级）事件里发放。
    except Exception as exc:
        logging.error(f"Failed to store member {member} in database: {exc}")

    # 使用邀请通知频道
    notification_channel = await get_channel_by_id(member.guild, INVITE_NOTIFICATION_CHANNEL_ID)
    if notification_channel is None:
        logging.error(f"Invite notification channel {INVITE_NOTIFICATION_CHANNEL_ID} not found in guild {member.guild.id}.")
        return

    guild_display_name = GUILD_DISPLAY_NAME or member.guild.name
    inviter_text = "由 系统邀请加入"
    if inviter_user_id:
        inviter_text = f"由 <@{inviter_user_id}> 邀请加入"

    # 欢迎消息的加入时间以北京时间展示
    try:
        dt = datetime.strptime(join_time_text, "%Y-%m-%d %H:%M:%S")
        join_time_display = dt.strftime("%Y年%m月%d日 %H:%M")
    except Exception:
        join_time_display = join_time_text
    # 嵌入欢迎消息（含头像）
    embed = discord.Embed(title="🎉 新成员加入", color=discord.Color.green())
    embed.description = f"欢迎 <@{member.id}> 加入 {guild_display_name}!"
    embed.add_field(name="👤 邀请者", value=inviter_text, inline=False)
    embed.add_field(name="📊 服务器统计", value=f"当前成员数：{member.guild.member_count}", inline=False)
    embed.add_field(name="⏰ 加入时间", value=join_time_display, inline=False)
    try:
        avatar_url = member.display_avatar.url if getattr(member, 'display_avatar', None) else None
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)
    except Exception:
        pass

    try:
        await notification_channel.send(embed=embed)
        logging.info(f"Sent welcome notification for {member}.")
        logging.debug(f"Welcome embed sent for member {member.id}")
    except Exception as exc:
        logging.error(f"Failed to send welcome notification for {member}: {exc}")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """当成员角色发生变化时，如果新增了允许的角色，则为其邀请者发放佣金（防重复）。"""
    try:
        # 计算升级前后的最高付费层级（支持多级升级：普通->月->年->合伙）
        before_roles = list(getattr(before, 'roles', []) or [])
        after_roles = list(getattr(after, 'roles', []) or [])
        before_highest = get_highest_paid_role(before_roles)
        after_highest = get_highest_paid_role(after_roles)
        # 若升级后无付费角色或层级未上升，则不发放
        if not after_highest:
            return
        if role_tier(after_highest) <= role_tier(before_highest):
            return
        # 以升级后的最高层级作为本次计佣的目标角色
        new_role = after_highest
        new_price = price_for_role(new_role) if new_role else 0.0
        prev_price = price_for_role(before_highest) if before_highest else 0.0
        incremental_price = max(new_price - prev_price, 0.0)
        if incremental_price <= 0:
            return
        with Database() as db:
            # 找邀请者
            # 先清理受邀者自身可能存在的自拉自历史
            db.purge_self_invites_for_user(after.id)
            inviter_id = db.get_referrer_id_for_member(after.id)
            if not inviter_id:
                return
            # 自拉自不计佣
            if inviter_id == after.id:
                return
            # 防重复：同一成员在同一层级不重复发放（允许更高层级再次发放）
            if db.has_reward_for_member_role(after.id, new_role.id):
                return

            # 获取邀请者的佣金比例
            inviter_member = after.guild.get_member(inviter_id)
            percent = commission_percent_for_inviter(inviter_member) if inviter_member else (BASIC_INVITE_COMMISSION if ALLOW_BASIC_INVITER else 0)

            # 新身份的价格（基于角色名称关键字）
            if not percent or not incremental_price:
                return

            commission_amount = round(incremental_price * (percent / 100.0), 2)
            # 入账 + 记录事件（invite_code 无法可靠获取，填 None；时间取当前北京时间），记录升级到的角色ID
            db.adjust_reward_balance(inviter_id, commission_amount)
            now_text = format_dt_local(datetime.now(ZoneInfo("UTC")))
            try:
                db.add_referral_event(inviter_id, None, after.id, now_text, commission_amount, role_id=new_role.id)
            except Exception as exc:
                logging.error(f"Failed to add referral event on role upgrade: {exc}")
            # 同步受邀者当前角色到 users.role_id，便于记录与展示
            try:
                db.update_user_role(after.id, new_role.id)
            except Exception as exc:
                logging.error(f"Failed to update user role in DB: {exc}")
            logging.info(f"Awarded commission {commission_amount} to inviter {inviter_id} for member {after.id} role upgrade {new_role.id}.")

            # 发送佣金奖励通知到指定频道
            try:
                notify_channel = await get_channel_by_id(after.guild, COMMISSION_NOTIFICATION_CHANNEL_ID)
                if notify_channel:
                    inviter_mention = f"<@{inviter_id}>"
                    invited_mention = after.mention
                    old_name = (before_highest.name if before_highest else "普通")
                    new_name = new_role.name if new_role else "普通会员"
                    embed = discord.Embed(title="💰 佣金奖励", color=discord.Color.gold())
                    embed.description = f"恭喜 {inviter_mention} 获得了 {commission_amount} USDT 的佣金!"
                    embed.add_field(name="👤 被邀请者", value=invited_mention, inline=False)
                    embed.add_field(name="🔄 角色变更", value=f"{old_name} → {new_name}", inline=False)
                    embed.add_field(name="💵 佣金金额", value=f"{commission_amount} USDT", inline=False)
                    embed.add_field(name="获得时间", value=now_text, inline=False)
                    await notify_channel.send(embed=embed)
            except Exception as exc:
                logging.error(f"Failed to send commission notification: {exc}")
    except Exception as exc:
        logging.error(f"on_member_update failed: {exc}")

# 运行 Bot
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)

