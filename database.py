import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from config import DATABASE_PATH

class DatabaseManager:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self.init_database()
    
    def init_database(self):
        """Initialize database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                );
                
                CREATE TABLE IF NOT EXISTS telegram_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    phone_number TEXT NOT NULL,
                    api_id INTEGER NOT NULL,
                    api_hash TEXT NOT NULL,
                    session_name TEXT NOT NULL,
                    account_name TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    is_connected BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    UNIQUE(user_id, phone_number)
                );
                
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    target_channel_id TEXT NOT NULL,
                    target_channel_name TEXT,
                    source_channel_id TEXT,
                    source_channel_name TEXT,
                    assigned_account_id INTEGER,
                    offer_post_content TEXT,
                    offer_post_media TEXT,
                    offer_post_buttons TEXT,
                    offer_post_entities TEXT,  -- New field for storing message entities
                    last_post_id INTEGER,
                    offer_post_id INTEGER,
                    last_source_message_id INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (assigned_account_id) REFERENCES telegram_accounts (id)
                );
                
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_id INTEGER,
                    account_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    status TEXT DEFAULT 'success',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (channel_id) REFERENCES channels (id),
                    FOREIGN KEY (account_id) REFERENCES telegram_accounts (id)
                );
                
                CREATE TABLE IF NOT EXISTS user_states (
                    user_id INTEGER PRIMARY KEY,
                    state TEXT,
                    data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels(user_id);
                CREATE INDEX IF NOT EXISTS idx_channels_active ON channels(is_active);
                CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON telegram_accounts(user_id);
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_channels_assigned_account ON channels(assigned_account_id);
            ''')
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None):
        """Add or update user in database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
    
    def add_telegram_account(self, user_id: int, phone_number: str, api_id: int, api_hash: str, 
                           session_name: str, account_name: str = None) -> int:
        """Add new Telegram account"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                INSERT INTO telegram_accounts (user_id, phone_number, api_id, api_hash, session_name, account_name)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, phone_number, api_id, api_hash, session_name, account_name or f"Account {phone_number}"))
            return cursor.lastrowid
    
    def get_user_accounts(self, user_id: int) -> List[Dict]:
        """Get all accounts for user"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM telegram_accounts 
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_account(self, account_id: int) -> Optional[Dict]:
        """Get specific account"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('SELECT * FROM telegram_accounts WHERE id = ?', (account_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_account_status(self, account_id: int, is_connected: bool):
        """Update account connection status"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE telegram_accounts 
                SET is_connected = ?, last_used = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (is_connected, account_id))
    
    def delete_account(self, account_id: int):
        """Soft delete account (set is_active to 0)"""
        with sqlite3.connect(self.db_path) as conn:
            # First, unassign from all channels
            conn.execute('''
                UPDATE channels 
                SET assigned_account_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE assigned_account_id = ?
            ''', (account_id,))
            
            # Then soft delete the account
            conn.execute('UPDATE telegram_accounts SET is_active = 0 WHERE id = ?', (account_id,))
    
    def unlink_account_from_channel(self, channel_id: int):
        """Unlink account from channel"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET assigned_account_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (channel_id,))
    
    def delete_offer_post(self, channel_id: int):
        """Delete offer post content from channel"""
        # Установить соединение с базой данных
        with sqlite3.connect(self.db_path) as conn:
            # Сбросить данные офер поста
            conn.execute('''
                UPDATE channels 
                SET offer_post_content = NULL, 
                    offer_post_media = NULL, 
                    offer_post_buttons = NULL,
                    offer_post_entities = NULL,
                    offer_post_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (channel_id,))

    def update_offer_post(self, channel_id: int, content: str = None, media: str = None, entities: str = None):
        """Update offer post content for specific channel with entities support"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET offer_post_content = ?, offer_post_media = ?, offer_post_entities = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (content, media, entities, channel_id))

    def get_channels_with_offer_posts(self, user_id: int) -> List[Dict]:
        """Get channels that have offer posts configured"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT c.*, a.account_name, a.is_connected as account_connected
                FROM channels c
                LEFT JOIN telegram_accounts a ON c.assigned_account_id = a.id AND a.is_active = 1
                WHERE c.user_id = ? AND c.offer_post_content IS NOT NULL
                ORDER BY c.created_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def add_channel(self, user_id: int, target_channel_id: str, target_channel_name: str = None) -> int:
        """Add new channel configuration"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                INSERT INTO channels (user_id, target_channel_id, target_channel_name)
                VALUES (?, ?, ?)
            ''', (user_id, target_channel_id, target_channel_name))
            return cursor.lastrowid
    
    def update_offer_post_buttons(self, channel_id: int, buttons: str = None):
        """Update offer post buttons for specific channel"""
        # Установить соединение с базой данных
        with sqlite3.connect(self.db_path) as conn:
            # Обновить данные кнопок
            conn.execute('''
                UPDATE channels 
                SET offer_post_buttons = ?, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (buttons, channel_id))
    
    def update_channel_source(self, channel_id: int, source_channel_id: str, source_channel_name: str = None):
        """Update source channel for existing channel configuration"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET source_channel_id = ?, source_channel_name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (source_channel_id, source_channel_name, channel_id))
    
    def assign_account_to_channel(self, channel_id: int, account_id: int):
        """Assign account to channel"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET assigned_account_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (account_id, channel_id))
    
    def get_user_channels(self, user_id: int) -> List[Dict]:
        """Get all channels for user with account info"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT c.*, a.account_name, a.phone_number, a.is_connected as account_connected
                FROM channels c
                LEFT JOIN telegram_accounts a ON c.assigned_account_id = a.id AND a.is_active = 1
                WHERE c.user_id = ? AND c.is_active = 1
                ORDER BY c.created_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_channel(self, channel_id: int) -> Optional[Dict]:
        """Get specific channel configuration with account info"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT c.*, a.account_name, a.phone_number, a.is_connected as account_connected
                FROM channels c
                LEFT JOIN telegram_accounts a ON c.assigned_account_id = a.id AND a.is_active = 1
                WHERE c.id = ?
            ''', (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_active_channels_with_accounts(self) -> List[Dict]:
        """Get all active channels with assigned accounts for monitoring"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT c.*, a.phone_number, a.api_id, a.api_hash, a.session_name, a.account_name
                FROM channels c
                JOIN telegram_accounts a ON c.assigned_account_id = a.id
                WHERE c.is_active = 1 AND c.source_channel_id IS NOT NULL 
                AND a.is_active = 1 AND a.is_connected = 1
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def update_channel_status(self, channel_id: int, is_active: bool):
        """Update channel active status (pause/resume instead of delete)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (is_active, channel_id))
    
    def update_last_post_id(self, channel_id: int, post_id: int):
        """Update last post ID for channel"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET last_post_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (post_id, channel_id))
    
    def update_offer_post_id(self, channel_id: int, post_id: int):
        """Update offer post ID for channel"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET offer_post_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (post_id, channel_id))
    
    def update_last_source_message_id(self, channel_id: int, message_id: int):
        """Update last processed source message ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE channels 
                SET last_source_message_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (message_id, channel_id))
    
    def delete_channel(self, channel_id: int):
        """Completely delete channel configuration"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    
    def add_log(self, user_id: int = None, channel_id: int = None, account_id: int = None,
                action: str = '', details: str = '', status: str = 'success'):
        """Add log entry"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO logs (user_id, channel_id, account_id, action, details, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, channel_id, account_id, action, details, status))
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Get user statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT 
                    COUNT(*) as total_channels,
                    COUNT(CASE WHEN is_active = 1 THEN 1 END) as active_channels,
                    COUNT(CASE WHEN source_channel_id IS NOT NULL THEN 1 END) as configured_channels
                FROM channels 
                WHERE user_id = ?
            ''', (user_id,))
            channel_stats = cursor.fetchone()
            
            cursor = conn.execute('''
                SELECT 
                    COUNT(*) as total_accounts,
                    COUNT(CASE WHEN is_connected = 1 THEN 1 END) as connected_accounts
                FROM telegram_accounts 
                WHERE user_id = ? AND is_active = 1
            ''', (user_id,))
            account_stats = cursor.fetchone()
            
            cursor = conn.execute('''
                SELECT COUNT(*) as total_actions
                FROM logs 
                WHERE user_id = ? AND timestamp >= datetime('now', '-30 days')
            ''', (user_id,))
            actions = cursor.fetchone()
            
            return {
                'total_channels': channel_stats[0] if channel_stats else 0,
                'active_channels': channel_stats[1] if channel_stats else 0,
                'configured_channels': channel_stats[2] if channel_stats else 0,
                'total_accounts': account_stats[0] if account_stats else 0,
                'connected_accounts': account_stats[1] if account_stats else 0,
                'actions_last_30_days': actions[0] if actions else 0
            }
    
    def set_user_state(self, user_id: int, state: str, data: Dict = None):
        """Set user state for conversation flow"""
        data_json = json.dumps(data) if data else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_states (user_id, state, data, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, state, data_json))
    
    def get_user_state(self, user_id: int) -> Optional[Dict]:
        """Get user state"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT state, data FROM user_states WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row[1]) if row[1] else {}
                return {'state': row[0], 'data': data}
            return None
    
    def clear_user_state(self, user_id: int):
        """Clear user state"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM user_states WHERE user_id = ?', (user_id,))