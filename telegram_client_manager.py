import asyncio
import logging
import json
import os
from pathlib import Path
from typing import Dict, Optional, List
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError
from telethon.tl.types import Message, Channel, Chat, MessageMediaPhoto, MessageMediaDocument
from telethon.tl.types import KeyboardButtonUrl, ReplyInlineMarkup
from telegram.constants import ParseMode
from config import SESSIONS_DIR
from database import DatabaseManager

logger = logging.getLogger(__name__)

class TelegramClientManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.clients: Dict[int, TelegramClient] = {}
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.last_processed_messages: Dict[int, int] = {}  # channel_id -> last_message_id
    
    async def add_account(self, user_id: int, phone_number: str, api_id: int, api_hash: str, 
                         account_name: str = None) -> Dict:
        """Add new Telegram account with authentication"""
        try:
            session_name = f"session_{user_id}_{phone_number.replace('+', '')}"
            session_path = SESSIONS_DIR / f"{session_name}.session"
            
            client = TelegramClient(str(session_path), api_id, api_hash)
            
            # Connect and start authentication
            await client.connect()
            
            if not await client.is_user_authorized():
                # Send code request
                sent_code = await client.send_code_request(phone_number)
                
                return {
                    'status': 'code_required',
                    'phone_hash': sent_code.phone_code_hash,
                    'session_name': session_name,
                    'message': 'Код подтверждения отправлен на ваш телефон. Введите код:'
                }
            else:
                # Already authorized
                me = await client.get_me()
                account_id = self.db.add_telegram_account(
                    user_id, phone_number, api_id, api_hash, session_name, 
                    account_name or f"{me.first_name} {me.last_name or ''}".strip()
                )
                
                self.clients[account_id] = client
                self.db.update_account_status(account_id, True)
                
                return {
                    'status': 'success',
                    'account_id': account_id,
                    'account_name': f"{me.first_name} {me.last_name or ''}".strip(),
                    'message': 'Аккаунт успешно добавлен!'
                }
                
        except Exception as e:
            logger.error(f"Error adding account: {e}")
            return {
                'status': 'error',
                'message': f'Ошибка при добавлении аккаунта: {str(e)}'
            }
    
    async def verify_code(self, user_id: int, phone_number: str, api_id: int, api_hash: str,
                         session_name: str, phone_hash: str, code: str, account_name: str = None) -> Dict:
        """Verify phone code and complete authentication"""
        try:
            session_path = SESSIONS_DIR / f"{session_name}.session"
            client = TelegramClient(str(session_path), api_id, api_hash)
            await client.connect()
        
            try:
                await client.sign_in(phone_number, code, phone_code_hash=phone_hash)
            
                me = await client.get_me()
                account_id = self.db.add_telegram_account(
                    user_id, phone_number, api_id, api_hash, session_name,
                    account_name or f"{me.first_name} {me.last_name or ''}".strip()
                )
            
                self.clients[account_id] = client
                self.db.update_account_status(account_id, True)
            
                return {
                    'status': 'success',
                    'account_id': account_id,
                    'account_name': f"{me.first_name} {me.last_name or ''}".strip(),
                    'message': 'Аккаунт успешно добавлен!'
                }
            
            except SessionPasswordNeededError:
                return {
                    'status': 'password_required',
                    'session_name': session_name,
                    'phone_number': phone_number,
                    'api_id': api_id,
                    'api_hash': api_hash,
                    'message': 'У вас включена двухфакторная аутентификация. Введите пароль:'
                }
        
        except PhoneCodeInvalidError:
            return {
                'status': 'error',
                'message': 'Неверный код подтверждения. Попробуйте еще раз.'
            }
        except Exception as e:
            logger.error(f"Error verifying code: {e}")
            return {
                'status': 'error',
                'message': f'Ошибка при проверке кода: {str(e)}'
            }
    
    async def verify_password(self, user_id: int, phone_number: str, api_id: int, api_hash: str,
                         session_name: str, password: str, account_name: str = None) -> Dict:
        """Verify 2FA password"""
        try:
            session_path = SESSIONS_DIR / f"{session_name}.session"
            client = TelegramClient(str(session_path), api_id, api_hash)
            await client.connect()
        
            await client.sign_in(password=password)
        
            me = await client.get_me()
            account_id = self.db.add_telegram_account(
                user_id, phone_number, api_id, api_hash, session_name,
                account_name or f"{me.first_name} {me.last_name or ''}".strip()
            )
        
            self.clients[account_id] = client
            self.db.update_account_status(account_id, True)
        
            return {
                'status': 'success',
                'account_id': account_id,
                'account_name': f"{me.first_name} {me.last_name or ''}".strip(),
                'message': 'Аккаунт успешно добавлен!'
            }
        
        except PasswordHashInvalidError:
            return {
                'status': 'error',
                'message': 'Неверный пароль двухфакторной аутентификации. Попробуйте еще раз.'
            }
        except Exception as e:
            logger.error(f"Error verifying password: {e}")
            return {
                'status': 'error',
                'message': f'Ошибка при проверке пароля: {str(e)}'
            }
    
    async def connect_account(self, account_id: int) -> bool:
        """Connect existing account"""
        try:
            account = self.db.get_account(account_id)
            if not account:
                return False
            
            session_path = SESSIONS_DIR / f"{account['session_name']}.session"
            client = TelegramClient(str(session_path), account['api_id'], account['api_hash'])
            
            await client.connect()
            
            if await client.is_user_authorized():
                self.clients[account_id] = client
                self.db.update_account_status(account_id, True)
                logger.info(f"Connected account {account_id}: {account['account_name']}")
                return True
            else:
                logger.warning(f"Account {account_id} not authorized")
                return False
                
        except Exception as e:
            logger.error(f"Error connecting account {account_id}: {e}")
            return False
    
    async def disconnect_account(self, account_id: int):
        """Disconnect account"""
        try:
            if account_id in self.clients:
                await self.clients[account_id].disconnect()
                del self.clients[account_id]
                self.db.update_account_status(account_id, False)
                
            # Stop all monitoring tasks for this account
            tasks_to_remove = []
            for task_key, task in self.monitoring_tasks.items():
                if task_key.startswith(f"{account_id}_"):
                    task.cancel()
                    tasks_to_remove.append(task_key)
            
            for key in tasks_to_remove:
                del self.monitoring_tasks[key]
                
        except Exception as e:
            logger.error(f"Error disconnecting account {account_id}: {e}")
    
    async def unlink_account_from_channel(self, channel_id: int):
        """Unlink account from channel"""
        try:
            # Get channel configuration
            channel = self.db.get_channel(channel_id)
            if not channel:
                return False
            
            # Stop monitoring first if active
            if channel['assigned_account_id']:
                await self.stop_monitoring_for_channel(channel_id, channel['assigned_account_id'])
            
            # Unlink account from channel
            self.db.unlink_account_from_channel(channel_id)
            
            logger.info(f"Account unlinked from channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error unlinking account from channel {channel_id}: {e}")
            return False
    
    async def get_client(self, account_id: int) -> Optional[TelegramClient]:
        """Get connected client for account"""
        if account_id not in self.clients:
            if await self.connect_account(account_id):
                return self.clients.get(account_id)
            return None
        return self.clients[account_id]
    
    async def start_all_monitoring(self):
        """Start monitoring for all active channels with connected accounts"""
        try:
            active_channels = self.db.get_active_channels_with_accounts()
            if not active_channels:
                logger.info("No active channels with connected accounts found")
                return
            
            for channel_config in active_channels:
                try:
                    await self.start_monitoring_for_channel(channel_config)
                    logger.info(f"Started monitoring for channel {channel_config['id']}")
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Error starting monitoring for channel {channel_config['id']}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error in start_all_monitoring: {e}")
    
    async def start_monitoring_for_channel(self, channel_config: Dict):
        """Start monitoring source channel for new messages"""
        account_id = channel_config['assigned_account_id']
        channel_id = channel_config['id']
        task_key = f"{account_id}_{channel_id}"
        
        # Cancel existing task if any
        if task_key in self.monitoring_tasks:
            self.monitoring_tasks[task_key].cancel()
            del self.monitoring_tasks[task_key]
        
        try:
            client = await self.get_client(account_id)
            if not client:
                logger.error(f"Cannot get client for account {account_id}")
                return
            
            source_channel = channel_config['source_channel_id']
            
            # Get source channel entity
            try:
                source_entity = await client.get_entity(source_channel)
            except Exception as e:
                logger.error(f"Cannot access source channel {source_channel}: {e}")
                return
            
            # Initialize baseline for new messages only
            await self._initialize_monitoring_baseline(client, channel_config, source_entity)
            
            logger.info(f"Starting monitoring for channel {channel_id} using account {account_id}")
            
            # Start monitoring task
            task = asyncio.create_task(
                self._monitor_channel_messages(client, channel_config, source_entity)
            )
            self.monitoring_tasks[task_key] = task
            
        except Exception as e:
            logger.error(f"Error starting monitoring for channel {channel_id}: {e}")
    
    async def _initialize_monitoring_baseline(self, client: TelegramClient, channel_config: Dict, source_entity):
        """Initialize monitoring baseline to only process NEW messages"""
        channel_id = channel_config['id']
        
        try:
            # Get the latest message to establish baseline
            latest_messages = await client.get_messages(source_entity, limit=1)
            if latest_messages and len(latest_messages) > 0:
                baseline_id = latest_messages[0].id
                self.db.update_last_source_message_id(channel_id, baseline_id)
                self.last_processed_messages[channel_id] = baseline_id
                logger.info(f"Established baseline message ID {baseline_id} for channel {channel_id}")
            
            # Initialize target channel state - find the very last post (including offer post)
            target_entity = await client.get_entity(channel_config['target_channel_id'])
            messages = await client.get_messages(target_entity, limit=1)
            
            if messages and len(messages) > 0:
                last_post_id = messages[0].id
                self.db.update_last_post_id(channel_id, last_post_id)
                logger.info(f"Initialized last_post_id to {last_post_id} for channel {channel_id}")
                
        except Exception as e:
            logger.error(f"Error initializing baseline: {e}")
    
    async def _monitor_channel_messages(self, client: TelegramClient, channel_config: Dict, source_entity):
        """Monitor channel for new messages - ONLY process NEW messages"""
        channel_id = channel_config['id']
        
        logger.info(f"Starting message monitoring for channel {channel_id}")
        
        while True:
            try:
                # Get current last processed message ID
                last_message_id = self.last_processed_messages.get(channel_id, 0)
                
                # Get recent messages
                messages = await client.get_messages(source_entity, limit=10)
                
                # Find NEW messages (ID > last_message_id)
                new_messages = [msg for msg in messages if msg.id > last_message_id]
                
                if new_messages:
                    # Sort by ID to process in chronological order
                    new_messages.sort(key=lambda m: m.id)
                    
                    for message in new_messages:
                        try:
                            logger.info(f"Processing NEW message {message.id} in channel {channel_id}")
                            await self._process_new_message(client, channel_config, message)
                            
                            # Update tracking
                            self.last_processed_messages[channel_id] = message.id
                            self.db.update_last_source_message_id(channel_id, message.id)
                            
                            # Small delay between processing
                            await asyncio.sleep(2)
                            
                        except Exception as e:
                            logger.error(f"Error processing message {message.id}: {e}")
                            continue
                
                # Wait before next check
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop for channel {channel_id}: {e}")
                await asyncio.sleep(30)
    
    async def _process_new_message(self, client: TelegramClient, channel_config: Dict, message: Message):
        """Process new message from source channel"""
        try:
            target_channel_id = channel_config['target_channel_id']
            target_entity = await client.get_entity(target_channel_id)
            
            logger.info(f"Processing message {message.id}: '{message.text[:50] if message.text else 'Media message'}'")
            
            # Replace the last post correctly
            await self._replace_last_post_correctly(client, channel_config, target_entity, message)
            
            # Log success
            self.db.add_log(
                channel_config['user_id'],
                channel_config['id'],
                channel_config['assigned_account_id'],
                'process_new_message',
                f'Successfully processed message {message.id}',
                'success'
            )
            
            logger.info(f"Successfully processed message {message.id}")
            
        except Exception as e:
            logger.error(f"Error processing new message {message.id}: {e}")
            self.db.add_log(
                channel_config['user_id'],
                channel_config['id'],
                channel_config['assigned_account_id'],
                'process_new_message',
                f'Error processing message {message.id}: {str(e)}',
                'error'
            )
    
    def _has_real_media(self, message: Message) -> bool:
        """Check if message has real media (photo, video, etc.) not just formatting"""
        if not message.media:
            return False
        
        # Check for specific media types that are considered "real media"
        if isinstance(message.media, MessageMediaPhoto):
            return True
        elif isinstance(message.media, MessageMediaDocument):
            # Check if it's a video, animation, or other media file
            if hasattr(message.media, 'document') and message.media.document:
                # Check MIME type for video files
                if hasattr(message.media.document, 'mime_type'):
                    mime_type = message.media.document.mime_type
                    return mime_type.startswith('video/') or mime_type.startswith('image/') or mime_type == 'application/pdf'
                return True
    
        return False
    
    async def _replace_last_post_correctly(self, client: TelegramClient, channel_config: Dict, 
                           target_entity, new_message: Message):
        """Replace last post with content from new message - CORRECT LOGIC via TelegramClient"""
        try:
            # Get the LAST message from target channel (это всегда offer post)
            messages = await client.get_messages(target_entity, limit=1)

            if not messages:
                logger.warning("No messages found in target channel, creating new post")
                new_post = await self._create_new_post_from_source(client, channel_config, target_entity, new_message)
                if new_post:
                    self.db.update_last_post_id(channel_config['id'], new_post.id)
                return

            last_post = messages[0]  # Это всегда offer post - редактируем его!
    
            # Determine content types
            source_has_real_media = self._has_real_media(new_message)
            source_text = new_message.text or new_message.message or ""
            target_has_real_media = self._has_real_media(last_post)

            logger.info(f"Source: real_media={source_has_real_media}, text='{source_text[:30]}'")
            logger.info(f"Target: real_media={target_has_real_media}, post_id={last_post.id}")

            # ПРАВИЛЬНАЯ ЛОГИКА - РЕДАКТИРУЕМ ПОСЛЕДНИЙ ПОСТ (offer post):
            try:
                if not source_has_real_media and not target_has_real_media:
                    # 📝 Текст → Текст: РЕДАКТИРУЕМ
                    logger.info("📝 Text → Text: EDITING")
                    await client.edit_message(
                        target_entity,
                        last_post.id,
                        source_text,
                        formatting_entities=new_message.entities,
                        parse_mode=None
                    )
                    logger.info(f"✅ Edited text post {last_post.id}")
            
                elif source_has_real_media and not target_has_real_media:
                    # 📝➡️🖼️ Текст → Медиа: УДАЛЯЕМ И СОЗДАЕМ НОВЫЙ (единственный случай)
                    logger.info("📝➡️🖼️ Text → Media: DELETING and CREATING NEW")
                    await client.delete_messages(target_entity, [last_post.id])
                    logger.info(f"🗑️ Deleted text post {last_post.id}")
                
                    new_post = await self._create_new_post_from_source(client, channel_config, target_entity, new_message)
                    if new_post:
                        self.db.update_last_post_id(channel_config['id'], new_post.id)
                        logger.info(f"✅ Created new media post {new_post.id}")
            
                elif not source_has_real_media and target_has_real_media:
                    # 🖼️➡️📝 Медиа → Текст: РЕДАКТИРУЕМ (убираем медиа)
                    logger.info("🖼️➡️📝 Media → Text: EDITING (removing media)")
                    await client.edit_message(
                        target_entity,
                        last_post.id,
                        source_text,
                        formatting_entities=new_message.entities,
                        parse_mode=None
                    )
                    logger.info(f"✅ Edited media post {last_post.id} to text-only")
            
                elif source_has_real_media and target_has_real_media:
                    # 🖼️➡️🖼️ Медиа → Медиа: РЕДАКТИРУЕМ (заменяем медиа)
                    logger.info("🖼️➡️🖼️ Media → Media: EDITING (replacing media)")
                    await client.edit_message(
                        target_entity,
                        last_post.id,
                        source_text,
                        file=new_message.media,
                        formatting_entities=new_message.entities,
                        parse_mode=None
                    )
                    logger.info(f"✅ Edited media post {last_post.id} with new media")

            except Exception as edit_error:
                logger.error(f"Could not edit post: {edit_error}")
                raise edit_error

            # Create offer post ONLY if configured
            if channel_config.get('offer_post_content'):
                logger.info("Creating offer post...")
                try:
                    await self._create_offer_post(client, channel_config, target_entity)
                    logger.info("Offer post creation completed")
                except Exception as offer_error:
                    logger.error(f"Error creating offer post: {offer_error}")

        except Exception as e:
            logger.error(f"Error in _replace_last_post_correctly: {e}")
            raise
    
    async def _create_new_post_from_source(self, client: TelegramClient, channel_config: Dict, 
                                         target_entity, source_message: Message):
        """Create new post with EXACT copy from source message with formatting support"""
        try:
            # Get exact copy of content
            message_text = source_message.text or source_message.message or ""
            message_entities = source_message.entities
            
            logger.info(f"Creating new post - Text: {bool(message_text)}, Media: {bool(source_message.media)}")
            
            # Send message with exact copy including media and formatting
            if source_message.media:
                # Use the original media object directly
                sent_message = await client.send_message(
                    target_entity,
                    message_text,
                    file=source_message.media,
                    formatting_entities=message_entities,
                    parse_mode=None
                )
            else:
                # Text-only message
                sent_message = await client.send_message(
                    target_entity,
                    message_text,
                    formatting_entities=message_entities,
                    parse_mode=None
                )
            
            # Update last_post_id in database
            self.db.update_last_post_id(channel_config['id'], sent_message.id)
            logger.info(f"Created new post {sent_message.id} - exact copy from source")
            
            return sent_message
            
        except Exception as e:
            logger.error(f"Error creating new post from source: {e}")
            # Fallback: try downloading media as bytes
            try:
                message_text = source_message.text or source_message.message or ""
                media_file = None
                if source_message.media:
                    media_file = await client.download_media(source_message.media, bytes)
                
                sent_message = await client.send_message(
                    target_entity,
                    message_text,
                    file=media_file,
                    formatting_entities=message_entities,
                    parse_mode=None
                )
                self.db.update_last_post_id(channel_config['id'], sent_message.id)
                return sent_message
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")
                raise
    
    async def _create_offer_post(self, client: TelegramClient, channel_config: Dict, target_entity):
        """Create new offer post with enhanced formatting and entities support"""
        try:
            # Проверка наличия контента
            offer_content = channel_config.get('offer_post_content')
            if not offer_content:
                logger.debug("No offer content configured, skipping offer post")
                return

            offer_media = channel_config.get('offer_post_media')
            offer_buttons = channel_config.get('offer_post_buttons')
            offer_entities = channel_config.get('offer_post_entities')

            logger.info("Creating offer post...")
            logger.info(f"Offer content length: {len(offer_content)}")

            # Подготовка медиа
            media_file = None
            if offer_media:
                try:
                    media_info = json.loads(offer_media)
                    file_id = media_info.get('file_id')
                    if file_id:
                        media_file = file_id
                        logger.info(f"Using media file_id: {file_id}")
                except Exception as media_error:
                    logger.warning(f"Error processing offer media: {media_error}")

            # Подготовка кнопок
            reply_markup = None
            if offer_buttons:
                try:
                    buttons_data = json.loads(offer_buttons)
                    if buttons_data and isinstance(buttons_data, list):
                        button_rows = []
                        for row in buttons_data:
                            if isinstance(row, list):
                                button_row = []
                                for btn in row:
                                    if isinstance(btn, dict) and 'text' in btn:
                                        if 'url' in btn:
                                            from telethon.tl.types import KeyboardButtonUrl
                                            button_row.append(KeyboardButtonUrl(btn['text'], btn['url']))
                                        elif 'callback_data' in btn:
                                            from telethon.tl.types import KeyboardButtonCallback
                                            button_row.append(KeyboardButtonCallback(btn['text'], btn['callback_data'].encode()))
                                if button_row:
                                    button_rows.append(button_row)
                        if button_rows:
                            from telethon.tl.types import ReplyInlineMarkup
                            reply_markup = ReplyInlineMarkup(button_rows)
                            logger.info(f"Added {len(button_rows)} button rows")
                except Exception as button_error:
                    logger.warning(f"Error processing buttons: {button_error}")

            # Обработка entities для форматирования
            formatting_entities = None
            if offer_entities:
                try:
                    entities_data = json.loads(offer_entities)
                    logger.info(f"Processing {len(entities_data)} entities")

                    if entities_data:
                        from telethon.tl.types import (
                            MessageEntityBold, MessageEntityItalic, MessageEntityCode,
                            MessageEntityTextUrl, MessageEntityUnderline, MessageEntityStrike,
                            MessageEntityPre, MessageEntityMention, MessageEntityHashtag,
                            MessageEntityCashtag, MessageEntityBotCommand, MessageEntityUrl,
                            MessageEntityEmail, MessageEntityPhone
                        )

                        formatting_entities = []
                        for entity in entities_data:
                            try:
                                offset = entity['offset']
                                length = entity['length']
                                entity_type = entity['type']

                                # Создание соответствующего entity по типу
                                if entity_type == 'bold':
                                    formatting_entities.append(MessageEntityBold(offset, length))
                                elif entity_type == 'italic':
                                    formatting_entities.append(MessageEntityItalic(offset, length))
                                elif entity_type == 'code':
                                    formatting_entities.append(MessageEntityCode(offset, length))
                                elif entity_type == 'underline':
                                    formatting_entities.append(MessageEntityUnderline(offset, length))
                                elif entity_type == 'strikethrough':
                                    formatting_entities.append(MessageEntityStrike(offset, length))
                                elif entity_type == 'text_link' and entity.get('url'):
                                    formatting_entities.append(MessageEntityTextUrl(offset, length, entity['url']))
                                elif entity_type == 'pre':
                                    language = entity.get('language', '')
                                    formatting_entities.append(MessageEntityPre(offset, length, language))
                                elif entity_type == 'mention':
                                    formatting_entities.append(MessageEntityMention(offset, length))
                                elif entity_type == 'hashtag':
                                    formatting_entities.append(MessageEntityHashtag(offset, length))
                                elif entity_type == 'cashtag':
                                    formatting_entities.append(MessageEntityCashtag(offset, length))
                                elif entity_type == 'bot_command':
                                    formatting_entities.append(MessageEntityBotCommand(offset, length))
                                elif entity_type == 'url':
                                    formatting_entities.append(MessageEntityUrl(offset, length))
                                elif entity_type == 'email':
                                    formatting_entities.append(MessageEntityEmail(offset, length))
                                elif entity_type == 'phone_number':
                                    formatting_entities.append(MessageEntityPhone(offset, length))

                            except Exception as entity_error:
                                logger.warning(f"Error processing entity {entity}: {entity_error}")
                                continue

                        logger.info(f"Successfully prepared {len(formatting_entities)} formatting entities")

                except Exception as entity_error:
                    logger.warning(f"Error processing entities: {entity_error}")

            # Отправка сообщения
            offer_message = None
            try:
                logger.info("Attempting to send offer post...")
                
                # Try to send with entities first
                if formatting_entities:
                    logger.info(f"Sending with {len(formatting_entities)} formatting entities")
                    offer_message = await client.send_message(
                        target_entity,
                        offer_content,
                        file=media_file,
                        buttons=reply_markup,
                        formatting_entities=formatting_entities,
                        parse_mode=None
                    )
                    logger.info(f"✅ Successfully sent offer post with entities: {offer_message.id}")
                else:
                    # No entities, try with HTML parsing
                    logger.info("No entities found, trying HTML parsing")
                    offer_message = await client.send_message(
                        target_entity,
                        offer_content,
                        file=media_file,
                        buttons=reply_markup,
                        parse_mode='html'
                    )
                    logger.info(f"✅ Successfully sent offer post with HTML: {offer_message.id}")

            except Exception as e:
                logger.error(f"Failed to send offer post: {e}")
                logger.info("Attempting fallback without formatting...")
                
                try:
                    # Last resort - plain text
                    offer_message = await client.send_message(
                        target_entity,
                        offer_content,
                        file=media_file,
                        buttons=reply_markup
                    )
                    logger.warning(f"⚠️ Sent offer post without formatting: {offer_message.id}")
                except Exception as e2:
                    logger.error(f"Complete failure to send offer post: {e2}")
                    raise

            # Обновление базы данных
            if offer_message:
                self.db.update_offer_post_id(channel_config['id'], offer_message.id)
                logger.info(f"Updated offer_post_id to {offer_message.id}")

        except Exception as e:
            logger.error(f"Error creating offer post: {e}")
            raise
    
    def _convert_entities_to_html(self, text: str, entities: List[Dict]) -> str:
        """Convert entities to HTML formatting as fallback"""
        if not entities:
            return text
        
        # Sort entities by offset in reverse order
        sorted_entities = sorted(entities, key=lambda e: e['offset'], reverse=True)
        
        result = text
        for entity in sorted_entities:
            start = entity['offset']
            end = start + entity['length']
            entity_text = text[start:end]
            
            if entity['type'] == 'bold':
                replacement = f'<b>{entity_text}</b>'
            elif entity['type'] == 'italic':
                replacement = f'<i>{entity_text}</i>'
            elif entity['type'] == 'code':
                replacement = f'<code>{entity_text}</code>'
            elif entity['type'] == 'pre':
                replacement = f'<pre>{entity_text}</pre>'
            elif entity['type'] == 'strikethrough':
                replacement = f'<s>{entity_text}</s>'
            elif entity['type'] == 'underline':
                replacement = f'<u>{entity_text}</u>'
            elif entity['type'] == 'text_link' and entity.get('url'):
                replacement = f'<a href="{entity["url"]}">{entity_text}</a>'
            else:
                continue
                
            result = result[:start] + replacement + result[end:]
        
        return result
    
    async def stop_monitoring_for_channel(self, channel_id: int, account_id: int):
        """Stop monitoring for specific channel"""
        task_key = f"{account_id}_{channel_id}"
        if task_key in self.monitoring_tasks:
            self.monitoring_tasks[task_key].cancel()
            del self.monitoring_tasks[task_key]
            logger.info(f"Stopped monitoring for channel {channel_id}")
        
        # Remove from tracking
        if channel_id in self.last_processed_messages:
            del self.last_processed_messages[channel_id]
    
    async def cleanup(self):
        """Cleanup all connections and tasks"""
        logger.info("Starting client manager cleanup...")
        
        # Cancel all monitoring tasks
        for task in list(self.monitoring_tasks.values()):
            task.cancel()
        
        # Wait for tasks to complete
        if self.monitoring_tasks:
            await asyncio.gather(*self.monitoring_tasks.values(), return_exceptions=True)
        
        # Disconnect all clients
        for account_id in list(self.clients.keys()):
            await self.disconnect_account(account_id)
        
        self.monitoring_tasks.clear()
        self.clients.clear()
        self.last_processed_messages.clear()
        
        logger.info("Client manager cleanup completed")
