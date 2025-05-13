import os
import time
import requests
import socket
import psutil
import threading
from dotenv import load_dotenv

# === Force only IPv4 ===
orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(*args, **kwargs):
    return [info for info in orig_getaddrinfo(*args, **kwargs) if info[0] == socket.AF_INET]

socket.getaddrinfo = getaddrinfo_ipv4

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
PERSONAL_CHAT_ID = os.getenv("PERSONAL_CHAT_ID")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
CHECK_INTERVAL = 120 # Battery check interval (seconds)

# === GLOBAL FLAGS ===
pending_shutdown = False
pending_reboot = False

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
        print(f"Error reading battery: {e}")
        return None

def battery_monitor():
    warned_100 = False
    warned_10 = False
    warned_5 = False
    warned_2 = False

    while True:
        battery = get_battery_level()
        if battery is None:
            time.sleep(CHECK_INTERVAL)
            continue

        print(f"[Battery Monitor] Battery level: {battery}%")
        if battery <= 1:
            send_telegram_message("🚨 *Battery CRITICAL (1%)* - Server will shutdown NOW! 🚨", PERSONAL_CHAT_ID)
            #send_telegram_message("🚨 *Battery CRITICAL (1%)* - Server will shutdown NOW! 🚨", GROUP_CHAT_ID)
            time.sleep(5)  # Give Telegram some time
            os.system("sudo /sbin/shutdown now")
            break
            
        elif battery <= 2 and not warned_2:
            send_telegram_message("⚠️ *Battery Very Low (2%)* - Please plug in! 🚨", PERSONAL_CHAT_ID)
            send_telegram_message("⚠️ *Battery Very Low (2%)* - Please plug in! 🚨", GROUP_CHAT_ID)
            warned_2 = True

        elif battery <= 5 and not warned_5:
            send_telegram_message("⚠️ *Battery Low (5%)* - Connect charger ASAP! ⚡", PERSONAL_CHAT_ID)
            send_telegram_message("⚠️ *Battery Low (5%)* - Connect charger ASAP! ⚡", GROUP_CHAT_ID)
            warned_5 = True

        elif battery <= 10 and not warned_10:
            send_telegram_message("⚠️ *Battery at 10%* - Please prepare to charge. 🔋", PERSONAL_CHAT_ID)
            send_telegram_message("⚠️ *Battery at 10%* - Please prepare to charge. 🔋", GROUP_CHAT_ID)
            warned_10 = True
            
        elif battery == 100 and not warned_100:
            send_telegram_message(f"🔋 *Server Battery*: *{battery}%!*\n\nStatus: *FULLY CHARGED!*", PERSONAL_CHAT_ID)
            send_telegram_message(f"🔋 *Server Battery*: *{battery}%!*\n\nStatus: *FULLY CHARGED!*", GROUP_CHAT_ID)
            warned_100 = True            

        time.sleep(CHECK_INTERVAL)

def cancel_shutdown():
    global pending_shutdown
    time.sleep(30)
    if pending_shutdown:
        pending_shutdown = False
        send_telegram_message("⌛ Shutdown request canceled (timeout).", PERSONAL_CHAT_ID)

def cancel_reboot():
    global pending_reboot
    time.sleep(30)
    if pending_reboot:
        pending_reboot = False
        send_telegram_message("⌛ Reboot request canceled (timeout).", PERSONAL_CHAT_ID)

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
                temp_readings.append(f"{entry.label or name}: {entry.current:.1f}°C")
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

                # Handle battery charge info
                if text.strip().lower() in ("/battery", f"/battery@{BOT_USERNAME}"):
                    battery = get_battery_level()
                    if battery is not None:
                        reply = f"🔋 *Server Battery*: *{battery}%*\n\nStatus: {'✅ Good' if battery > 20 else '⚠️ Low'}"
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
                
                    # Battery Status
                    battery_level = get_battery_level()
                    if battery_level is not None:
                        battery_status = f"{battery_level}% {'✅' if battery_level > 20 else '⚠️'}"
                        battery_bar = create_bar(battery_level)
                    else:
                        battery_status = "Unavailable"
                        battery_bar = "N/A"
                
                    # Uptime
                    uptime = os.popen("uptime -p").read().strip()
                
                    # Temperature Sensors
                    temperatures = get_temperatures()
                
                    # Create final status message
                    message = (
                        f"📊 *Server Status*\n\n"
                
                        f"🖥️ *CPU:*\n"
                        f"- Load 1min: `{load1:.2f}`\n- Load 5min: `{load5:.2f}`\n- Load 15min: `{load15:.2f}`\n"
                        f"- Usage: `{cpu_percent:.1f}%` [{cpu_bar}]\n\n"
                
                        f"🌡️ *Temperatures:*\n"
                        f"```\n{temperatures}\n```\n"
                
                        f"🧠 *Memory:*\n"
                        f"- Total: `{mem_total:.2f} GB`\n"
                        f"- Used: `{mem_used:.2f} GB`\n"
                        f"- Free: `{mem_free:.2f} GB`\n"
                        f"- Usage: `{mem_percent:.1f}%` [{mem_bar}]\n\n"
                
                        f"💽 *Disk:*\n"
                        f"- Total: `{disk_total:.2f} GB`\n"
                        f"- Used: `{disk_used:.2f} GB`\n"
                        f"- Free: `{disk_free:.2f} GB`\n"
                        f"- Usage: `{disk_percent:.1f}%` [{disk_bar}]\n\n"
                
                        f"🔋 *Battery:*\n"
                        f"- Status: `{battery_status}`"
                        + (f" [{battery_bar}]" if battery_bar != "N/A" else "") +
                        "\n\n"
                
                        f"⏳ *Uptime:*\n"
                        f"`{uptime}`"
                    )
                    send_telegram_message(message, chat_id)

                # Handle privacy policy
                elif text.lower() in ["/privacy", f"/privacy@{BOT_USERNAME}"]:
                    message = (
                        f"🔐 *Privacy Policy*\n\n"
                        
                        f"EchoSys does not collect or store personal data.\n"
                        f"All system info stays on your machine and is only sent to chats you configure.\n\n"
                        
                        f"Source code: [EchoSys](https://github.com/FelipheMP/EchoSys)\n"
                        f"License: GPL-3.0\n\n"
                        
                        f"You're free to inspect, modify, and self-host it.\n"
                        f"No third-party servers or tracking involved."
                    )
                    send_telegram_message(message, chat_id)
                
                # Handle reboot
                elif text.lower() in ["/reboot", f"/reboot@{BOT_USERNAME}"]:
                    if chat_id == PERSONAL_CHAT_ID:
                        pending_reboot = True
                        send_telegram_message("⚠️ Confirm reboot by typing `/confirmreboot` within 30 seconds!", chat_id)
                        threading.Thread(target=cancel_reboot, daemon=True).start()                           
                    else:
                        send_telegram_message("🚫 You are not authorized to reboot the server.", chat_id)

                # Handle shutdown
                elif text.lower() in ["/shutdown", f"/shutdown@{BOT_USERNAME}"]:
                    if chat_id == PERSONAL_CHAT_ID:
                        pending_shutdown = True
                        send_telegram_message("⚠️ Confirm shutdown by typing `/confirmshutdown` within 30 seconds!", chat_id)
                        threading.Thread(target=cancel_shutdown, daemon=True).start()
                    else:
                        send_telegram_message("🚫 You are not authorized to reboot the server.", chat_id)

                # Confirm shutdown
                elif text.lower() in ["/confirmshutdown"]:
                    if chat_id == PERSONAL_CHAT_ID and pending_shutdown:
                        send_telegram_message("🔻 Shutting down now...", chat_id)
                        os.system("sudo /sbin/shutdown now")
                    else:
                        send_telegram_message("🚫 No shutdown was requested or unauthorized.", chat_id)
                        pending_shutdown = False
                
                # Confirm reboot
                elif text.lower() in ["/confirmreboot"]:
                    if chat_id == PERSONAL_CHAT_ID and pending_reboot:
                        send_telegram_message("♻️ Rebooting now...", chat_id)
                        os.system("sudo /sbin/reboot")
                    else:
                        send_telegram_message("🚫 No reboot was requested or unauthorized.", chat_id)
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
