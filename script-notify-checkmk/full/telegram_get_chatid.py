#!/usr/bin/env python3
"""telegram_get_chatid.py - Utility to get CHAT_ID and verify TOKEN

Usage:
    python3 telegram_get_chatid.py
    python3 telegram_get_chatid.py --token 1234567890:AAxxxxxx

Version: 1.0.0"""

import sys
import json
import argparse
import urllib.request
import urllib.error

VERSION = "1.0.0"


def get_updates(token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_me(token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/getMe"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Telegram CHAT_ID finder v{VERSION}")
    parser.add_argument("--token", help="Bot token (altrimenti verrà chiesto interattivamente)")
    args = parser.parse_args()

    token = args.token
    if not token:
        token = input("Inserisci il TOKEN del bot: ").strip()

    if not token:
        print("ERROR: Token vuoto.")
        return 1

    print(f"\n{'='*55}")
    print(f"  telegram_get_chatid v{VERSION}")
    print(f"{'='*55}\n")

    # Verify token via getMe
    try:
        me = get_me(token)
        if not me.get("ok"):
            print(f"ERROR: Token non valido → {me.get('description', 'unknown')}")
            return 1
        bot = me["result"]
        print(f"Bot verificato: @{bot['username']} (id: {bot['id']})")
        print(f"  TELEGRAM_TOKEN={token}\n")
    except urllib.error.HTTPError as e:
        print(f"ERROR: Token non valido (HTTP {e.code})")
        return 1
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    # Get updates to find CHAT_ID
    try:
        updates = get_updates(token)
    except Exception as e:
        print(f"ERROR getUpdates: {e}")
        return 1

    if not updates.get("ok") or not updates.get("result"):
        print("Nessun update trovato.")
        print("→ Manda un messaggio nel canale/gruppo col bot dentro, poi rilancia lo script.\n")
        return 0

    # Raccogli chat univoche
    chats: dict = {}
    for upd in updates["result"]:
        # Messaggi normali
        msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message")
        if msg and "chat" in msg:
            chat = msg["chat"]
            chats[chat["id"]] = chat

        # my_chat_member (bot added to channel/group)
        mcm = upd.get("my_chat_member")
        if mcm and "chat" in mcm:
            chat = mcm["chat"]
            chats[chat["id"]] = chat

    if not chats:
        print("Nessuna chat trovata negli update.")
        print("→ Manda un messaggio nel canale/gruppo col bot dentro, poi rilancia lo script.\n")
        return 0

    print(f"Chat trovate ({len(chats)}):\n")
    for chat_id, chat in chats.items():
        chat_type = chat.get("type", "?")
        title = chat.get("title") or chat.get("username") or chat.get("first_name", "?")
        print(f"  [{chat_type.upper()}] {title}")
        print(f"  TELEGRAM_CHAT_ID={chat_id}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
