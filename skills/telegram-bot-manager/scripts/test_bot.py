#!/usr/bin/env python3
"""
Telegram Bot Test Script
Tests bot connectivity and basic functionality
"""

import requests
import json
import sys
import os
from typing import Dict, Any, Optional


class TelegramBotTester:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
    def test_connectivity(self) -> bool:
        """Test basic connectivity to Telegram API"""
        print("🧪 Testing Telegram API connectivity...")
        
        try:
            response = requests.get(
                "https://api.telegram.org",
                timeout=10,
                headers={'User-Agent': 'OpenClaw-Bot-Tester/1.0'}
            )
            
            if response.status_code == 200:
                print("✅ Telegram API is reachable")
                return True
            else:
                print(f"❌ Telegram API returned status: {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            print("❌ Connection timeout - network may be blocked")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Connection error: {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False
    
    def test_bot_token(self) -> Optional[Dict[str, Any]]:
        """Test if bot token is valid"""
        print("\n🧪 Testing bot token validity...")
        
        try:
            response = requests.get(
                f"{self.base_url}/getMe",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data['result']
                    print(f"✅ Bot token is valid")
                    print(f"   Bot username: @{bot_info.get('username')}")
                    print(f"   Bot ID: {bot_info.get('id')}")
                    print(f"   Bot name: {bot_info.get('first_name')}")
                    return bot_info
                else:
                    print(f"❌ Bot token is invalid: {data.get('description')}")
                    return None
            else:
                print(f"❌ Request failed with status: {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            print("❌ Request timeout")
            return None
        except Exception as e:
            print(f"❌ Error testing bot token: {e}")
            return None
    
    def test_get_updates(self) -> bool:
        """Test if bot can receive updates (polling mode)"""
        print("\n🧪 Testing bot update retrieval...")
        
        try:
            response = requests.get(
                f"{self.base_url}/getUpdates",
                params={'timeout': 5, 'limit': 1},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    updates = data.get('result', [])
                    print(f"✅ Bot can retrieve updates")
                    print(f"   Pending updates: {len(updates)}")
                    return True
                else:
                    print(f"❌ Failed to get updates: {data.get('description')}")
                    return False
            else:
                print(f"❌ Request failed with status: {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            print("⚠️  Timeout - this is normal if no updates are pending")
            return True
        except Exception as e:
            print(f"❌ Error getting updates: {e}")
            return False
    
    def test_webhook_info(self) -> Optional[Dict[str, Any]]:
        """Check webhook configuration"""
        print("\n🧪 Checking webhook configuration...")
        
        try:
            response = requests.get(
                f"{self.base_url}/getWebhookInfo",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    webhook_info = data['result']
                    url = webhook_info.get('url', '')
                    
                    if url:
                        print(f"✅ Webhook is configured")
                        print(f"   URL: {url}")
                        print(f"   Pending updates: {webhook_info.get('pending_update_count', 0)}")
                        print(f"   Max connections: {webhook_info.get('max_connections', 40)}")
                    else:
                        print("ℹ️  No webhook configured (using polling mode)")
                    
                    return webhook_info
                else:
                    print(f"❌ Failed to get webhook info: {data.get('description')}")
                    return None
            else:
                print(f"❌ Request failed with status: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error checking webhook: {e}")
            return None
    
    def comprehensive_test(self) -> bool:
        """Run all tests"""
        print("=" * 60)
        print("Telegram Bot Comprehensive Test")
        print("=" * 60)
        
        all_passed = True
        
        # Test 1: API connectivity
        if not self.test_connectivity():
            all_passed = False
            print("\n❌ Cannot proceed with other tests due to connectivity issues")
            return False
        
        # Test 2: Bot token
        bot_info = self.test_bot_token()
        if not bot_info:
            all_passed = False
            print("\n❌ Cannot proceed with other tests due to invalid token")
            return False
        
        # Test 3: Get updates
        if not self.test_get_updates():
            all_passed = False
        
        # Test 4: Webhook info
        webhook_info = self.test_webhook_info()
        
        print("\n" + "=" * 60)
        if all_passed:
            print("✅ All tests passed! Bot is ready to use.")
        else:
            print("❌ Some tests failed. Please check the issues above.")
        print("=" * 60)
        
        return all_passed


def main():
    """Main function"""
    # Get bot token from environment or argument
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if len(sys.argv) > 1:
        bot_token = sys.argv[1]
    
    if not bot_token:
        print("❌ No bot token provided")
        print("\nUsage:")
        print("  python3 test_bot.py YOUR_BOT_TOKEN")
        print("  or")
        print("  export TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN")
        print("  python3 test_bot.py")
        sys.exit(1)
    
    # Validate token format
    if ':' not in bot_token:
        print("❌ Invalid bot token format")
        print("   Expected format: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
        sys.exit(1)
    
    # Run tests
    tester = TelegramBotTester(bot_token)
    success = tester.comprehensive_test()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
