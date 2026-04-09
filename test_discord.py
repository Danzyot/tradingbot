import sys
sys.path.insert(0, 'src')
from smc_bot.journal.discord_client import DiscordClient
d = DiscordClient()
print('Webhook URL loaded OK:', d.webhook_url[:50] + '...')
