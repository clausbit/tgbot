# Main bot script
import logging
import os
import json
from datetime import datetime # Added datetime import
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message # Added Message
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes # JobQueue not explicitly needed for application.job_queue
from telegram.error import TelegramError, BadRequest # Added for API call error handling

# Import configuration
try:
    from config import BOT_TOKEN, ADMIN_USER_ID, API_ID, API_HASH
except ImportError:
    logging.error("config.py not found or missing critical variables. Please create it and add BOT_TOKEN, ADMIN_USER_ID, API_ID, API_HASH.")
    exit()

# Database file
DB_FILE = 'database.json'
db = {}

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Python code block to insert:

def _initialize_new_db_structure():
    global db
    # Ensure ADMIN_USER_ID is accessible, e.g. loaded from config.py globally
    # This subtask assumes ADMIN_USER_ID is available in the global scope.
    # from config import ADMIN_USER_ID # Import if not already global from main script part

    db.clear() # Start with a clean slate for the global db
    db.update({
        'admins': [],
        'channels': [],
        'offers': {},
        'fallback_accounts': {},
        'error_logs': [],
        'stats': {
            'copied_posts_total': 0,
            'edited_posts_total': 0,
            'offers_sent_total': 0,
            'errors_total': 0,
            'per_channel_stats': {}
        },
        'offer_history': {}
    })

    # Detailed comments for structure (won't be in the live code but for documentation)
    # 'admins': list of int (admin user IDs)
    # 'channels': list of dicts:
    #   'id': str (unique ID, e.g., f"{source_id}_{target_id}")
    #   'source_id': int
    #   'source_name': str
    #   'target_id': int
    #   'target_name': str
    #   'offer_id': str (references db['offers'])
    #   'last_target_message_id': int or None
    #   'last_offer_message_id': int or None
    #   'active': bool
    # 'offers': dict (key: offer_id str, value: dict)
    #   'text': str (Markdown/HTML)
    #   'buttons': list of lists of dicts (for InlineKeyboardMarkup)
    #     button dict: {'text': str, 'url': str}
    #   'last_modified': str (ISO timestamp)
    # 'fallback_accounts': dict (key: user_id int, value: dict)
    #   'phone': str
    #   'api_id': int
    #   'api_hash': str
    #   'session_string': str or None
    #   'status': str ('inactive', 'active', 'needs_auth', 'error')
    # 'error_logs': list of dicts
    #   'timestamp': str (ISO timestamp)
    #   'message': str
    #   'context': dict
    # 'stats': dict
    #   'copied_posts_total', 'edited_posts_total', 'offers_sent_total', 'errors_total': int
    #   'per_channel_stats': dict (key: channel_pair_id str, value: dict with 'copied', 'edited', 'offers_sent', 'errors' ints)
    # 'offer_history': dict (key: offer_id str, value: list of previous offer versions)
    #   version dict: {'text', 'buttons', 'timestamp_archived'}

    # This part needs ADMIN_USER_ID to be in global scope or imported
    # For the subtask, we assume config.ADMIN_USER_ID is available.
    # If this subtask is run in an environment where 'config' is not yet imported,
    # this will cause an error. The main script should handle imports.
    try:
        from config import ADMIN_USER_ID # Ensure ADMIN_USER_ID is available
        if ADMIN_USER_ID and isinstance(ADMIN_USER_ID, int):
            db['admins'].append(ADMIN_USER_ID)
            logger.info(f"ADMIN_USER_ID {ADMIN_USER_ID} added to new database's admin list.")
        elif ADMIN_USER_ID:
             logger.warning(f"ADMIN_USER_ID ({ADMIN_USER_ID}) from config is not an int, not adding.")
        else:
            logger.warning("ADMIN_USER_ID not found or is None in config. Initial admin may need manual setup.")
    except ImportError:
        logger.error("Could not import ADMIN_USER_ID from config within _initialize_new_db_structure.")
    except NameError: # logger might not be defined if this is run too early
        print("WARN: ADMIN_USER_ID handling in _initialize_new_db_structure: logger or ADMIN_USER_ID not defined yet.")


    if 'default_offer' not in db['offers']:
        db['offers']['default_offer'] = {
            'text': 'This is a default offer! Please edit it via the bot menu.',
            'buttons': [[{'text': 'Learn More', 'url': 'https://example.com'}]],
            'last_modified': datetime.utcnow().isoformat()
        }
        logger.info("Added 'default_offer' to the new database.")

    # Call the new save_db directly after initializing
    _save_db_internal()

def load_db():
    global db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                db_content = json.load(f)
            # Basic validation: check if it's a dictionary
            if not isinstance(db_content, dict):
                raise json.JSONDecodeError("DB root is not a dictionary", "", 0)
            db.clear()
            db.update(db_content) # Load content into the global db
            logger.info("Database loaded successfully.")
            # Simple schema validation/migration placeholder
            if 'admins' not in db or not isinstance(db['admins'], list):
                logger.warning("Missing 'admins' list in DB, re-initializing. Old data might be lost for this key.")
                db['admins'] = []
                # Potentially re-add ADMIN_USER_ID if appropriate
                from config import ADMIN_USER_ID # Ensure ADMIN_USER_ID is available
                if ADMIN_USER_ID and ADMIN_USER_ID not in db['admins']: db['admins'].append(ADMIN_USER_ID)

        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {DB_FILE}: {e}. Attempting to initialize a new DB structure.")
            backup_name = f"{DB_FILE}.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            try:
                os.rename(DB_FILE, backup_name)
                logger.info(f"Corrupt database file renamed to {backup_name}.")
            except OSError as ose:
                logger.error(f"Could not rename corrupt database file {DB_FILE}: {ose}")
            _initialize_new_db_structure() # This will also save it
        except Exception as ex:
            logger.error(f"Unexpected error loading database {DB_FILE}: {ex}. Attempting to initialize a new DB structure.")
            _initialize_new_db_structure() # This will also save it
    else:
        logger.info(f"Database file {DB_FILE} not found. Creating a new one.")
        _initialize_new_db_structure() # This will also save it

def _save_db_internal():
    global db
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=4, ensure_ascii=False)
        # logger.info("Database saved successfully.") # Too frequent, log selectively
    except Exception as e:
        logger.error(f"Failed to save database: {e}")

# Make save_db an alias or wrapper if needed by other parts of the code expecting 'save_db()'
def save_db():
    _save_db_internal()

# Ensure datetime, os, json, logging, ADMIN_USER_ID (from config) are imported/available
# in the main script body where these functions will reside.
# The logger calls assume 'logger' is a globally configured logger instance.
# The datetime calls assume 'datetime' is imported from the datetime module.

async def edit_target_message(context: ContextTypes.DEFAULT_TYPE, target_channel_id: int, source_message: Message, last_target_message_id: int = None) -> int or None:
    logger.info(f"EDIT_TARGET: Attempting to post content from source message {source_message.message_id} (text: '{source_message.text[:30] if source_message.text else ''}...') to target channel {target_channel_id}. Last target message ID to edit: {last_target_message_id}.")
    
    if not source_message.text: # For now, only handle text messages
        logger.warning(f"EDIT_TARGET: Source message {source_message.message_id} has no text. Skipping edit for now (full content handling later).")
        return None

    if last_target_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=target_channel_id,
                message_id=last_target_message_id,
                text=source_message.text
                # TODO: Add parse_mode if source_message has entities
            )
            logger.info(f"EDIT_TARGET: Successfully edited message ID {last_target_message_id} in target channel {target_channel_id}.")
            return last_target_message_id
        except BadRequest as e:
            logger.error(f"EDIT_TARGET: BadRequest when trying to edit message ID {last_target_message_id} in {target_channel_id}: {e.message}")
            if "message to edit not found" in e.message.lower():
                logger.warning(f"EDIT_TARGET: Message {last_target_message_id} not found in {target_channel_id}. Cannot edit. Will clear last_target_message_id in DB.")
                # Returning None will cause copy_message_to_target to clear it.
                return None
            elif "message is not modified" in e.message.lower():
                logger.info(f"EDIT_TARGET: Message {last_target_message_id} in {target_channel_id} was not modified (text identical). Considering as success.")
                return last_target_message_id
            # Any other BadRequest, assume failure for this attempt
            return None
        except TelegramError as e:
            logger.error(f"EDIT_TARGET: TelegramError when trying to edit message ID {last_target_message_id} in {target_channel_id}: {e}")
            return None
    else:
        # Strict interpretation: "Редактирует последний пост". If no last post, cannot edit.
        # "Новое сообщение публикуется только в случае отправки офер-поста."
        # This means content is not sent if there's no prior message to edit.
        logger.warning(f"EDIT_TARGET: No 'last_target_message_id' for channel {target_channel_id}. As per spec, cannot send new content message if there's nothing to edit. Content from source message {source_message.message_id} will NOT be posted.")
        return None

async def send_offer_post(context: ContextTypes.DEFAULT_TYPE, target_channel_id: int, offer_id: str) -> int or None:
    offer_details = db.get('offers', {}).get(offer_id)
    if not offer_details:
        logger.error(f"SEND_OFFER: Offer ID '{offer_id}' not found in database for target {target_channel_id}.")
        return None

    offer_text = offer_details.get('text')
    if not offer_text:
        logger.error(f"SEND_OFFER: Offer ID '{offer_id}' has no text. Cannot send offer to {target_channel_id}.")
        return None

    # Basic button support (structure from DB)
    buttons_data = offer_details.get('buttons', [])
    reply_markup = None
    if buttons_data:
        try:
            keyboard = []
            for row_data in buttons_data:
                row = []
                for button_info in row_data:
                    # Basic validation, expecting {'text': '..', 'url': '...'}
                    if 'text' in button_info and 'url' in button_info:
                         row.append(InlineKeyboardButton(text=button_info['text'], url=button_info['url']))
                    # Can add more button types here later (callback_data etc)
                if row: # only add row if it has buttons
                    keyboard.append(row)
            if keyboard: # only create markup if keyboard is not empty
                reply_markup = InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"SEND_OFFER: Error processing buttons for offer '{offer_id}': {e}. Sending without buttons.")
            reply_markup = None
    
    logger.info(f"SEND_OFFER: Sending offer '{offer_id}' (Text: {offer_text[:30]}...) to channel {target_channel_id}.")
    try:
        sent_message = await context.bot.send_message(
            chat_id=target_channel_id,
            text=offer_text,
            reply_markup=reply_markup
            # TODO: Add parse_mode (e.g., HTML/Markdown) based on offer settings
        )
        logger.info(f"SEND_OFFER: Successfully sent offer '{offer_id}' to channel {target_channel_id}. Message ID: {sent_message.message_id}")
        return sent_message.message_id
    except TelegramError as e:
        logger.error(f"SEND_OFFER: TelegramError when sending offer '{offer_id}' to {target_channel_id}: {e}")
        return None

async def copy_message_to_target(context: ContextTypes.DEFAULT_TYPE, source_channel_id: int, target_channel_id: int, message: Message, offer_id: str, channel_config: dict):
    logger.info(f"COPY_FLOW: Processing message {message.message_id} from source {source_channel_id} for target {target_channel_id}.")
    
    original_last_target_msg_id = channel_config.get('last_target_message_id')
    content_message_id = await edit_target_message(
        context,
        target_channel_id,
        message,
        original_last_target_msg_id
    )

    if content_message_id:
        logger.info(f"COPY_FLOW: Content successfully processed for target {target_channel_id}. Effective message ID: {content_message_id}.")
        if channel_config.get('last_target_message_id') != content_message_id:
            channel_config['last_target_message_id'] = content_message_id
            logger.info(f"COPY_FLOW: Updated last_target_message_id to {content_message_id} for target {target_channel_id}.")
    else:
        logger.warning(f"COPY_FLOW: Content posting failed or was skipped for source message {message.message_id} to target {target_channel_id}.")
        # If edit_message_text returned None because the original_last_target_msg_id was not found,
        # we should clear it from our config to avoid repeated errors on a non-existent message.
        if original_last_target_msg_id: # And content_message_id is None
             logger.info(f"COPY_FLOW: Content message ID {original_last_target_msg_id} in target {target_channel_id} might be invalid or not editable. Clearing it from config.")
             channel_config['last_target_message_id'] = None

    # "После этого всегда публикует офер-пост." - Always try to send the offer.
    logger.info(f"COPY_FLOW: Proceeding to send offer post for target {target_channel_id}.")
    offer_message_id = await send_offer_post(context, target_channel_id, offer_id)

    if offer_message_id:
        logger.info(f"COPY_FLOW: Offer '{offer_id}' sent to target {target_channel_id}. Offer message ID: {offer_message_id}.")
        if channel_config.get('last_offer_message_id') != offer_message_id:
            channel_config['last_offer_message_id'] = offer_message_id
            logger.info(f"COPY_FLOW: Updated last_offer_message_id to {offer_message_id} for target {target_channel_id}.")
    else:
        logger.error(f"COPY_FLOW: Failed to send offer '{offer_id}' to target {target_channel_id}.")
        # If the offer failed, we might want to clear last_offer_message_id too,
        # or retry later. For now, if it fails, it's just not updated.
        # channel_config['last_offer_message_id'] = None # Optional: clear if failed

    # Save DB if any of the message IDs might have changed or been cleared.
    save_db()
    logger.info(f"COPY_FLOW: Database saved for target {target_channel_id} after copy attempt.")

async def check_new_posts(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Periodic check running via JobQueue...")
    active_channels = [ch for ch in db.get('channels', []) if ch.get('active')]

    if not active_channels:
        logger.info("No active channels configured to check.")
        return

    for channel_config in active_channels:
        source_id = channel_config.get('source_id')
        target_id = channel_config.get('target_id')
        source_name = channel_config.get('source_name', str(source_id)) # Fallback to ID if name missing
        target_name = channel_config.get('target_name', str(target_id)) # Fallback to ID if name missing
        offer_id = channel_config.get('offer_id', 'default_offer')

        logger.info(f"Checking for new posts in source '{source_name}' ({source_id}) for target '{target_name}' ({target_id}).")

        # TODO: Implement actual message fetching logic from Telegram
        # This would involve using context.bot.get_chat_history or similar,
        # comparing with a stored last_processed_message_id for this source channel.
        logger.info(f"TODO: Implement actual message fetching logic from Telegram for source channel ID {source_id}.")

        # Simulate finding a message for testing purposes:
        # This specific dummy source ID (-1001234567890) can be configured in database.json by an admin for a channel pair
        # to test the copy flow without needing a live source channel.
        if source_id == -1001234567890: # A specific dummy/test source ID
            logger.info(f"Simulating new message found in TEST source channel '{source_name}' for testing copy flow.")
            # Create a dummy telegram.Message object
            # Note: `chat` can be `None` for this dummy object if only text is used.
            # For full media copy, a dummy Chat object might be needed, but keep it simple for now.
            dummy_message_text = f"Simulated new post from {source_name} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            dummy_message = Message(
                message_id=int(datetime.now().timestamp()),
                date=datetime.utcnow(),
                chat=None, # Placeholder, will need a Chat object for media
                text=dummy_message_text
                # from_user=None, # Not needed for this simulation
                # caption=None, photo=None, video=None, etc.
            )
            await copy_message_to_target(context, source_id, target_id, dummy_message, offer_id, channel_config)
        else:
            logger.info(f"No new simulated messages for source '{source_name}' ({source_id}). Production logic needed here.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Ensure 'admins' key exists and is a list
    if 'admins' not in db or not isinstance(db.get('admins'), list):
        db['admins'] = []

    if user.id not in db.get('admins', []):
        # If ADMIN_USER_ID is the one starting, add them automatically.
        # This is useful for the very first run or if db['admins'] is empty or ADMIN_USER_ID was removed.
        from config import ADMIN_USER_ID # Ensure ADMIN_USER_ID is available
        if ADMIN_USER_ID and user.id == ADMIN_USER_ID:
            if user.id not in db['admins']: # Check again to be sure after potential initialization
                 db['admins'].append(user.id)
            save_db() # Uses the new save_db wrapper
            logger.info(f"Initial admin {user.id} (from config) added to database.")
            await update.message.reply_text("Welcome, Admin! You have been automatically registered.", reply_markup=get_main_menu_keyboard())
        else:
            logger.warning(f"Unauthorized access attempt for /start by user {user.id} ({user.username}).")
            await update.message.reply_text("You are not authorized to use this bot.")
        return

    logger.info(f"Admin {user.id} started the bot.")
    await update.message.reply_text("Welcome back, Admin! Here is your menu:", reply_markup=get_main_menu_keyboard())

def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Set Source/Target Channels", callback_data='menu_channels')],
        [InlineKeyboardButton("🎁 Manage Offer Post", callback_data='menu_offer')],
        [InlineKeyboardButton("🛡️ Add Fallback Account", callback_data='menu_fallback')],
        [InlineKeyboardButton("ℹ️ View Status", callback_data='menu_status')],
        [InlineKeyboardButton("📜 View Error Log", callback_data='menu_log')],
        [InlineKeyboardButton("🔄 Force Check Now", callback_data='menu_force_check')],
    ]
    return InlineKeyboardMarkup(keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in db.get('admins', []):
        await update.message.reply_text("You are not authorized to use this bot.")
        return

    help_text = (
        "This bot copies posts from a source channel to a target channel, "
        "replacing the last post and adding an offer post.\n\n"
        "Use the menu to:\n"
        "- Set source and target channels\n"
        "- Manage offer posts\n"
        "- Add fallback accounts\n"
        "- View status and error logs\n"
        "- Force a check for new posts"
    )
    await update.message.reply_text(help_text)

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if user.id not in db.get('admins', []):
        logger.warning(f"Unauthorized callback query attempt by user {user.id} ({user.username}) for data: {query.data}")
        await query.answer("You are not authorized for this action.", show_alert=True)
        return

    await query.answer() # Acknowledge callback
    action = query.data
    message_text = f"Selected: {action}. Implementation pending."

    logger.info(f"Admin {user.id} selected menu option: {action}")

    if action == 'menu_channels':
        message_text = "Channel settings: Manage source and target channels. (Pending)"
        # TODO: Implement channel settings logic and keyboard
    elif action == 'menu_offer':
        message_text = "Offer post management. (Pending)"
        # TODO: Implement offer management logic and keyboard
    elif action == 'menu_fallback':
        message_text = "Fallback account management. (Pending)"
        # TODO: Implement fallback account logic
    elif action == 'menu_status':
        message_text = "Viewing bot status. (Pending)"
        # TODO: Implement status view
    elif action == 'menu_log':
        message_text = "Viewing error log. (Pending)"
        # TODO: Implement log view
    elif action == 'menu_force_check':
        logger.info(f"Admin {user.id} triggered manual check for new posts.")
        # Edit message first to give feedback
        await query.edit_message_text(text="Manual check initiated...", reply_markup=None)
        await check_new_posts(context) # Call the (currently simple) check function
        # Update message again after check (even if it's quick for now)
        message_text = "Manual check process invoked. See logs for details."
        # The main handler will then call query.edit_message_text again with the main menu
    else:
        message_text = "Unknown action. Please try again."
        logger.warning(f"Unknown callback query data: {action} from user {user.id}")

    await query.edit_message_text(text=message_text) #, reply_markup=get_main_menu_keyboard()) # Optionally show menu again or a sub-menu

if __name__ == '__main__':
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in config.py. Exiting.")
        exit()
    if not API_ID or not API_HASH:
        logger.warning("API_ID or API_HASH are not set in config.py. Fallback functionality will not work.")
    # ADMIN_USER_ID can be initially unset, the first user to /start can be made admin if db is empty.
    # Or, set ADMIN_USER_ID in config.py for a predefined admin.

    load_db() # Uses the new load_db

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    if application.job_queue:
        application.job_queue.run_repeating(check_new_posts, interval=15, first=5, name="periodic_post_checker")
        logger.info("Periodic post checking job scheduled every 15 seconds.")
    else:
        logger.error("JobQueue not available on application object. Periodic checks will not run.")

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(main_menu_handler)) # Handles all callback queries

    logger.info("Bot starting...")
    application.run_polling()
    logger.info("Bot stopped.")
