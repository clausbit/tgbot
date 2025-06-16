import asyncio
import logging
import json
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from pathlib import Path

from telegram import (
    Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    Message, Chat, ChatMember
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError, Forbidden, BadRequest

from config import BOT_TOKEN, NOTIFICATION_CHAT_ID, EMOJIS, MONITORING_INTERVAL
from database import DatabaseManager
from telegram_client_manager import TelegramClientManager

# Configure logging with rotation
import logging.handlers

def setup_logging():
    """Setup logging with file rotation"""
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Rotating file handler (2MB max, keep 3 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        'bot.log', 
        maxBytes=2*1024*1024,  # 2MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler]
    )

# Call setup function
setup_logging()
logger = logging.getLogger(__name__)

class TelegramChannelBot:
    def __init__(self):
        self.db = DatabaseManager()
        self.client_manager = TelegramClientManager(self.db)
        self.bot = None
        self.application = None
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        self.db.add_user(user.id, user.username, user.first_name)
        self.db.clear_user_state(user.id)
        
        welcome_text = f"""
🎯 <b>Добро пожаловать в продвинутый бот управления каналами!</b>

Привет, {user.first_name}! Теперь бот использует <b>пользовательские аккаунты Telegram</b> для полного контроля над каналами!

<b>🚀 Новые возможности:</b>
• Добавление ваших Telegram аккаунтов (по номеру + API)
• Полный доступ к любым каналам через ваши аккаунты
• Назначение конкретного аккаунта для каждого канала
• РЕДАКТИРОВАНИЕ постов (не создание новых!)
• Управление рекламными постами
• Мониторинг в реальном времени

<b>📋 Алгоритм работы:</b>
1. Ваш аккаунт мониторит исходный канал
2. При новом посте → копирует содержимое
3. РЕДАКТИРУЕТ последний пост в целевом канале
4. Удаляет старый рекламный пост
5. Создает новый рекламный пост (всегда последний)

<b>🔧 Пошаговая настройка:</b>
1. Добавьте ваш Telegram аккаунт
2. Настройте целевой канал
3. Укажите исходный канал
4. Назначьте аккаунт для работы с каналами
5. Установите рекламный пост

Используйте кнопки ниже для управления:
        """
        
        keyboard = self.get_main_keyboard()
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        
        self.db.add_log(user.id, action='start_command', details='User started bot')
    
    def get_main_keyboard(self) -> ReplyKeyboardMarkup:
        """Get main reply keyboard"""
        keyboard = [
            [
                KeyboardButton(f"{EMOJIS['accounts']} Мои аккаунты"),
                KeyboardButton(f"{EMOJIS['account']} Добавить аккаунт")
            ],
            [
                KeyboardButton(f"{EMOJIS['add']} Добавить целевой канал"),
                KeyboardButton(f"{EMOJIS['source']} Указать исходный канал")
            ],
            [
                KeyboardButton(f"{EMOJIS['offer']} Установить рекламный пост"),
                KeyboardButton(f"{EMOJIS['offer']} Управление рекламой")
            ],
            [
                KeyboardButton(f"{EMOJIS['link']} Назначить аккаунт каналу"),
                KeyboardButton(f"{EMOJIS['channels']} Все каналы")
            ],
            [
                KeyboardButton(f"{EMOJIS['stats']} Статистика"),
                KeyboardButton(f"{EMOJIS['help']} Помощь")
            ]
        ]

        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages and button presses"""
        if not update.effective_user:
            return
            
        user_id = update.effective_user.id
        
        # Handle media messages for offer post setup
        if not update.message.text:
            await self.handle_state_input(update, context)
            return
            
        text = update.message.text
        
        # Handle main menu buttons
        if text.startswith(f"{EMOJIS['account']} Добавить аккаунт"):
            await self.add_telegram_account(update, context)
        elif text.startswith(f"{EMOJIS['offer']} Управление"):
            await self.manage_offer_posts(update, context)
        elif text.startswith(f"{EMOJIS['accounts']} Мои аккаунты"):
            await self.view_accounts(update, context)
        elif text.startswith(f"{EMOJIS['add']} Добавить"):
            await self.add_target_channel(update, context)
        elif text.startswith(f"{EMOJIS['source']} Указать"):
            await self.set_source_channel(update, context)
        elif text.startswith(f"{EMOJIS['offer']} Установить"):
            await self.set_offer_post(update, context)
        elif text.startswith(f"{EMOJIS['link']} Назначить"):
            await self.assign_account_to_channel(update, context)
        elif text.startswith(f"{EMOJIS['channels']} Все каналы"):
            await self.view_all_channels(update, context)
        elif text.startswith(f"{EMOJIS['stats']} Статистика"):
            await self.show_statistics(update, context)
        elif text.startswith(f"{EMOJIS['help']} Помощь"):
            await self.show_help(update, context)
        else:
            await self.handle_state_input(update, context)
    
    async def add_telegram_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start adding Telegram account process"""
        user_id = update.effective_user.id
        
        text = f"""
{EMOJIS['account']} <b>Добавление Telegram аккаунта</b>

Для работы с каналами нужно добавить ваш Telegram аккаунт.

<b>Что потребуется:</b>
• Номер телефона (с кодом страны, например: +380123456789)
• API ID и API Hash (получить на my.telegram.org)
• Код подтверждения из SMS
• Пароль двухфакторной аутентификации (если включен)

<b>Безопасность:</b>
• Данные хранятся локально в зашифрованном виде
• Используется официальный Telegram Client API
• Полный контроль остается у вас

Отправьте номер телефона в формате: +380123456789
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")]
        ])
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        self.db.set_user_state(user_id, 'waiting_phone_number')
    
    async def view_accounts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View all user accounts"""
        user_id = update.effective_user.id
        accounts = self.db.get_user_accounts(user_id)
        
        text = f"{EMOJIS['accounts']} <b>Ваши Telegram аккаунты:</b>\n\n"
        
        if not accounts:
            text += f"{EMOJIS['info']} У вас пока нет добавленных аккаунтов.\n\n"
        
        keyboard = []
        for i, account in enumerate(accounts, 1):
            status = "🟢 Подключен" if account['is_connected'] else "🔴 Отключен"
            text += f"<b>{i}. {account['account_name']}</b>\n"
            text += f"   Телефон: {account['phone_number']}\n"
            text += f"   Статус: {status}\n"
            text += f"   Добавлен: {account['created_at'][:10]}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"⚙️ {account['account_name'][:20]}",
                    callback_data=f"manage_account_{account['id']}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                f"{EMOJIS['account']} Добавить аккаунт",
                callback_data="add_account"
            )
        ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def view_all_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View all channels with detailed info"""
        user_id = update.effective_user.id
        channels = self.db.get_user_channels(user_id)
        
        if not channels:
            await update.message.reply_text(
                f"{EMOJIS['info']} У вас пока нет настроенных каналов.",
                parse_mode=ParseMode.HTML
            )
            return
        
        text = f"{EMOJIS['channels']} <b>Все ваши каналы:</b>\n\n"
        
        for i, channel in enumerate(channels, 1):
            status = "🟢 Активен" if channel['is_active'] else "🔴 Приостановлен"
            target_name = channel['target_channel_name'] or channel['target_channel_id']
            source_name = channel['source_channel_name'] or "Не настроен"
            account_name = channel['account_name'] or "Не назначен"
            account_status = "🟢" if channel['account_connected'] else "🔴" if channel['account_name'] else "⚪"
            
            text += f"<b>{i}. {target_name}</b>\n"
            text += f"   Статус: {status}\n"
            text += f"   Исходный: {source_name}\n"
            text += f"   Аккаунт: {account_status} {account_name}\n"
            text += f"   Рекламный пост: {'✅' if channel['offer_post_content'] else '❌'}\n\n"
        
        keyboard = []
        for channel in channels:
            channel_name = channel['target_channel_name'] or channel['target_channel_id']
            keyboard.append([
                InlineKeyboardButton(
                    f"⚙️ {channel_name[:25]}",
                    callback_data=f"manage_channel_{channel['id']}"
                )
            ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def manage_offer_posts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manage offer posts - view and delete"""
        # Initialize user and channel data
        user_id = update.effective_user.id
        channels = self.db.get_user_channels(user_id)
        channels_with_offers = [ch for ch in channels if ch['offer_post_content']]

        # Check if there are any offer posts
        if not channels_with_offers:
            await update.message.reply_text(
                f"{EMOJIS['info']} У вас нет настроенных рекламных постов.",
                parse_mode=ParseMode.HTML
            )
            return

        # Build response text and keyboard
        text = f"{EMOJIS['offer']} <b>Управление рекламными постами:</b>\n\n"
        keyboard = []

        for i, channel in enumerate(channels_with_offers, 1):
            channel_name = channel['target_channel_name'] or channel['target_channel_id']
            offer_preview = channel['offer_post_content'][:50] + "..." if len(channel['offer_post_content']) > 50 else channel['offer_post_content']

            # Add channel details to response text
            text += f"<b>{i}. {channel_name}</b>\n"
            text += f"   Контент: {offer_preview}\n"
            text += f"   Медиа: {'✅' if channel['offer_post_media'] else '❌'}\n\n"

            # Add buttons for channel actions
            keyboard.append([
                InlineKeyboardButton(f"👁️ {channel_name[:15]}", callback_data=f"preview_offer_{channel['id']}"),
                InlineKeyboardButton(f"🗑️ Удалить", callback_data=f"delete_offer_{channel['id']}")
            ])

        # Add cancel button
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['cancel']} Закрыть", callback_data="cancel")])

        # Send response
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def preview_offer_post(self, query, channel_id: int):
        """Preview offer post with enhanced display and entities support"""
        # Fetch channel data
        channel = self.db.get_channel(channel_id)
        if not channel or not channel['offer_post_content']:
            await query.edit_message_text("Рекламный пост не найден.")
            return

        # Parse entities if they exist
        entities_info = "❌ Нет"
        if channel.get('offer_post_entities'):
            entities = json.loads(channel['offer_post_entities'])
            if entities:
                entities_types = {entity['type'] for entity in entities}
                entities_info = f"✅ ({', '.join(entities_types)})"

        # Build preview text
        preview_text = f"""
👁️ <b>Предварительный просмотр рекламного поста</b>

<b>Канал:</b> {channel['target_channel_name'] or channel['target_channel_id']}

<b>Содержимое:</b>
{channel['offer_post_content']}

<b>Форматирование:</b> {entities_info}

<b>Медиа:</b> {'✅ Есть' if channel['offer_post_media'] else '❌ Нет'}
        """

        # Build keyboard
        keyboard = [
            [
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit_offer_{channel_id}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_offer_{channel_id}")
            ],
            [InlineKeyboardButton("❌ Закрыть", callback_data="cancel")]
        ]

        # Send preview
        await query.edit_message_text(
            preview_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def delete_offer_post(self, query, channel_id: int):
        """Delete offer post from database"""
        try:
            # Delete from database
            self.db.delete_offer_post(channel_id)

            # Fetch channel details
            channel = self.db.get_channel(channel_id)
            channel_name = channel['target_channel_name'] if channel else 'Неизвестный канал'

            # Send success message
            await query.edit_message_text(
                f"{EMOJIS['success']} Рекламный пост для канала <b>{channel_name}</b> удален из базы данных.\n\n"
                f"Теперь вы можете настроить новый рекламный пост.",
                parse_mode=ParseMode.HTML
            )

            # Log the action
            if channel:
                self.db.add_log(
                    channel['user_id'],
                    channel_id,
                    action='delete_offer_post',
                    details=f'Deleted offer post for channel {channel_name}'
                )

        except Exception as e:
            logger.error(f"Error deleting offer post: {e}")
            await query.edit_message_text(
                f"{EMOJIS['error']} Ошибка при удалении рекламного поста: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def assign_account_to_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Assign account to channel"""
        user_id = update.effective_user.id
        channels = self.db.get_user_channels(user_id)
        accounts = self.db.get_user_accounts(user_id)
        
        if not channels:
            await update.message.reply_text(
                f"{EMOJIS['warning']} Сначала добавьте целевой канал!",
                parse_mode=ParseMode.HTML
            )
            return
        
        if not accounts:
            await update.message.reply_text(
                f"{EMOJIS['warning']} Сначала добавьте Telegram аккаунт!",
                parse_mode=ParseMode.HTML
            )
            return
        
        keyboard = []
        for channel in channels:
            channel_name = channel['target_channel_name'] or channel['target_channel_id']
            current_account = channel['account_name'] or "Не назначен"
            keyboard.append([
                InlineKeyboardButton(
                    f"🔗 {channel_name} ({current_account})",
                    callback_data=f"assign_to_channel_{channel['id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")])
        
        await update.message.reply_text(
            f"{EMOJIS['link']} <b>Выберите канал для назначения аккаунта:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def add_target_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start adding target channel process"""
        user_id = update.effective_user.id
        
        text = f"""
{EMOJIS['add']} <b>Добавление целевого канала</b>

Отправьте ID или ссылку на канал, где я буду управлять постами.

<b>Требования:</b>
• Я должен быть администратором канала
• У меня должны быть права на редактирование и удаление сообщений

<b>Форматы:</b>
• @channel_username
• https://t.me/channel_username
• -1001234567890 (ID канала)

Отправьте канал или нажмите "Отмена":
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")]
        ])
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        self.db.set_user_state(user_id, 'waiting_target_channel')
    
    async def set_source_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start setting source channel process"""
        user_id = update.effective_user.id
        channels = self.db.get_user_channels(user_id)
        
        if not channels:
            await update.message.reply_text(
                f"{EMOJIS['warning']} Сначала добавьте целевой канал!",
                parse_mode=ParseMode.HTML
            )
            return
        
        keyboard = []
        for channel in channels:
            channel_name = channel['target_channel_name'] or channel['target_channel_id']
            keyboard.append([
                InlineKeyboardButton(
                    f"📺 {channel_name}",
                    callback_data=f"select_channel_for_source_{channel['id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")])
        
        await update.message.reply_text(
            f"{EMOJIS['source']} <b>Выберите целевой канал для настройки исходного канала:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def set_offer_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start setting offer post process"""
        user_id = update.effective_user.id
        channels = self.db.get_user_channels(user_id)
        
        if not channels:
            await update.message.reply_text(
                f"{EMOJIS['warning']} Сначала добавьте целевой канал!",
                parse_mode=ParseMode.HTML
            )
            return
        
        keyboard = []
        for channel in channels:
            channel_name = channel['target_channel_name'] or channel['target_channel_id']
            offer_status = "✅" if channel['offer_post_content'] else "❌"
            keyboard.append([
                InlineKeyboardButton(
                    f"🎯 {channel_name} {offer_status}",
                    callback_data=f"select_channel_for_offer_{channel['id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")])
        
        await update.message.reply_text(
            f"{EMOJIS['offer']} <b>Выберите канал для настройки рекламного поста:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def view_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current settings with management options"""
        user_id = update.effective_user.id
        channels = self.db.get_user_channels(user_id)
        
        if not channels:
            await update.message.reply_text(
                f"{EMOJIS['info']} У вас пока нет настроенных каналов.",
                parse_mode=ParseMode.HTML
            )
            return
        
        text = f"{EMOJIS['settings']} <b>Управление каналами:</b>\n\n"
        
        active_count = 0
        for i, channel in enumerate(channels, 1):
            status = "🟢 Активен" if channel['is_active'] else "🔴 Приостановлен"
            if channel['is_active']:
                active_count += 1
            target_name = channel['target_channel_name'] or channel['target_channel_id']
            source_name = channel['source_channel_name'] or channel['source_channel_id'] or "Не настроен"
            
            text += f"<b>{i}. {target_name[:30]}</b>\n"
            text += f"   Статус: {status}\n"
            text += f"   Исходный: {source_name[:30]}\n"
            text += f"   Рекламный пост: {'✅ Настроен' if channel['offer_post_content'] else '❌ Не настроен'}\n\n"
        
        text += f"<b>Всего каналов:</b> {len(channels)}\n"
        text += f"<b>Активных:</b> {active_count}\n"
        
        keyboard = []
        for channel in channels:
            channel_name = channel['target_channel_name'] or channel['target_channel_id']
            status_emoji = "🟢" if channel['is_active'] else "🔴"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status_emoji} {channel_name[:20]}",
                    callback_data=f"manage_channel_{channel['id']}"
                )
            ])
        
        # Add global controls
        keyboard.append([
            InlineKeyboardButton("⏸️ Приостановить все", callback_data="pause_all"),
            InlineKeyboardButton("▶️ Запустить все", callback_data="resume_all")
        ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show enhanced statistics"""
        user_id = update.effective_user.id
        stats = self.db.get_user_stats(user_id)
        
        text = f"""
{EMOJIS['stats']} <b>Ваша статистика:</b>

👥 <b>Аккаунты:</b>
• Всего аккаунтов: {stats['total_accounts']}
• Подключенных: {stats['connected_accounts']}

📺 <b>Каналы:</b>
• Всего каналов: {stats['total_channels']}
• Активных каналов: {stats['active_channels']}
• Настроенных каналов: {stats['configured_channels']}

📈 <b>Активность:</b>
• Действий за 30 дней: {stats['actions_last_30_days']}

🕐 <b>Последнее обновление:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
        """
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show enhanced help information"""
        text = f"""
{EMOJIS['help']} <b>Помощь по использованию бота</b>

<b>🎯 Основные функции:</b>
• Использование ваших Telegram аккаунтов для полного контроля
• Мониторинг исходных каналов в реальном времени
• РЕДАКТИРОВАНИЕ постов (не создание новых!)
• Автоматическое управление рекламными постами
• Назначение конкретных аккаунтов для каждого канала

<b>📋 Алгоритм работы:</b>
1. Ваш аккаунт мониторит исходный канал
2. При появлении нового поста:
   • Копирует содержимое нового поста
   • Находит последний НЕ-рекламный пост в целевом канале
   • РЕДАКТИРУЕТ этот пост, заменяя содержимое
   • Удаляет старый рекламный пост
   • Создает новый рекламный пост (всегда последний)

<b>⚙️ Пошаговая настройка:</b>
1. Добавьте ваш Telegram аккаунт (номер + API данные)
2. Добавьте целевой канал
3. Укажите исходный канал для мониторинга
4. Назначьте аккаунт для работы с каналами
5. Установите рекламный пост
6. Бот автоматически начнет работу

<b>🔧 Получение API данных:</b>
1. Перейдите на https://my.telegram.org
2. Войдите с вашим номером телефона
3. Перейдите в "API development tools"
4. Создайте приложение (любое название)
5. Скопируйте API ID и API Hash

<b>🔒 Безопасность:</b>
• Данные хранятся локально в зашифрованном виде
• Используется официальный Telegram Client API
• Полный контроль остается у вас

<b>❓ Поддержка:</b>
Если возникли проблемы, проверьте подключение аккаунтов и настройки каналов.
        """
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks"""
        # Инициализация данных
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = query.from_user.id

        # Обработка callback'ов
        if data == "cancel":
            self.db.clear_user_state(user_id)
            await query.edit_message_text(
                f"{EMOJIS['cancel']} Операция отменена.",
                parse_mode=ParseMode.HTML
            )
        elif data == "add_account":
            await self.add_telegram_account_callback(query, context)
        elif data.startswith("manage_account_"):
            account_id = int(data.split("_")[-1])
            await self.show_account_management(query, account_id)
        elif data.startswith("preview_offer_"):
            channel_id = int(data.split("_")[-1])
            await self.preview_offer_post(query, channel_id)
        elif data.startswith("delete_offer_"):
            channel_id = int(data.split("_")[-1])
            await self.delete_offer_post(query, channel_id)
        elif data.startswith("edit_offer_"):
            channel_id = int(data.split("_")[-1])
            await self.handle_offer_post_selection(query, channel_id)
        elif data.startswith("unlink_from_channel_"):
            channel_id = int(data.split("_")[-1])
            await self.unlink_account_from_channel_confirm(query, channel_id)
        elif data.startswith("assign_to_channel_"):
            channel_id = int(data.split("_")[-1])
            await self.show_account_selection_for_channel(query, channel_id)
        elif data.startswith("assign_account_"):
            parts = data.split("_")
            account_id = int(parts[2])
            channel_id = int(parts[3])
            await self.assign_account_to_channel_confirm(query, account_id, channel_id)
        elif data.startswith("connect_account_"):
            account_id = int(data.split("_")[-1])
            await self.connect_account(query, account_id)
        elif data.startswith("disconnect_account_"):
            account_id = int(data.split("_")[-1])
            await self.disconnect_account(query, account_id)
        elif data.startswith("delete_account_"):
            account_id = int(data.split("_")[-1])
            await self.delete_account(query, account_id)
        elif data.startswith("select_channel_for_source_"):
            channel_id = int(data.split("_")[-1])
            await self.handle_source_channel_selection(query, channel_id)
        elif data.startswith("select_channel_for_offer_"):
            channel_id = int(data.split("_")[-1])
            await self.handle_offer_post_selection(query, channel_id)
        elif data.startswith("manage_channel_"):
            channel_id = int(data.split("_")[-1])
            await self.show_channel_management(query, channel_id)
        elif data.startswith("edit_channel_"):
            channel_id = int(data.split("_")[-1])
            await self.handle_edit_channel_selection(query, channel_id)
        elif data.startswith("edit_source_"):
            channel_id = int(data.split("_")[-1])
            await self.handle_source_channel_selection(query, channel_id)
        elif data.startswith("confirm_"):
            await self.handle_confirmation(query, data)
        elif data.startswith("toggle_channel_"):
            channel_id = int(data.split("_")[-1])
            await self.toggle_channel_status(query, channel_id)
        elif data.startswith("delete_channel_"):
            channel_id = int(data.split("_")[-1])
            await self.delete_channel(query, channel_id)
    
    async def unlink_account_from_channel_confirm(self, query, channel_id: int):
        """Confirm unlinking account from channel"""
        try:
            # Unlink account from channel
            success = await self.client_manager.unlink_account_from_channel(channel_id)
            
            if success:
                channel = self.db.get_channel(channel_id)
                channel_name = channel['target_channel_name'] if channel else 'Неизвестный канал'
                
                await query.edit_message_text(
                    f"{EMOJIS['success']} Аккаунт успешно отвязан от канала <b>{channel_name}</b>.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await query.edit_message_text(
                    f"{EMOJIS['error']} Ошибка при отвязке аккаунта.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Error unlinking account from channel {channel_id}: {e}")
            await query.edit_message_text(
                f"{EMOJIS['error']} Ошибка: {str(e)}",
                parse_mode=ParseMode.HTML
            )
            return
        
        keyboard = []
        for channel in channels_with_accounts:
            channel_name = channel['target_channel_name'] or channel['target_channel_id'] 
            account_name = channel['account_name'] or "Неизвестный аккаунт"
            keyboard.append([
                InlineKeyboardButton(
                    f"🔗 {channel_name} ({account_name})",
                    callback_data=f"unlink_from_channel_{channel['id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")])
        
        await update.message.reply_text(
            f"{EMOJIS['link']} <b>Выберите канал для отвязки аккаунта:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def add_telegram_account_callback(self, query, context):
        """Handle add account callback"""
        text = f"""
{EMOJIS['account']} <b>Добавление Telegram аккаунта</b>

Для работы с каналами нужно добавить ваш Telegram аккаунт.

<b>Что потребуется:</b>
• Номер телефона (с кодом страны, например: +380123456789)
• API ID и API Hash (получить на my.telegram.org)
• Код подтверждения из SMS
• Пароль двухфакторной аутентификации (если включен)

<b>Безопасность:</b>
• Данные хранятся локально в зашифрованном виде
• Используется официальный Telegram Client API
• Полный контроль остается у вас

Отправьте номер телефона в формате: +380123456789
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")]
        ])
        
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        self.db.set_user_state(query.from_user.id, 'waiting_phone_number')
    
    async def show_account_management(self, query, account_id: int):
        """Show account management options"""
        account = self.db.get_account(account_id)
        if not account:
            await query.edit_message_text("Аккаунт не найден.")
            return
        
        status = "🟢 Подключен" if account['is_connected'] else "🔴 Отключен"
        text = f"""
⚙️ <b>Управление аккаунтом</b>

<b>Аккаунт:</b> {account['account_name']}
<b>Телефон:</b> {account['phone_number']}
<b>Статус:</b> {status}
<b>Добавлен:</b> {account['created_at'][:16]}
<b>Последнее использование:</b> {account['last_used'][:16] if account['last_used'] else 'Никогда'}
        """
        
        keyboard = []
        if account['is_connected']:
            keyboard.append([
                InlineKeyboardButton("🔌 Отключить", callback_data=f"disconnect_account_{account_id}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("🔌 Подключить", callback_data=f"connect_account_{account_id}")
            ])
        
        keyboard.extend([
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_account_{account_id}")],
            [InlineKeyboardButton("❌ Закрыть", callback_data="cancel")]
        ])
        
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, 
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_account_selection_for_channel(self, query, channel_id: int):
        """Show account selection for channel"""
        user_id = query.from_user.id
        accounts = self.db.get_user_accounts(user_id)
        channel = self.db.get_channel(channel_id)
        
        if not channel:
            await query.edit_message_text("Канал не найден.")
            return
        
        text = f"""
🔗 <b>Назначение аккаунта для канала</b>

<b>Канал:</b> {channel['target_channel_name'] or channel['target_channel_id']}
<b>Текущий аккаунт:</b> {channel['account_name'] or 'Не назначен'}

Выберите аккаунт для работы с этим каналом:
        """
        
        keyboard = []
        for account in accounts:
            status_emoji = "🟢" if account['is_connected'] else "🔴"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status_emoji} {account['account_name']}",
                    callback_data=f"assign_account_{account['id']}_{channel_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")])
        
        await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def assign_account_to_channel_confirm(self, query, account_id: int, channel_id: int):
        """Confirm account assignment to channel"""
        account = self.db.get_account(account_id)
        channel = self.db.get_channel(channel_id)
        
        if not account or not channel:
            await query.edit_message_text("Аккаунт или канал не найден.")
            return
        
        # Assign account to channel
        self.db.assign_account_to_channel(channel_id, account_id)
        
        # Start monitoring if account is connected and channel is configured
        if (account['is_connected'] and channel['source_channel_id'] and 
            channel['is_active']):
            try:
                updated_channel = self.db.get_channel(channel_id)
                await self.client_manager.start_monitoring_for_channel(updated_channel)
            except Exception as e:
                logger.error(f"Error starting monitoring: {e}")
        
        await query.edit_message_text(
            f"{EMOJIS['success']} Аккаунт <b>{account['account_name']}</b> назначен каналу <b>{channel['target_channel_name']}</b>!",
            parse_mode=ParseMode.HTML
        )
    
    async def connect_account(self, query, account_id: int):
        """Connect account"""
        try:
            success = await self.client_manager.connect_account(account_id)
            if success:
                await query.edit_message_text(
                    f"{EMOJIS['success']} Аккаунт успешно подключен!",
                    parse_mode=ParseMode.HTML
                )
                
                # Start monitoring for channels using this account
                await self.start_monitoring_for_account(account_id)
            else:
                await query.edit_message_text(
                    f"{EMOJIS['error']} Ошибка подключения аккаунта. Проверьте данные.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            await query.edit_message_text(
                f"{EMOJIS['error']} Ошибка: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def disconnect_account(self, query, account_id: int):
        """Disconnect account"""
        try:
            await self.client_manager.disconnect_account(account_id)
            await query.edit_message_text(
                f"{EMOJIS['success']} Аккаунт отключен.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            await query.edit_message_text(
                f"{EMOJIS['error']} Ошибка: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def delete_account(self, query, account_id: int):
        """Delete account"""
        try:
            await self.client_manager.disconnect_account(account_id)
            self.db.delete_account(account_id)
            await query.edit_message_text(
                f"{EMOJIS['success']} Аккаунт удален.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            await query.edit_message_text(
                f"{EMOJIS['error']} Ошибка: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def toggle_channel_status(self, query, channel_id: int):
        """Toggle channel active status (pause/resume instead of delete)"""
        channel = self.db.get_channel(channel_id)
        if not channel:
            await query.edit_message_text("Канал не найден.")
            return
        
        new_status = not channel['is_active']
        self.db.update_channel_status(channel_id, new_status)
        
        if new_status:
            # Resume - start monitoring if conditions are met
            if (channel['assigned_account_id'] and channel['account_connected'] and 
                channel['source_channel_id']):
                try:
                    updated_channel = self.db.get_channel(channel_id)
                    await self.client_manager.start_monitoring_for_channel(updated_channel)
                except Exception as e:
                    logger.error(f"Error starting monitoring: {e}")
        else:
            # Pause - stop monitoring
            if channel['assigned_account_id']:
                try:
                    await self.client_manager.stop_monitoring_for_channel(
                        channel_id, channel['assigned_account_id']
                    )
                except Exception as e:
                    logger.error(f"Error stopping monitoring: {e}")
        
        status_text = "активирован" if new_status else "приостановлен"
        await query.edit_message_text(
            f"{EMOJIS['success']} Канал {channel['target_channel_name']} {status_text}.",
            parse_mode=ParseMode.HTML
        )
    
    async def delete_channel(self, query, channel_id: int):
        """Delete channel configuration completely"""
        channel = self.db.get_channel(channel_id)
        if not channel:
            await query.edit_message_text("Канал не найден.")
            return
        
        # Stop monitoring first
        if channel['assigned_account_id']:
            try:
                await self.client_manager.stop_monitoring_for_channel(
                    channel_id, channel['assigned_account_id']
                )
            except Exception as e:
                logger.error(f"Error stopping monitoring: {e}")
        
        # Delete from database
        self.db.delete_channel(channel_id)
        
        await query.edit_message_text(
            f"{EMOJIS['success']} Канал {channel['target_channel_name']} полностью удален.",
            parse_mode=ParseMode.HTML
        )
    
    async def pause_all_channels(self, query):
        """Pause all channels"""
        user_id = query.from_user.id
        channels = self.db.get_user_channels(user_id)
        
        active_channels = [c for c in channels if c['is_active']]
        if not active_channels:
            await query.edit_message_text(
                f"{EMOJIS['info']} Все каналы уже приостановлены.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Stop monitoring and update status
        for channel in active_channels:
            self.db.update_channel_status(channel['id'], False)
            if channel['assigned_account_id']:
                await self.client_manager.stop_monitoring_for_channel(
                    channel['id'], channel['assigned_account_id']
                )
        
        await query.edit_message_text(
            f"{EMOJIS['pause']} Все активные каналы ({len(active_channels)}) приостановлены.",
            parse_mode=ParseMode.HTML
        )
    
    async def resume_all_channels(self, query):
        """Resume all channels"""
        user_id = query.from_user.id
        channels = self.db.get_user_channels(user_id)
        
        inactive_channels = [c for c in channels if not c['is_active']]
        if not inactive_channels:
            await query.edit_message_text(
                f"{EMOJIS['info']} Все каналы уже активны.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Update status and start monitoring
        resumed_count = 0
        for channel in inactive_channels:
            self.db.update_channel_status(channel['id'], True)
            
            # Start monitoring if account is assigned and connected
            if (channel['assigned_account_id'] and channel['account_connected'] and 
                channel['source_channel_id']):
                try:
                    updated_channel = self.db.get_channel(channel['id'])
                    await self.client_manager.start_monitoring_for_channel(updated_channel)
                    resumed_count += 1
                except Exception as e:
                    logger.error(f"Error resuming monitoring for channel {channel['id']}: {e}")
        
        await query.edit_message_text(
            f"{EMOJIS['resume']} Возобновлено {resumed_count} каналов из {len(inactive_channels)}.\n"
            f"Убедитесь, что аккаунты подключены и каналы настроены.",
            parse_mode=ParseMode.HTML
        )
    
    async def handle_state_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle input based on user state"""
        user_id = update.effective_user.id
        state_data = self.db.get_user_state(user_id)
        
        if not state_data:
            return
        
        state = state_data['state']
        data = state_data['data']
        
        if state == 'waiting_phone_number':
            await self.process_phone_number(update, context)
        elif state == 'waiting_api_credentials':
            await self.process_api_credentials(update, context)
        elif state == 'waiting_verification_code':
            await self.process_verification_code(update, context)
        elif state == 'waiting_2fa_password':
            await self.process_2fa_password(update, context)
        elif state == 'waiting_target_channel':
            await self.process_target_channel(update, context)
        elif state == 'waiting_source_channel':
            await self.process_source_channel(update, context, data.get('channel_id'))
        elif state == 'waiting_offer_post':
            await self.process_offer_post(update, context, data.get('channel_id'))
        elif state == 'adding_buttons_to_offer':
            await self.process_button_addition(update, context, data.get('channel_id'))
    
    async def process_phone_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process phone number input"""
        user_id = update.effective_user.id
        phone_number = update.message.text.strip()
        
        # Validate phone number format
        if not re.match(r'^\+\d{10,15}$', phone_number):
            await update.message.reply_text(
                f"{EMOJIS['error']} Неверный формат номера телефона.\n"
                f"Используйте формат: +380123456789",
                parse_mode=ParseMode.HTML
            )
            return
        
        text = f"""
{EMOJIS['key']} <b>API данные</b>

Номер телефона: <code>{phone_number}</code>

Теперь нужны API ID и API Hash:

1. Перейдите на https://my.telegram.org
2. Войдите с вашим номером телефона
3. Перейдите в "API development tools"
4. Создайте приложение (любое название)
5. Скопируйте API ID и API Hash

Отправьте в формате:
<code>API_ID:API_HASH</code>

Например: <code>12345678:abcdef1234567890abcdef1234567890</code>
        """
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        self.db.set_user_state(user_id, 'waiting_api_credentials', {'phone_number': phone_number})
    
    async def process_api_credentials(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process API credentials input"""
        user_id = update.effective_user.id
        state_data = self.db.get_user_state(user_id)
        phone_number = state_data['data']['phone_number']
        
        credentials = update.message.text.strip()
        
        try:
            api_id, api_hash = credentials.split(':')
            api_id = int(api_id)
        except ValueError:
            await update.message.reply_text(
                f"{EMOJIS['error']} Неверный формат. Используйте: API_ID:API_HASH",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Try to add account
        result = await self.client_manager.add_account(user_id, phone_number, api_id, api_hash)
        
        if result['status'] == 'code_required':
            await update.message.reply_text(
                f"{EMOJIS['phone']} {result['message']}",
                parse_mode=ParseMode.HTML
            )
            self.db.set_user_state(user_id, 'waiting_verification_code', {
                'phone_number': phone_number,
                'api_id': api_id,
                'api_hash': api_hash,
                'phone_hash': result['phone_hash'],
                'session_name': result['session_name']
            })
        elif result['status'] == 'success':
            await update.message.reply_text(
                f"{EMOJIS['success']} {result['message']}",
                parse_mode=ParseMode.HTML
            )
            self.db.clear_user_state(user_id)
        else:
            await update.message.reply_text(
                f"{EMOJIS['error']} {result['message']}",
                parse_mode=ParseMode.HTML
            )
    
    async def process_verification_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process verification code input"""
        user_id = update.effective_user.id
        state_data = self.db.get_user_state(user_id)
        data = state_data['data']
        
        code = update.message.text.strip()
        
        result = await self.client_manager.verify_code(
            user_id, data['phone_number'], data['api_id'], data['api_hash'],
            data['session_name'], data['phone_hash'], code
        )
        
        if result['status'] == 'password_required':
            await update.message.reply_text(
                f"{EMOJIS['key']} {result['message']}",
                parse_mode=ParseMode.HTML
            )
            # Update state with all necessary data for 2FA
            self.db.set_user_state(user_id, 'waiting_2fa_password', {
                'phone_number': result['phone_number'],
                'api_id': result['api_id'],
                'api_hash': result['api_hash'],
                'session_name': result['session_name']
            })
        elif result['status'] == 'success':
            await update.message.reply_text(
                f"{EMOJIS['success']} {result['message']}\n\n"
                f"Аккаунт <b>{result['account_name']}</b> готов к работе!",
                parse_mode=ParseMode.HTML
            )
            self.db.clear_user_state(user_id)
        
            # Start monitoring for channels using this account
            try:
                await self.start_monitoring_for_account(result['account_id'])
            except Exception as e:
                logger.error(f"Error starting monitoring: {e}")
        else:
            await update.message.reply_text(
                f"{EMOJIS['error']} {result['message']}",
                parse_mode=ParseMode.HTML
            )
    
    async def process_2fa_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process 2FA password input"""
        user_id = update.effective_user.id
        state_data = self.db.get_user_state(user_id)
        data = state_data['data']
        
        password = update.message.text.strip()
        
        result = await self.client_manager.verify_password(
            user_id, 
            data['phone_number'], 
            data['api_id'], 
            data['api_hash'],
            data['session_name'], 
            password
        )
        
        if result['status'] == 'success':
            await update.message.reply_text(
                f"{EMOJIS['success']} {result['message']}\n\n"
                f"Аккаунт <b>{result['account_name']}</b> готов к работе!",
                parse_mode=ParseMode.HTML
            )
            self.db.clear_user_state(user_id)
        
            # Start monitoring for channels using this account
            try:
                await self.start_monitoring_for_account(result['account_id'])
            except Exception as e:
                logger.error(f"Error starting monitoring: {e}")
            
        else:
            await update.message.reply_text(
                f"{EMOJIS['error']} {result['message']}",
                parse_mode=ParseMode.HTML
            )
    
    async def start_monitoring_for_account(self, account_id: int):
        """Start monitoring for all channels using this account"""
        try:
            # Get all channels using this account
            active_channels = self.db.get_active_channels_with_accounts()
            account_channels = [ch for ch in active_channels if ch['assigned_account_id'] == account_id]
            
            for channel_config in account_channels:
                await self.client_manager.start_monitoring_for_channel(channel_config)
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error starting monitoring for account {account_id}: {e}")
    
    async def process_target_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process target channel input"""
        user_id = update.effective_user.id
        channel_input = update.message.text.strip()
        
        channel_id = self.parse_channel_identifier(channel_input)
        
        if not channel_id:
            await update.message.reply_text(
                f"{EMOJIS['error']} Неверный формат канала. Попробуйте еще раз.",
                parse_mode=ParseMode.HTML
            )
            return
        
        try:
            chat = await context.bot.get_chat(channel_id)
            member = await context.bot.get_chat_member(channel_id, context.bot.id)
            
            if member.status not in [ChatMemberStatus.ADMINISTRATOR]:
                await update.message.reply_text(
                    f"{EMOJIS['error']} Я не являюсь администратором канала {chat.title}. "
                    f"Добавьте меня администратором с правами редактирования сообщений.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            db_channel_id = self.db.add_channel(user_id, str(channel_id), chat.title)
            
            await update.message.reply_text(
                f"{EMOJIS['success']} Канал <b>{chat.title}</b> успешно добавлен!",
                parse_mode=ParseMode.HTML
            )
            
            self.db.clear_user_state(user_id)
            self.db.add_log(user_id, db_channel_id, action='add_target_channel', details=f'Added channel: {chat.title}')
            
        except Exception as e:
            logger.error(f"Error adding target channel: {e}")
            await update.message.reply_text(
                f"{EMOJIS['error']} Ошибка при добавлении канала. Проверьте права доступа.",
                parse_mode=ParseMode.HTML
            )
    
    def parse_channel_identifier(self, channel_input: str) -> Optional[str]:
        """Parse channel identifier from various formats"""
        channel_input = channel_input.strip()
        
        if channel_input.startswith('-') and channel_input[1:].isdigit():
            return channel_input
        
        if channel_input.startswith('@'):
            return channel_input
        
        if 't.me/' in channel_input:
            username = channel_input.split('t.me/')[-1].split('?')[0]
            return f"@{username}"
        
        if channel_input.replace('_', '').replace('-', '').isalnum():
            return f"@{channel_input}"
        
        return None
    
    async def handle_source_channel_selection(self, query, channel_id: int):
        """Handle source channel selection"""
        await query.edit_message_text(
            f"{EMOJIS['source']} Отправьте ID или ссылку на исходный канал для мониторинга:",
            parse_mode=ParseMode.HTML
        )
        self.db.set_user_state(query.from_user.id, 'waiting_source_channel', {'channel_id': channel_id})

    async def handle_offer_post_selection(self, query, channel_id: int):
        """Handle offer post selection"""
        await query.edit_message_text(
            f"{EMOJIS['offer']} <b>Отправьте рекламный пост</b>\n\n"
            f"Поддерживаются:\n"
            f"• Текст с HTML разметкой\n"
            f"• Фото, видео, документы\n"
            f"• Inline кнопки\n\n"
            f"Просто отправьте готовый пост со всем содержимым:",
            parse_mode=ParseMode.HTML
        )
        self.db.set_user_state(query.from_user.id, 'waiting_offer_post', {'channel_id': channel_id})

    async def show_channel_management(self, query, channel_id: int):
        """Show channel management options"""
        channel = self.db.get_channel(channel_id)
        if not channel:
            await query.edit_message_text("Канал не найден.")
            return
        
        status = "🟢 Активен" if channel['is_active'] else "🔴 Приостановлен"
        text = f"""
⚙️ <b>Управление каналом</b>

<b>Канал:</b> {channel['target_channel_name'] or channel['target_channel_id']}
<b>Статус:</b> {status}
<b>Исходный канал:</b> {channel['source_channel_name'] or 'Не настроен'}
<b>Аккаунт:</b> {channel['account_name'] or 'Не назначен'}
<b>Рекламный пост:</b> {'✅ Настроен' if channel['offer_post_content'] else '❌ Не настроен'}
        """
        
        keyboard = [
            [
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_channel_{channel_id}")
            ],
            [
                InlineKeyboardButton("🔗 Отвязать аккаунт", callback_data=f"unlink_from_channel_{channel_id}") if channel['assigned_account_id'] else InlineKeyboardButton("🔗 Назначить аккаунт", callback_data=f"assign_to_channel_{channel_id}")
            ],
            [
                InlineKeyboardButton("🗑️ Удалить навсегда", callback_data=f"delete_channel_{channel_id}")
            ],
            [
                InlineKeyboardButton("❌ Закрыть", callback_data="cancel")
            ]
        ]
        
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, 
                                    reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_edit_channel_selection(self, query, channel_id: int):
        """Handle edit channel selection"""
        channel = self.db.get_channel(channel_id)
        if not channel:
            await query.edit_message_text("Канал не найден.")
            return
        
        text = f"""
✏️ <b>Редактирование канала</b>

<b>Канал:</b> {channel['target_channel_name'] or channel['target_channel_id']}
Выберите, что хотите редактировать:
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📡 Исходный канал", callback_data=f"edit_source_{channel_id}"),
                InlineKeyboardButton("🎯 Рекламный пост", callback_data=f"edit_offer_{channel_id}")
            ],
            [InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")]
        ]
        
        await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_confirmation(self, query, data: str):
        """Handle confirmation callbacks"""
        if data.startswith("confirm_target_"):
            channel_id = int(data.split("_")[-1])
            await query.edit_message_text(
                f"{EMOJIS['success']} Целевой канал успешно добавлен!",
                parse_mode=ParseMode.HTML
            )
        elif data == "confirm_reset":
            user_id = query.from_user.id
            channels = self.db.get_user_channels(user_id)
            for channel in channels:
                # Stop monitoring first
                if channel['assigned_account_id']:
                    try:
                        await self.client_manager.stop_monitoring_for_channel(
                            channel['id'], channel['assigned_account_id']
                        )
                    except Exception as e:
                        logger.error(f"Error stopping monitoring: {e}")
                
                self.db.delete_channel(channel['id'])
            
            await query.edit_message_text(
                f"{EMOJIS['success']} Все настройки сброшены.",
                parse_mode=ParseMode.HTML
            )

    async def process_source_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int):
        """Process source channel input"""
        channel_input = update.message.text.strip()
        parsed_channel = self.parse_channel_identifier(channel_input)
        
        if not parsed_channel:
            await update.message.reply_text(
                f"{EMOJIS['error']} Неверный формат канала. Попробуйте еще раз.",
                parse_mode=ParseMode.HTML
            )
            return
        
        try:
            # Try to get channel info (this doesn't require bot to be admin)
            try:
                chat = await context.bot.get_chat(parsed_channel)
                channel_name = chat.title
            except:
                # If bot can't access, just use the ID/username
                channel_name = parsed_channel
            
            self.db.update_channel_source(channel_id, str(parsed_channel), channel_name)
            
            await update.message.reply_text(
                f"{EMOJIS['success']} Исходный канал <b>{channel_name}</b> успешно настроен!\n\n"
                f"Теперь бот будет отслеживать новые сообщения в этом канале через назначенный аккаунт.",
                parse_mode=ParseMode.HTML
            )
            
            self.db.clear_user_state(update.effective_user.id)
            
            # Try to start monitoring if account is assigned and connected
            channel = self.db.get_channel(channel_id)
            if (channel['assigned_account_id'] and channel['account_connected'] and 
                channel['is_active']):
                try:
                    await self.client_manager.start_monitoring_for_channel(channel)
                except Exception as e:
                    logger.error(f"Error starting monitoring: {e}")
            
        except Exception as e:
            await update.message.reply_text(
                f"{EMOJIS['error']} Ошибка при настройке исходного канала: {str(e)}",
                parse_mode=ParseMode.HTML
            )

    async def process_offer_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int):
        """Process offer post input with enhanced HTML formatting and entities support"""
        user_id = update.effective_user.id
        message = update.message

        # Extract content with entities support  
        content = ""
        entities = []

        if message.text:
            content = message.text
            if message.entities:
                entities = [
                    {
                        'type': entity.type,
                        'offset': entity.offset,
                        'length': entity.length,
                        'url': getattr(entity, 'url', None),
                        'user': getattr(entity, 'user', None),
                        'language': getattr(entity, 'language', None)
                    } for entity in message.entities
                ]
        elif message.caption:
            content = message.caption
            if message.caption_entities:
                entities = [
                    {
                        'type': entity.type,
                        'offset': entity.offset,
                        'length': entity.length,
                        'url': getattr(entity, 'url', None),
                        'user': getattr(entity, 'user', None),
                        'language': getattr(entity, 'language', None)
                    } for entity in message.caption_entities
                ]

        # Extract media info with enhanced support
        media_info = None
        if message.photo:
            media_info = {
                'type': 'photo',
                'file_id': message.photo[-1].file_id,
                'file_unique_id': message.photo[-1].file_unique_id,
                'width': message.photo[-1].width,
                'height': message.photo[-1].height,
                'file_size': getattr(message.photo[-1], 'file_size', None)
            }
        elif message.video:
            media_info = {
                'type': 'video',
                'file_id': message.video.file_id,
                'file_unique_id': message.video.file_unique_id,
                'duration': message.video.duration,
                'width': message.video.width,
                'height': message.video.height,
                'file_size': getattr(message.video, 'file_size', None),
                'mime_type': getattr(message.video, 'mime_type', None)
            }
        elif message.document:
            media_info = {
                'type': 'document',
                'file_id': message.document.file_id,
                'file_unique_id': message.document.file_unique_id,
                'file_name': getattr(message.document, 'file_name', None),
                'file_size': getattr(message.document, 'file_size', None),
                'mime_type': getattr(message.document, 'mime_type', None)
            }
        elif message.animation:
            media_info = {
                'type': 'animation',
                'file_id': message.animation.file_id,
                'file_unique_id': message.animation.file_unique_id,
                'duration': message.animation.duration,
                'width': message.animation.width,
                'height': message.animation.height,
                'file_size': getattr(message.animation, 'file_size', None),
                'mime_type': getattr(message.animation, 'mime_type', None)
            }
        elif message.audio:
            media_info = {
                'type': 'audio',
                'file_id': message.audio.file_id,
                'file_unique_id': message.audio.file_unique_id,
                'duration': message.audio.duration,
                'performer': getattr(message.audio, 'performer', None),
                'title': getattr(message.audio, 'title', None),
                'mime_type': getattr(message.audio, 'mime_type', None),
                'file_size': getattr(message.audio, 'file_size', None)
            }
        elif message.voice:
            media_info = {
                'type': 'voice',
                'file_id': message.voice.file_id,
                'file_unique_id': message.voice.file_unique_id,
                'duration': message.voice.duration,
                'mime_type': getattr(message.voice, 'mime_type', None),
                'file_size': getattr(message.voice, 'file_size', None)
            }
        elif message.video_note:
            media_info = {
                'type': 'video_note',
                'file_id': message.video_note.file_id,
                'file_unique_id': message.video_note.file_unique_id,
                'duration': message.video_note.duration,
                'length': message.video_note.length,
                'file_size': getattr(message.video_note, 'file_size', None)
            }
        elif message.sticker:
            media_info = {
                'type': 'sticker',
                'file_id': message.sticker.file_id,
                'file_unique_id': message.sticker.file_unique_id,
                'width': message.sticker.width,
                'height': message.sticker.height,
                'is_animated': message.sticker.is_animated,
                'is_video': getattr(message.sticker, 'is_video', False),
                'file_size': getattr(message.sticker, 'file_size', None)
            }

        # Extract inline buttons
        buttons_data = []
        if message.reply_markup and message.reply_markup.inline_keyboard:
            for row in message.reply_markup.inline_keyboard:
                button_row = []
                for button in row:
                    if button.url:
                        button_row.append({
                            'text': button.text,
                            'url': button.url
                        })
                    elif button.callback_data:
                        button_row.append({
                            'text': button.text,
                            'callback_data': button.callback_data
                        })
                if button_row:
                    buttons_data.append(button_row)

        # Prepare data for database
        media_json = json.dumps(media_info) if media_info else None
        entities_json = json.dumps(entities) if entities else None
        buttons_json = json.dumps(buttons_data) if buttons_data else None

        # Update database
        self.db.update_offer_post(channel_id, content, media_json, entities_json)
        if buttons_json:
            try:
                self.db.update_offer_post_buttons(channel_id, buttons_json)
            except Exception as e:
                logger.warning(f"Could not save buttons: {e}")

        # Build detailed response
        entities_info = "❌ Нет"
        if entities:
            entity_types = list(set(entity['type'] for entity in entities))
            entities_info = f"✅ ({', '.join(entity_types)})"

        media_types = []
        if media_info:
            media_types.append(media_info['type'])

        response_text = f"{EMOJIS['success']} <b>Рекламный пост успешно настроен!</b>\n\n"
        response_text += f"<b>Сохранено:</b>\n"
        response_text += f"• Текст: {'✅' if content else '❌'}\n"
        response_text += f"• Форматирование: {entities_info}\n"
        response_text += f"• Медиа: {'✅ ' + ', '.join(media_types) if media_info else '❌'}\n"
        response_text += f"• Кнопки: {'✅' if buttons_data else '❌'}\n\n"

        if content:
            preview = content[:100] + "..." if len(content) > 100 else content
            response_text += f"<b>Предварительный просмотр:</b>\n{preview}\n\n"

        if entities:
            response_text += f"<b>Обнаружено форматирование:</b>\n"
            for entity in entities[:3]:
                entity_text = content[entity['offset']:entity['offset'] + entity['length']]
                response_text += f"• {entity['type']}: \"{entity_text}\"\n"
            if len(entities) > 3:
                response_text += f"• и еще {len(entities) - 3} элементов...\n"
            response_text += "\n"

        if media_info:
            response_text += f"<b>Медиафайл:</b> {media_info['type']}"
            if media_info.get('file_size'):
                file_size_mb = media_info['file_size'] / (1024 * 1024)
                response_text += f" ({file_size_mb:.1f} MB)"
            response_text += "\n\n"

        # Build keyboard
        keyboard = [
            [
                InlineKeyboardButton("👁️ Просмотр", callback_data=f"preview_offer_{channel_id}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_offer_{channel_id}")
            ]
        ]

        # Send response
        await update.message.reply_text(
            response_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Clear user state
        self.db.clear_user_state(user_id)

        # Enhanced logging
        self.db.add_log(
            user_id,
            channel_id,
            action='update_offer_post',
            details=f'Updated offer post - entities: {len(entities)}, media: {media_info["type"] if media_info else None}, buttons: {len(buttons_data)}'
        )
    
    async def handle_add_button_to_offer(self, query, channel_id: int):
        """Handle adding button to offer post"""
        # Send instructions for adding buttons
        await query.edit_message_text(
            f"{EMOJIS['link']} <b>Добавление кнопки к рекламному посту</b>\n\n"
            f"Отправьте данные кнопки в формате:\n"
            f"<code>Текст кнопки | https://example.com</code>\n\n"
            f"Или для нескольких кнопок:\n"
            f"<code>Кнопка 1 | https://link1.com\n"
            f"Кнопка 2 | https://link2.com</code>\n\n"
            f"<b>Примеры:</b>\n"
            f"<code>🛒 Купить | https://shop.com</code>\n"
            f"<code>📞 Связаться | https://t.me/username</code>",
            parse_mode=ParseMode.HTML
        )

        # Set user state
        self.db.set_user_state(query.from_user.id, 'adding_buttons_to_offer', {'channel_id': channel_id})
    
    async def process_button_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int):
        """Process button addition to offer post"""
        # Initialize user and button data
        user_id = update.effective_user.id
        button_text = update.message.text.strip()

        try:
            # Fetch existing buttons
            channel = self.db.get_channel(channel_id)
            existing_buttons = []

            if channel['offer_post_buttons']:
                existing_buttons = json.loads(channel['offer_post_buttons'])

            # Parse new buttons
            new_buttons = []
            lines = button_text.split('\n')

            for line in lines:
                if '|' in line:
                    parts = line.split('|', 1)
                    text = parts[0].strip()
                    url = parts[1].strip()

                    if text and url:
                        new_buttons.append({'text': text, 'url': url})

            # Validate new buttons
            if not new_buttons:
                await update.message.reply_text(
                    f"{EMOJIS['error']} Неверный формат. Используйте: Текст | URL",
                    parse_mode=ParseMode.HTML
                )
                return

            # Add new buttons
            existing_buttons.append(new_buttons)

            # Save updated buttons
            buttons_json = json.dumps(existing_buttons)
            self.db.update_offer_post_buttons(channel_id, buttons_json)

            # Send success message
            await update.message.reply_text(
                f"{EMOJIS['success']} Кнопки успешно добавлены к рекламному посту!\n\n"
                f"Добавлено кнопок: {len(new_buttons)}",
                parse_mode=ParseMode.HTML
            )

            # Clear user state
            self.db.clear_user_state(user_id)

        except Exception as e:
            logger.error(f"Error adding buttons: {e}")
            await update.message.reply_text(
                f"{EMOJIS['error']} Ошибка при добавлении кнопок: {str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    async def reset_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset all settings"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{EMOJIS['confirm']} Подтвердить", callback_data="confirm_reset"),
                InlineKeyboardButton(f"{EMOJIS['cancel']} Отмена", callback_data="cancel")
            ]
        ])
        
        await update.message.reply_text(
            f"{EMOJIS['warning']} <b>Внимание!</b>\n\n"
            f"Это действие удалит все настройки каналов и не может быть отменено.\n\n"
            f"Вы уверены?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

    async def send_notification(self, text: str):
        """Send notification to admin"""
        try:
            if NOTIFICATION_CHAT_ID and NOTIFICATION_CHAT_ID != 'YOUR_NOTIFICATION_CHAT_ID':
                await self.bot.send_message(NOTIFICATION_CHAT_ID, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    async def run(self):
        """Run the bot with proper error handling"""
        try:
            self.application = Application.builder().token(BOT_TOKEN).build()
            self.bot = self.application.bot

            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            self.application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, self.handle_message))
            self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))

            # Initialize the application
            await self.application.initialize()
            await self.application.start()

            # Start monitoring for all connected accounts
            monitoring_task = None
            try:
                monitoring_task = asyncio.create_task(self.client_manager.start_all_monitoring())
                logger.info("Started monitoring task")
            except Exception as e:
                logger.error(f"Failed to start monitoring: {e}")

            # Start polling
            logger.info("Starting advanced bot with Telegram Client API integration")
            
            await self.application.updater.start_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
            )
            
            # Keep the bot running
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                logger.info("Bot received cancellation signal")
                
        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            # Cleanup
            logger.info("Starting cleanup process...")
            
            try:
                # Cancel monitoring task
                if 'monitoring_task' in locals() and monitoring_task and not monitoring_task.done():
                    logger.info("Cancelling monitoring task...")
                    monitoring_task.cancel()
                    try:
                        await asyncio.wait_for(monitoring_task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.info("Monitoring task cancelled/timed out")
                
                # Cleanup client manager
                logger.info("Cleaning up client manager...")
                await self.client_manager.cleanup()
                
                # Stop application
                if self.application:
                    logger.info("Stopping application...")
                    try:
                        if self.application.updater.running:
                            await self.application.updater.stop()
                        await self.application.stop()
                        await self.application.shutdown()
                    except Exception as e:
                        logger.error(f"Error stopping application: {e}")
                
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
            
            logger.info("Bot stopped completely")

def main():
    """Main function to run the bot"""
    bot = TelegramChannelBot()
    
    try:
        # Run the bot
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Main function completed")

if __name__ == "__main__":
    main()