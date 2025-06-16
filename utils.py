import asyncio
import logging
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class Utils:
    @staticmethod
    def validate_phone_number(phone: str) -> bool:
        """Validate phone number format"""
        return bool(re.match(r'^\+\d{10,15}$', phone.strip()))
    
    @staticmethod
    def validate_api_credentials(credentials: str) -> Optional[tuple]:
        """Validate and parse API credentials"""
        try:
            api_id, api_hash = credentials.strip().split(':')
            return int(api_id), api_hash
        except (ValueError, AttributeError):
            return None
    
    @staticmethod
    def parse_channel_identifier(channel_input: str) -> Optional[str]:
        """Parse channel identifier from various formats"""
        channel_input = channel_input.strip()
        
        # Direct channel ID (negative number)
        if channel_input.startswith('-') and channel_input[1:].isdigit():
            return channel_input
        
        # Username with @
        if channel_input.startswith('@'):
            return channel_input
        
        # t.me link
        if 't.me/' in channel_input:
            username = channel_input.split('t.me/')[-1].split('?')[0]
            return f"@{username}"
        
        # Plain username
        if channel_input.replace('_', '').replace('-', '').isalnum():
            return f"@{channel_input}"
        
        return None
    
    @staticmethod
    def format_datetime(dt_string: str) -> str:
        """Format datetime string for display"""
        try:
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            return dt.strftime('%d.%m.%Y %H:%M')
        except:
            return dt_string[:16] if dt_string else 'Никогда'
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 50) -> str:
        """Truncate text to specified length"""
        if not text:
            return ""
        return text[:max_length] + "..." if len(text) > max_length else text
    
    @staticmethod
    async def retry_async(func, max_retries: int = 3, delay: float = 1.0):
        """Retry async function with exponential backoff"""
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(delay * (2 ** attempt))
        
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe storage"""
        return re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    @staticmethod
    def get_media_type(message) -> Optional[str]:
        """Get media type from message"""
        if hasattr(message, 'photo') and message.photo:
            return 'photo'
        elif hasattr(message, 'video') and message.video:
            return 'video'
        elif hasattr(message, 'document') and message.document:
            return 'document'
        elif hasattr(message, 'audio') and message.audio:
            return 'audio'
        elif hasattr(message, 'voice') and message.voice:
            return 'voice'
        elif hasattr(message, 'video_note') and message.video_note:
            return 'video_note'
        elif hasattr(message, 'animation') and message.animation:
            return 'animation'
        return None
    
    @staticmethod
    def extract_media_info(message) -> Optional[Dict[str, Any]]:
        """Extract media information from message"""
        media_type = Utils.get_media_type(message)
        if not media_type:
            return None
        
        media_attr = getattr(message, media_type)
        if not media_attr:
            return None
        
        return {
            'type': media_type,
            'file_id': media_attr.file_id if hasattr(media_attr, 'file_id') else None,
            'file_size': getattr(media_attr, 'file_size', None),
            'mime_type': getattr(media_attr, 'mime_type', None)
        }

class RateLimiter:
    def __init__(self, max_requests: int = 30, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self.requests = {}
    
    async def is_allowed(self, user_id: int) -> bool:
        """Check if user is within rate limits"""
        now = datetime.now()
        
        if user_id not in self.requests:
            self.requests[user_id] = []
        
        # Remove old requests outside the window
        self.requests[user_id] = [
            req_time for req_time in self.requests[user_id]
            if now - req_time < timedelta(seconds=self.window)
        ]
        
        # Check if under limit
        if len(self.requests[user_id]) < self.max_requests:
            self.requests[user_id].append(now)
            return True
        
        return False

class ErrorHandler:
    @staticmethod
    def format_error(error: Exception) -> str:
        """Format error for user display"""
        error_msg = str(error).lower()
        
        if 'timeout' in error_msg:
            return "Превышено время ожидания. Попробуйте позже."
        elif 'network' in error_msg or 'connection' in error_msg:
            return "Проблемы с сетью. Проверьте подключение."
        elif 'permission' in error_msg or 'forbidden' in error_msg:
            return "Недостаточно прав доступа."
        elif 'not found' in error_msg:
            return "Канал или сообщение не найдено."
        elif 'invalid' in error_msg:
            return "Неверные данные. Проверьте ввод."
        else:
            return f"Произошла ошибка: {str(error)[:100]}"
    
    @staticmethod
    async def handle_async_error(func, *args, **kwargs):
        """Handle async function errors gracefully"""
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            return None