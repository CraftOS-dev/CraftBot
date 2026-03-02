#!/usr/bin/env python3
"""
Telegram Bot Setup Script
Automates the process of setting up a Telegram bot in OpenClaw
"""

import json
import os
import sys
import subprocess
from pathlib import Path


class TelegramBotSetup:
    def __init__(self):
        self.workspace = Path("/home/openclaw/.openclaw/workspace")
        self.config_path = Path("/home/openclaw/.openclaw/openclaw.json")
        
    def get_bot_token(self) -> str:
        """Get bot token from user"""
        print("📋 Telegram Bot Setup")
        print("=" * 50)
        
        print("\n1. Get your bot token from BotFather:")
        print("   - Open Telegram and search for @BotFather")
        print("   - Send /newbot command")
        print("   - Follow the prompts")
        print("   - Copy the token (format: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz)")
        
        token = input("\nEnter your bot token: ").strip()
        
        if not token:
            print("❌ Bot token cannot be empty")
            sys.exit(1)
        
        if ':' not in token:
            print("❌ Invalid token format. Should contain a colon.")
            sys.exit(1)
        
        return token
    
    def backup_config(self) -> bool:
        """Backup existing config"""
        if not self.config_path.exists():
            print(f"\nℹ️  No existing config found at {self.config_path}")
            return True
        
        backup_path = self.config_path.with_suffix('.json.backup')
        
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            with open(backup_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            print(f"\n✅ Backed up existing config to {backup_path}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to backup config: {e}")
            return False
    
    def load_config(self) -> dict:
        """Load existing OpenClaw config"""
        if not self.config_path.exists():
            return {}
        
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Failed to load config: {e}")
            return {}
    
    def update_config(self, bot_token: str) -> bool:
        """Update OpenClaw config with Telegram settings"""
        print(f"\n📝 Updating OpenClaw configuration...")
        
        config = self.load_config()
        
        # Ensure telegram section exists
        if 'telegram' not in config:
            config['telegram'] = {}
        
        # Update telegram settings
        config['telegram'].update({
            'enabled': True,
            'token': bot_token,
            'pairing': True,
            'streamMode': 'partial'
        })
        
        # Ensure telegram plugin is enabled
        if 'plugins' not in config:
            config['plugins'] = []
        
        if 'telegram' not in config['plugins']:
            config['plugins'].append('telegram')
        
        try:
            # Write updated config
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            print(f"✅ Configuration updated successfully")
            print(f"   - Telegram enabled: True")
            print(f"   - Pairing mode: True")
            print(f"   - Stream mode: partial")
            print(f"   - Plugin added: telegram")
            return True
            
        except Exception as e:
            print(f"❌ Failed to update config: {e}")
            return False
    
    def test_telegram_api(self, bot_token: str) -> bool:
        """Test Telegram API connectivity"""
        print(f"\n🧪 Testing Telegram API connectivity...")
        
        try:
            import requests
            
            # Test basic connectivity
            response = requests.get(
                "https://api.telegram.org",
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Telegram API not reachable (status: {response.status_code})")
                return False
            
            # Test bot token
            response = requests.get(
                f"https://api.telegram.org/bot{bot_token}/getMe",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data['result']
                    print(f"✅ Bot token is valid")
                    print(f"   Username: @{bot_info.get('username')}")
                    print(f"   Name: {bot_info.get('first_name')}")
                    return True
                else:
                    print(f"❌ Invalid bot token: {data.get('description')}")
                    return False
            else:
                print(f"❌ Failed to validate token (status: {response.status_code})")
                return False
                
        except ImportError:
            print("⚠️  requests module not available, skipping API test")
            return True
        except Exception as e:
            print(f"⚠️  Could not test API: {e}")
            return True  # Don't fail setup due to test issues
    
    def restart_openclaw(self) -> bool:
        """Restart OpenClaw gateway"""
        print(f"\n🔄 Restarting OpenClaw gateway...")
        
        try:
            result = subprocess.run(
                ['openclaw', 'gateway', 'restart'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print("✅ OpenClaw gateway restarted successfully")
                return True
            else:
                print(f"❌ Failed to restart gateway: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("⚠️  Restart timed out, but may have succeeded")
            return True
        except Exception as e:
            print(f"⚠️  Could not restart gateway: {e}")
            print("   You may need to restart manually: openclaw gateway restart")
            return True  # Don't fail setup
    
    def show_next_steps(self, bot_token: str):
        """Show next steps for using the bot"""
        print(f"\n" + "=" * 60)
        print("🎉 Setup Complete!")
        print("=" * 60)
        
        print(f"\n📱 Next Steps:")
        print(f"1. Open Telegram and search for your bot")
        print(f"2. Send /start to begin conversation")
        print(f"3. The bot will provide pairing instructions")
        print(f"4. Follow the pairing process to link your Telegram account")
        
        print(f"\n🔧 Manual Commands:")
        print(f"   Check status: openclaw status")
        print(f"   View logs: openclaw gateway logs -f")
        print(f"   Restart: openclaw gateway restart")
        
        print(f"\n🧪 Testing:")
        print(f"   Run: python3 telegram-bot-manager/scripts/test_bot.py")
        print(f"   Or: export TELEGRAM_BOT_TOKEN={bot_token}")
        print(f"        python3 telegram-bot-manager/scripts/test_bot.py")
        
        print(f"\n📚 Documentation:")
        print(f"   - See references/OPENCLAW_CONFIG.md for detailed config")
        print(f"   - See references/WEBHOOK_SETUP.md for webhook setup")
        
        print(f"\n⚠️  Security Reminder:")
        print(f"   - Keep your bot token secure")
        print(f"   - Never commit tokens to version control")
        print(f"   - Rotate token if compromised")
    
    def run(self):
        """Main setup process"""
        print("Telegram Bot Setup for OpenClaw")
        print("=" * 60)
        
        # Get bot token
        bot_token = self.get_bot_token()
        
        # Backup existing config
        if not self.backup_config():
            print("\n❌ Failed to backup existing config")
            sys.exit(1)
        
        # Test Telegram API
        if not self.test_telegram_api(bot_token):
            print("\n⚠️  Telegram API test failed, but continuing with setup...")
            print("   You may need to check network connectivity later.")
        
        # Update config
        if not self.update_config(bot_token):
            print("\n❌ Failed to update configuration")
            sys.exit(1)
        
        # Restart OpenClaw
        if not self.restart_openclaw():
            print("\n⚠️  Failed to restart OpenClaw automatically")
            print("   Please run: openclaw gateway restart")
        
        # Show next steps
        self.show_next_steps(bot_token)


def main():
    """Main entry point"""
    try:
        setup = TelegramBotSetup()
        setup.run()
    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
