import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from database import DatabaseManager

logger = logging.getLogger(__name__)

class MonitoringManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.active_monitors = {}
        self.stats = {
            'messages_processed': 0,
            'errors_count': 0,
            'last_activity': None
        }
    
    async def start_monitoring(self, channel_config: Dict):
        """Start monitoring for a specific channel"""
        channel_id = channel_config['id']
        
        if channel_id in self.active_monitors:
            await self.stop_monitoring(channel_id)
        
        monitor_task = asyncio.create_task(
            self._monitor_channel(channel_config)
        )
        
        self.active_monitors[channel_id] = {
            'task': monitor_task,
            'config': channel_config,
            'started_at': datetime.now(),
            'messages_processed': 0,
            'last_message_time': None
        }
        
        logger.info(f"Started monitoring for channel {channel_id}")
    
    async def stop_monitoring(self, channel_id: int):
        """Stop monitoring for a specific channel"""
        if channel_id in self.active_monitors:
            monitor = self.active_monitors[channel_id]
            monitor['task'].cancel()
            
            try:
                await monitor['task']
            except asyncio.CancelledError:
                pass
            
            del self.active_monitors[channel_id]
            logger.info(f"Stopped monitoring for channel {channel_id}")
    
    async def _monitor_channel(self, channel_config: Dict):
        """Monitor a single channel for new messages"""
        channel_id = channel_config['id']
        
        while True:
            try:
                # Check for new messages
                await self._check_for_new_messages(channel_config)
                
                # Update stats
                self.stats['last_activity'] = datetime.now()
                
                # Wait before next check
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring channel {channel_id}: {e}")
                self.stats['errors_count'] += 1
                await asyncio.sleep(30)  # Wait longer after error
    
    async def _check_for_new_messages(self, channel_config: Dict):
        """Check for new messages in source channel"""
        # This would integrate with TelegramClientManager
        # Implementation depends on the specific monitoring logic
        pass
    
    def get_monitoring_stats(self) -> Dict:
        """Get current monitoring statistics"""
        active_count = len(self.active_monitors)
        total_processed = sum(m['messages_processed'] for m in self.active_monitors.values())
        
        return {
            'active_channels': active_count,
            'total_messages_processed': total_processed,
            'global_errors': self.stats['errors_count'],
            'last_activity': self.stats['last_activity'],
            'uptime': datetime.now() - min([m['started_at'] for m in self.active_monitors.values()]) if self.active_monitors else timedelta(0)
        }
    
    async def cleanup(self):
        """Cleanup all monitoring tasks"""
        for channel_id in list(self.active_monitors.keys()):
            await self.stop_monitoring(channel_id)
        
        logger.info("Monitoring cleanup completed")