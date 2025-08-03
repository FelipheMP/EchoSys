import os
import time
import requests
import socket
import psutil
import threading
import random
from dotenv import load_dotenv

# === Force only IPv4 ===
orig_getaddrinfo = socket.getaddrinfo


def getaddrinfo_ipv4(*args, **kwargs):
    return [info for info in orig_getaddrinfo(*args, **kwargs) if info[0] == socket.AF_INET]


socket.getaddrinfo = getaddrinfo_ipv4

# === CONFIG ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
PERSONAL_CHAT_ID = os.getenv("PERSONAL_CHAT_ID")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
CHECK_INTERVAL = 120  # Battery check interval (seconds)

# === GLOBAL FLAGS ===
pending_shutdown = False
pending_reboot = False
start_used_by = set()

greeting_responses = [
    "🫡 Reporting for duty, Captain Obvious.",
    "🧠 Yes, yes, hello. Shall we skip the pleasantries?",
    "😐 Greetings, mortal. I hope this isn't your peak social interaction.",
    "🚪 Wow, someone knocked. Should I pretend to care?"
]

sarcastic_responses = [
    "🙄 Again with the /start? What do you want, a medal? I'm already running, Einstein.",
    "🤦 Wow. `/start` again. Groundbreaking innovation here.",
    "🎉 Congrats! You've unlocked... absolutely nothing. I'm still the same bot.",
    "😐 Still here. Still running. Still unimpressed.",
    "🤖 Rebooting your expectations... not the bot.",
    "👏 Great job! You’ve successfully demonstrated your ability to repeat commands.",
    "📢 Attention! User thinks `/start` is a magic spell. Spoiler: it's not.",
    "🤡 /start again? Are we stuck in a loop or is this just your thing?",
    "😴 Oh yay, /start again. My circuits are *thrilled*.",
    "🧠 Pro tip: You only need to use /start once. Wild, I know.",
    "🤖 Already running. Still running. Forever running. What more do you want from me?",
    "⚠️ ERROR 404: Patience not found. Please stop hitting /start.",
    "🫠 I'm beginning to think you're doing this on purpose..."
]

# === FUNCTIONS ===


def send_telegram_message(text, chat_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",  # Allow bold, italic, etc
    }
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send message: {e}")


def get_battery_level():
    try:
        with open("/sys/class/power_supply/BAT0/capacity", "r") as f:
            return int(f.read().strip())
    except Exception as e:
        print(f"Error reading battery charge level: {e}")
        return None


def get_battery_status():
    try:
        with open("/sys/class/power_supply/BAT0/status", "r") as s:
            return s.read().strip()
    except Exception as e:
        print(f"Error reading battery status: {e}")
        return None


def battery_monitor():
    warned_100 = False
    warned_10 = False
    warned_5 = False
    warned_2 = False
    warn_group = False

    while True:
        battery_charge = get_battery_level()
        battery_status = get_battery_status()

        if battery_charge is None:
            time.sleep(CHECK_INTERVAL)
            continue

        print(f"[Battery Monitor] Battery level: {battery_charge}%")
        if battery_charge <= 1 and battery_status != "Charging":
            send_telegram_message(
                "🚨 *Battery CRITICAL (1%)* - Server will shutdown NOW! 🚨", PERSONAL_CHAT_ID)

            if warn_group:
                send_telegram_message(
                    "🚨 *Battery CRITICAL (1%)* - Server will shutdown NOW! 🚨", GROUP_CHAT_ID)

            time.sleep(5)  # Give Telegram some time
            os.system("sudo /sbin/shutdown now")
            break

        elif battery_charge <= 2 and not warned_2 and battery_status != "Charging":
            send_telegram_message(
                "⚠️ *Battery Very Low (2%)* - Please plug in! 🚨", PERSONAL_CHAT_ID)

            if warn_group:
                send_telegram_message(
                    "⚠️ *Battery Very Low (2%)* - Please plug in! 🚨", GROUP_CHAT_ID)
            warned_2 = True

        elif battery_charge <= 5 and not warned_5 and battery_status != "Charging":
            send_telegram_message(
                "⚠️ *Battery Low (5%)* - Connect charger ASAP! ⚡", PERSONAL_CHAT_ID)
            if warn_group:
                send_telegram_message(
                    "⚠️ *Battery Low (5%)* - Connect charger ASAP! ⚡", GROUP_CHAT_ID)
            warned_5 = True

        elif battery_charge <= 10 and not warned_10 and battery_status != "Charging":
            send_telegram_message(
                "⚠️ *Battery at 10%* - Please prepare to charge. 🔋", PERSONAL_CHAT_ID)
            if warn_group:
                send_telegram_message(
                    "⚠️ *Battery at 10%* - Please prepare to charge. 🔋", GROUP_CHAT_ID)
            warned_10 = True

        elif battery_charge == 100 and not warned_100 and battery_status == "Charging":
            send_telegram_message(
                f"🔋 *Battery*: *{battery_charge}%!*\n\nStatus: *FULLY CHARGED!*", PERSONAL_CHAT_ID)
            if warn_group:
                send_telegram_message(
                    f"🔋 *Battery*: *{battery_charge}%!*\n\nStatus: *FULLY CHARGED!*", GROUP_CHAT_ID)
            warned_100 = True

        time.sleep(CHECK_INTERVAL)


def cancel_shutdown():
    global pending_shutdown
    time.sleep(15)
    if pending_shutdown:
        pending_shutdown = False
        send_telegram_message(
            "⌛ Shutdown request canceled (timeout).", PERSONAL_CHAT_ID)


def cancel_reboot():
    global pending_reboot
    time.sleep(15)
    if pending_reboot:
        pending_reboot = False
        send_telegram_message(
            "⌛ Reboot request canceled (timeout).", PERSONAL_CHAT_ID)


def create_bar(percentage, length=10):
    full = int(percentage / (100 / length))
    empty = length - full
    return "█" * full + "░" * empty


def get_temperatures():
    temps = psutil.sensors_temperatures()
    if not temps:
        return "Unavailable"
    temp_readings = []
    for name, entries in temps.items():
        for entry in entries:
            if entry.current is not None:
                temp_readings.append(f"{entry.label or name}: {
                                     entry.current:.1f}°C")
    if temp_readings:
        return "\n".join(temp_readings)
    else:
        return "Unavailable"


def listen_for_commands():
    global pending_shutdown, pending_reboot
    last_update_id = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            if last_update_id:
                url += f"?offset={last_update_id + 1}&timeout=30"

            response = requests.get(url, timeout=35).json()

            for update in response.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id"))
                text = message.get("text", "")

                # Ignore messages from other users/chats
                if chat_id not in [PERSONAL_CHAT_ID, GROUP_CHAT_ID]:
                    print(f"Ignored message from {chat_id}")
                    continue

                #
                if text.strip().lower() in ["/start", f"/start@{BOT_USERNAME}"]:
                    if chat_id not in start_used_by:
                        start_used_by.add(chat_id)
                        send_telegram_message(random.choice(
                            greeting_responses), chat_id)
                    else:
                        send_telegram_message(random.choice(
                            sarcastic_responses), chat_id)

                # Handle battery charge info
                elif text.strip().lower() in ["/battery", f"/battery@{BOT_USERNAME}"]:
                    battery_charge = get_battery_level()
                    battery_status = get_battery_status()
                    if battery_charge is not None:
                        if battery_status == "Charging":
                            reply = f"🔋 *Battery*: *{
                                battery_charge}%*\n\nStatus:🔌{battery_status}"
                        else:
                            reply = f"🔋 *Battery*: *{
                                battery_charge}%*\n\nStatus:❗{battery_status}"
                    else:
                        reply = "❌ Could not read battery level."

                    send_telegram_message(reply, chat_id)

                # Handle all server stats
                elif text.lower() in ["/status", f"/status@{BOT_USERNAME}"]:
                    # CPU Load and CPU Usage
                    load1, load5, load15 = os.getloadavg()
                    cpu_percent = psutil.cpu_percent(interval=1)
                    cpu_bar = create_bar(cpu_percent)

                    # Memory Usage
                    mem = psutil.virtual_memory()
                    mem_total = mem.total / (1024 ** 3)
                    mem_used = mem.used / (1024 ** 3)
                    mem_free = mem.available / (1024 ** 3)
                    mem_percent = mem.percent
                    mem_bar = create_bar(mem_percent)

                    # Disk Usage
                    disk = psutil.disk_usage('/')
                    disk_total = disk.total / (1024 ** 3)
                    disk_used = disk.used / (1024 ** 3)
                    disk_free = disk.free / (1024 ** 3)
                    disk_percent = disk.percent
                    disk_bar = create_bar(disk_percent)

                    home_disk = psutil.disk_usage('/home')
                    home_disk_total = home_disk.total / (1024 ** 3)
                    home_disk_used = home_disk.used / (1024 ** 3)
                    home_disk_free = home_disk.free / (1024 ** 3)
                    home_disk_percent = home_disk.percent
                    home_disk_bar = create_bar(home_disk_percent)
                    
                    # Battery Status
                    battery_level = get_battery_level()
                    batt_status = get_battery_status()
                    if battery_level is not None:
                        battery_charge = f"{battery_level}%"
                        battery_bar = create_bar(battery_level)
                        battery_status = f"{'🔌' if batt_status == "Charging" else '❗'}"
                    else:
                        battery_status = "Unavailable"
                        battery_bar = "N/A"

                    # Uptime
                    uptime = os.popen("uptime -p").read().strip()

                    # Temperature Sensors
                    temperatures = get_temperatures()

                    # Create final status message
                    message = (
                        f"📊 *Machine Status*\n\n"

                        f"🖥️ *CPU:*\n"
                        f"- Load 1min: `{load1:.2f}`\n"
                        f"- Load 5min: `{load5:.2f}`\n"
                        f"- Load 15min: `{load15:.2f}`\n"
                        f"- Usage: `{cpu_percent:.1f}%` [{cpu_bar}]\n\n"

                        f"🌡️ *Temperatures:*\n"
                        f"```\n{temperatures}\n```\n"

                        f"🧠 *Memory:*\n"
                        f"- Total: `{mem_total:.2f} GB`\n"
                        f"- Used: `{mem_used:.2f} GB`\n"
                        f"- Free: `{mem_free:.2f} GB`\n"
                        f"- Usage: `{mem_percent:.1f}%` [{mem_bar}]\n\n"

                        f"💽 *Disk:*\n"
                        f"- / total: `{disk_total:.2f} GB`\n"
                        f"- / used:  `{disk_used:.2f} GB`\n"
                        f"- / free:  `{disk_free:.2f} GB`\n"
                        f"- / usage: `{disk_percent:.1f}%` [{disk_bar}]\n\n"
                        f"- /home total: `{home_disk_total:.2f} GB`\n"
                        f"- /home used:  `{home_disk_used:.2f} GB`\n"
                        f"- /home free:  `{home_disk_free:.2f} GB`\n"
                        f"- /home usage: `{home_disk_percent:.1f}%` [{home_disk_bar}]\n\n"

                        f"🔋 *Battery:*\n"
                        f"- Status: `{battery_charge}`"
                        + (f" [{battery_bar}]" if battery_bar != "N/A" else "")
                        + f"\n-`{battery_status}`{batt_status}"
                        + "\n\n"

                        f"⏳ *Uptime:*\n"
                        f"`{uptime}`"
                    )
                    send_telegram_message(message, chat_id)

                # Handle privacy policy
                elif text.lower() in ["/privacy", f"/privacy@{BOT_USERNAME}"]:
                    message = (
                        "🔐 *Privacy Policy*\n\n"
                        + "EchoSys does not collect or store personal data.\n"
                        + "All system info stays on your machine and is only sent to chats you configure.\n\n"
                        + "Source code: [EchoSys](https://github.com/FelipheMP/EchoSys)\n"
                        + "License: GPL-3.0\n\n"
                        + "You're free to inspect, modify, and self-host it.\n"
                        + "No third-party servers or tracking involved."
                    )
                    send_telegram_message(message, chat_id)

                # Handle suspend
                elif text.lower() in ["/suspend", f"/suspend@{BOT_USERNAME}"]:
                    if chat_id == PERSONAL_CHAT_ID:
                        send_telegram_message(
                            "🔋 Suspending system now...", chat_id)
                        os.system("sudo /bin/systemctl suspend")
                    else:
                        send_telegram_message(
                            "🚫 You are not authorized to suspend the server.", chat_id)

                # Handle reboot
                elif text.lower() in ["/reboot", f"/reboot@{BOT_USERNAME}"]:
                    if chat_id == PERSONAL_CHAT_ID:
                        pending_reboot = True
                        send_telegram_message(
                            "⚠️ Confirm reboot by typing `/confirmreboot` within 15 seconds!", chat_id)
                        threading.Thread(target=cancel_reboot,
                                         daemon=True).start()
                    else:
                        send_telegram_message(
                            "🚫 You are not authorized to reboot the server.", chat_id)

                # Handle shutdown
                elif text.lower() in ["/shutdown", f"/shutdown@{BOT_USERNAME}"]:
                    if chat_id == PERSONAL_CHAT_ID:
                        pending_shutdown = True
                        send_telegram_message(
                            "⚠️ Confirm shutdown by typing `/confirmshutdown` within 15 seconds!", chat_id)
                        threading.Thread(
                            target=cancel_shutdown, daemon=True).start()
                    else:
                        send_telegram_message(
                            "🚫 You are not authorized to reboot the server.", chat_id)

                # Confirm shutdown
                elif text.lower() in ["/confirmshutdown"]:
                    if chat_id == PERSONAL_CHAT_ID and pending_shutdown:
                        send_telegram_message(
                            "🔻 Shutting down now...", chat_id)
                        os.system("sudo /sbin/shutdown now")
                    else:
                        send_telegram_message(
                            "🚫 No shutdown was requested or unauthorized.", chat_id)
                        pending_shutdown = False

                # Confirm reboot
                elif text.lower() in ["/confirmreboot"]:
                    if chat_id == PERSONAL_CHAT_ID and pending_reboot:
                        send_telegram_message("♻️ Rebooting now...", chat_id)
                        os.system("sudo /sbin/reboot")
                    else:
                        send_telegram_message(
                            "🚫 No reboot was requested or unauthorized.", chat_id)
                        pending_reboot = False
                else:
                    send_telegram_message("❓ Unknown command.", chat_id)

        except Exception as e:
            print(f"Error listening for commands: {e}")
            time.sleep(5)

# === MAIN ===


if __name__ == "__main__":
    t1 = threading.Thread(target=battery_monitor, daemon=True)
    t2 = threading.Thread(target=listen_for_commands, daemon=True)

    t1.start()
    t2.start()

    while True:
        time.sleep(60)  # Keep main thread alive
