import os
from pathlib import Path

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', '8096770876:AAHMuHUhZdr40Fhd1UUaJt2bdBTJ7RWedMw')

# Notification chat ID (where all notifications will be sent)
NOTIFICATION_CHAT_ID = os.getenv('NOTIFICATION_CHAT_ID', '-4920027903')

# Database Configuration
BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / 'bot_database.db'

# Logging Configuration
LOG_PATH = BASE_DIR / 'bot.log'
LOG_LEVEL = 'INFO'

# Bot Settings
MAX_CHANNELS_PER_USER = 50
MAX_ACCOUNTS_PER_USER = 10
MONITORING_INTERVAL = 10  # Check every 10 seconds
MAX_MESSAGE_LENGTH = 4096

# Telegram Client Settings
SESSIONS_DIR = BASE_DIR / 'sessions'
SESSIONS_DIR.mkdir(exist_ok=True)

# Button Emojis and Styles
EMOJIS = {
    'add': '➕',
    'source': '📡',
    'offer': '🎯',
    'settings': '⚙️',
    'stats': '📊',
    'help': '❓',
    'pause': '⏸️',
    'resume': '▶️',
    'reset': '🔄',
    'confirm': '✅',
    'cancel': '❌',
    'edit': '✏️',
    'preview': '👁️',
    'delete': '🗑️',
    'success': '✅',
    'error': '❌',
    'warning': '⚠️',
    'info': 'ℹ️',
    'account': '👤',
    'phone': '📱',
    'key': '🔑',
    'link': '🔗',
    'channels': '📺',
    'accounts': '👥'
}

# Connection Configuration
CONNECTION_POOL_SIZE = 8
CONNECTION_TIMEOUT = 30
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 5

# Security Settings
ALLOWED_USERS = []  # Empty list means all users allowed
ADMIN_USERS = []    # List of admin user IDs

# Performance Settings
MAX_CONCURRENT_TASKS = 10
TASK_TIMEOUT = 300  # 5 minutes
CLEANUP_INTERVAL = 3600  # 1 hour

# Media Settings
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
SUPPORTED_MEDIA_TYPES = [
    'photo', 'video', 'document', 'audio', 
    'voice', 'video_note', 'animation'
]

# Rate Limiting
RATE_LIMIT_MESSAGES = 30  # messages per minute
RATE_LIMIT_WINDOW = 60    # seconds

# Error Handling
MAX_RETRIES_PER_OPERATION = 3
RETRY_BACKOFF_FACTOR = 2