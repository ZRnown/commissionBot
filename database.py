import sqlite3
import logging
from config import (
    DATABASE_PATH,
)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_PATH)
        self.cursor = self.conn.cursor()
        logging.debug(f"Opening database connection to {DATABASE_PATH}.")

        # 创建 users 表
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            referred_by INTEGER,
            join_date TEXT,
            reward_balance REAL,
            role_id INTEGER
        )''')

        # 创建 invites 表，存储每个用户的邀请链接
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS invites (
            user_id INTEGER PRIMARY KEY,
            invite_link TEXT
        )''')

        # 新增 v2 多邀请链接表（非覆盖旧表，便于逐步迁移）
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS invites_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            url TEXT,
            channel_id INTEGER,
            created_at TEXT,
            expires_at TEXT,
            max_uses INTEGER,
            uses INTEGER,
            active INTEGER DEFAULT 1
        )''')

        # 邀请事件流水（用于累计、结算、统计）
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS referral_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invite_code TEXT,
            new_member_id INTEGER,
            joined_at TEXT,
            commission_amount REAL,
            settled INTEGER DEFAULT 0,
            role_id INTEGER
        )''')

        # 结算记录表
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            created_at TEXT,
            note TEXT
        )''')

        self.conn.commit()
        logging.info("Database initialized with users and invites tables.")

        # 迁移：为 referral_events 增加 role_id 字段（若不存在）
        try:
            self.cursor.execute("PRAGMA table_info(referral_events)")
            cols = [row[1] for row in self.cursor.fetchall()]
            if 'role_id' not in cols:
                self.cursor.execute('''ALTER TABLE referral_events ADD COLUMN role_id INTEGER''')
                self.conn.commit()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def add_or_update_user(self, user_id, username=None, referred_by=None, join_date=None, role_id=None):
        """创建或更新用户信息，保留已存在的余额数据。"""
        existing_user = self.get_user_by_id(user_id)

        if existing_user:
            current_username = username or existing_user[1]
            current_referred_by = referred_by if referred_by is not None else existing_user[2]
            current_join_date = join_date or existing_user[3]
            current_role_id = role_id if role_id is not None else existing_user[5]

            self.cursor.execute(
                '''UPDATE users SET username = ?, referred_by = ?, join_date = ?, role_id = ? WHERE user_id = ?''',
                (current_username, current_referred_by, current_join_date, current_role_id, user_id)
            )
            logging.info(f"User {current_username} updated in the database.")
        else:
            self.cursor.execute(
                '''INSERT INTO users (user_id, username, referred_by, join_date, reward_balance, role_id)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (user_id, username, referred_by, join_date, 0, role_id)
            )
            logging.info(f"User {username} added to the database.")

        self.conn.commit()
        logging.debug(f"Database commit completed for user {user_id}.")

    def get_user_by_id(self, user_id):
        logging.debug(f"Fetching user {user_id} from database.")
        self.cursor.execute('''SELECT * FROM users WHERE user_id = ?''', (user_id,))
        return self.cursor.fetchone()

    def get_invite_link_by_user(self, user_id):
        logging.debug(f"Fetching invite link for user {user_id}.")
        self.cursor.execute('''SELECT invite_link FROM invites WHERE user_id = ?''', (user_id,))
        return self.cursor.fetchone()

    def set_invite_link(self, user_id, invite_link):
        self.cursor.execute('''INSERT OR REPLACE INTO invites (user_id, invite_link) VALUES (?, ?)''', (user_id, invite_link))
        self.conn.commit()
        logging.info(f"Invite link for user {user_id} updated/created.")
        logging.debug(f"Invite link stored: {invite_link}.")

    # v2 邀请
    def add_invite_v2(self, user_id: int, code: str, url: str, channel_id: int, created_at: str,
                       expires_at: str = None, max_uses: int = 0, uses: int = 0, active: int = 1):
        self.cursor.execute(
            '''INSERT INTO invites_v2 (user_id, code, url, channel_id, created_at, expires_at, max_uses, uses, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, code, url, channel_id, created_at, expires_at, max_uses, uses, active)
        )
        self.conn.commit()

    def get_latest_invite_v2(self, user_id: int):
        self.cursor.execute('''SELECT code, url, channel_id, created_at FROM invites_v2 WHERE user_id = ? ORDER BY id DESC LIMIT 1''', (user_id,))
        return self.cursor.fetchone()

    def get_inviter_by_code(self, code: str):
        """根据邀请码 code 反查邀请者 user_id（按最新一条记录）。"""
        self.cursor.execute('''SELECT user_id FROM invites_v2 WHERE code = ? ORDER BY id DESC LIMIT 1''', (code,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def get_referred_users(self, referrer_id):
        """获取指定用户邀请的所有成员"""
        self.cursor.execute('''SELECT user_id, username, join_date, role_id FROM users WHERE referred_by = ? ORDER BY join_date DESC''', (referrer_id,))
        return self.cursor.fetchall()

    def get_referrer_info(self, user_id):
        """获取用户的邀请者信息"""
        user_data = self.get_user_by_id(user_id)
        if user_data and user_data[2]:  # referred_by 不为 None
            referrer_id = user_data[2]
            referrer_data = self.get_user_by_id(referrer_id)
            return referrer_data
        return None

    def get_referrer_id_for_member(self, user_id: int):
        """获取成员的邀请者 user_id（来自 users.referred_by）。"""
        self.cursor.execute('''SELECT referred_by FROM users WHERE user_id = ?''', (user_id,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def update_user_role(self, user_id: int, role_id: int | None):
        """更新用户在 users 表中的当前角色ID。"""
        self.cursor.execute('''UPDATE users SET role_id = ? WHERE user_id = ?''', (role_id, user_id))
        self.conn.commit()

    def adjust_reward_balance(self, user_id: int, delta: float) -> float:
        """调整用户余额（可正可负），返回调整后的余额。若用户不存在则创建用户后再调整。"""
        user = self.get_user_by_id(user_id)
        if not user:
            # 初始化用户以确保有余额字段
            self.add_or_update_user(user_id=user_id, username=None)
            user = self.get_user_by_id(user_id)
        current_balance = float(user[4] or 0)
        new_balance = current_balance + float(delta)
        if new_balance < 0:
            new_balance = 0.0
        self.cursor.execute('''UPDATE users SET reward_balance = ? WHERE user_id = ?''', (new_balance, user_id))
        self.conn.commit()
        logging.info(f"User {user_id} balance adjusted by {delta}, new balance={new_balance}.")
        return new_balance

    def get_positive_balance_users(self):
        """获取所有余额>0的用户，返回 (user_id, username, reward_balance, role_id) 列表，按余额降序。"""
        self.cursor.execute(
            '''SELECT user_id, username, reward_balance, role_id FROM users WHERE reward_balance > 0 ORDER BY reward_balance DESC'''
        )
        return self.cursor.fetchall()

    # 邀请事件与结算
    def add_referral_event(self, inviter_id: int, invite_code: str, new_member_id: int, joined_at: str, commission_amount: float, role_id: int | None = None):
        self.cursor.execute(
            '''INSERT INTO referral_events (inviter_id, invite_code, new_member_id, joined_at, commission_amount, settled, role_id)
               VALUES (?, ?, ?, ?, ?, 0, ?)''',
            (inviter_id, invite_code, new_member_id, joined_at, commission_amount, role_id)
        )
        self.conn.commit()

    def has_reward_for_member(self, new_member_id: int) -> bool:
        """检查该新成员是否已经产生过佣金事件，防止重复计佣。"""
        self.cursor.execute('''SELECT 1 FROM referral_events WHERE new_member_id = ? LIMIT 1''', (new_member_id,))
        return self.cursor.fetchone() is not None

    def has_reward_for_member_role(self, new_member_id: int, role_id: int) -> bool:
        """检查该新成员在指定角色层级是否已经产生过佣金事件（用于分段升级计佣防重复）。"""
        try:
            self.cursor.execute(
                '''SELECT 1 FROM referral_events WHERE new_member_id = ? AND role_id = ? LIMIT 1''',
                (new_member_id, role_id)
            )
            return self.cursor.fetchone() is not None
        except Exception:
            return False

    def get_commission_stats(self, user_id: int):
        # total
        self.cursor.execute('''SELECT COALESCE(SUM(commission_amount), 0) FROM referral_events WHERE inviter_id = ?''', (user_id,))
        total = float(self.cursor.fetchone()[0] or 0)
        # settled
        self.cursor.execute('''SELECT COALESCE(SUM(commission_amount), 0) FROM referral_events WHERE inviter_id = ? AND settled = 1''', (user_id,))
        settled = float(self.cursor.fetchone()[0] or 0)
        unsettled = total - settled
        return total, settled, unsettled

    def get_recent_referral_events(self, inviter_id: int, limit: int = 10):
        """获取最近的佣金产生事件（升组触发）。返回 new_member_id, joined_at, commission_amount, settled, role_id。"""
        self.cursor.execute(
            '''SELECT new_member_id, joined_at, commission_amount, settled, role_id FROM referral_events
               WHERE inviter_id = ? ORDER BY id DESC LIMIT ?''',
            (inviter_id, limit)
        )
        return self.cursor.fetchall()

    def get_recent_payouts(self, user_id: int, limit: int = 10):
        """获取最近的结算记录。返回 amount, created_at, note。"""
        self.cursor.execute(
            '''SELECT amount, created_at, note FROM payouts WHERE user_id = ? ORDER BY id DESC LIMIT ?''',
            (user_id, limit)
        )
        return self.cursor.fetchall()

    # 自拉自数据清理
    def purge_all_self_invites(self):
        """全局清理自拉自：
        - users 表：user_id = referred_by 的记录置空 referred_by
        - referral_events 表：删除 inviter_id = new_member_id 的事件
        """
        try:
            self.cursor.execute('''UPDATE users SET referred_by = NULL WHERE user_id = referred_by''')
            self.cursor.execute('''DELETE FROM referral_events WHERE inviter_id = new_member_id''')
            self.conn.commit()
            logging.info("Purged global self-invite associations and events.")
        except Exception as exc:
            logging.error(f"Failed to purge global self-invites: {exc}")

    def purge_self_invites_for_user(self, user_id: int):
        """按用户清理自拉自数据。"""
        try:
            self.cursor.execute('''UPDATE users SET referred_by = NULL WHERE user_id = ? AND referred_by = ?''', (user_id, user_id))
            self.cursor.execute('''DELETE FROM referral_events WHERE inviter_id = ? AND new_member_id = ?''', (user_id, user_id))
            self.conn.commit()
            logging.info(f"Purged self-invite data for user {user_id}.")
        except Exception as exc:
            logging.error(f"Failed to purge self-invites for user {user_id}: {exc}")

    def settle_user_amount(self, user_id: int, amount: float) -> float:
        """按时间顺序将 referral_events 标记为已结算，返回实际结算金额，并写 payouts 记录。"""
        remaining = float(amount)
        settled_sum = 0.0
        # 找出未结算事件
        self.cursor.execute('''SELECT id, commission_amount FROM referral_events WHERE inviter_id = ? AND settled = 0 ORDER BY id ASC''', (user_id,))
        rows = self.cursor.fetchall()
        for event_id, commission in rows:
            if remaining <= 0:
                break
            take = min(commission, remaining)
            if take >= commission:
                # 整条事件结算
                self.cursor.execute('''UPDATE referral_events SET settled = 1 WHERE id = ?''', (event_id,))
            else:
                # 局部结算：将原事件金额缩小为已结算部分并标记已结算，再插入一条未结算的余数事件
                self.cursor.execute('''UPDATE referral_events SET commission_amount = ?, settled = 1 WHERE id = ?''', (take, event_id))
                self.cursor.execute(
                    '''INSERT INTO referral_events (inviter_id, invite_code, new_member_id, joined_at, commission_amount, settled)
                       SELECT inviter_id, invite_code, new_member_id, joined_at, ?, 0 FROM referral_events WHERE id = ?''',
                    (commission - take, event_id)
                )
            remaining -= take
            settled_sum += take
        if settled_sum > 0:
            # 写 payouts
            import datetime
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.cursor.execute('''INSERT INTO payouts (user_id, amount, created_at, note) VALUES (?, ?, ?, ?)''', (user_id, settled_sum, now, 'manual settle'))
            # 扣减余额
            self.cursor.execute('''UPDATE users SET reward_balance = COALESCE(reward_balance, 0) - ? WHERE user_id = ?''', (settled_sum, user_id))
            self.conn.commit()
        return settled_sum

    def close(self):
        if getattr(self, "conn", None):
            self.conn.close()
            logging.debug("Database connection closed.")
            self.conn = None

