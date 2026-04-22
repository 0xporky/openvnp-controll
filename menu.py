#!/usr/bin/env python3
"""Interactive menu for OpenVPN controller with arrow-key navigation."""

import os
import subprocess
import sys
import tty
import termios


MENU_ITEMS = [
    ("Setup", "Initial setup: install OpenVPN, generate clients, create snapshot"),
    ("Start VPN", "Create droplet from snapshot and start VPN"),
    ("Start VPN (timed)", "Create droplet, auto-destroy after 1-12 hours"),
    ("Stop VPN", "Destroy the running droplet (snapshot preserved)"),
    ("Status", "Show VPN status, DNS, and snapshots"),
    ("Cleanup", "Delete ALL droplets and snapshots"),
    ("Clear Clients", "Delete local .ovpn client configs"),
    ("Start Bot", "Run the Telegram bot"),
    ("Quit", "Exit"),
]

COMMANDS = {
    0: [sys.executable, "cli.py", "setup"],
    1: [sys.executable, "cli.py", "up"],
    2: [sys.executable, "cli.py", "up-timed"],
    3: [sys.executable, "cli.py", "down"],
    4: [sys.executable, "cli.py", "status"],
    5: [sys.executable, "cli.py", "cleanup"],
    6: [sys.executable, "cli.py", "clear-clients"],
    7: [sys.executable, "cli.py", "bot"],
}


def read_key() -> str:
    """Read a single keypress, handling arrow key escape sequences."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return "esc"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "q":
            return "quit"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")


def draw_menu(selected: int):
    clear_screen()
    print("\033[1m  OpenVPN Controller\033[0m")
    print("  Use \033[1m↑↓\033[0m to navigate, \033[1mEnter\033[0m to select, \033[1mq\033[0m to quit\n")

    for i, (label, desc) in enumerate(MENU_ITEMS):
        if i == selected:
            print(f"  \033[38;5;114m > {label:<18} \033[0m  {desc}")
        else:
            print(f"    {label:<18}   {desc}")

    print()


def run_command(index: int):
    """Run the CLI command for the given menu index."""
    if index not in COMMANDS:
        return

    clear_screen()
    label = MENU_ITEMS[index][0]
    print(f"\033[1m  Running: {label}\033[0m\n")

    try:
        subprocess.run(COMMANDS[index], cwd=os.path.dirname(os.path.abspath(__file__)))
    except KeyboardInterrupt:
        print("\n\nInterrupted.")

    print("\n  Press any key to return to menu...")
    read_key()


def main():
    selected = 0
    last = len(MENU_ITEMS) - 1

    while True:
        draw_menu(selected)

        key = read_key()

        if key == "up":
            selected = last if selected == 0 else selected - 1
        elif key == "down":
            selected = 0 if selected == last else selected + 1
        elif key == "enter":
            if selected == last:  # Quit
                clear_screen()
                break
            run_command(selected)
        elif key in ("quit", "esc"):
            clear_screen()
            break


if __name__ == "__main__":
    main()
