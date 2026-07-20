"""
setup_env.py - Interactive oci.env generator.

Pure-Python replacement for setup_env.sh. Works identically on Windows,
macOS, and Linux. Run it with:

    python setup_env.py

It will ask a few questions and write out oci.env (backing up any
existing one to oci.env.bak first).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def ask(prompt, default=""):
    value = input(prompt).strip()
    return value if value else default


def ask_yes_no(prompt):
    while True:
        answer = input(prompt).strip().lower()
        if answer == "y":
            return True
        if answer == "n":
            return False
        print("Invalid choice. Please enter 'y' or 'n'.")


def ask_shape():
    print("Choose one of the two free shapes")
    print("1. VM.Standard.A1.Flex (ARM: 4 OCPU / 24GB RAM)")
    print("2. VM.Standard.E2.1.Micro (AMD: 1 OCPU / 1GB RAM)")
    while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            return "VM.Standard.A1.Flex"
        if choice == "2":
            return "VM.Standard.E2.1.Micro"
        print("Invalid choice. Please try again.")


def main():
    print("=== Oracle Free Tier Instance Creation - oci.env setup ===\n")

    instance_name = ask("Type name of the instance: ", "my-arm-ubuntu-instance")
    shape = ask_shape()
    second_micro = ask_yes_no("Use the script for your second free tier Micro Instance? (y/n): ")
    subnet_id = ask("Enter the Subnet OCID (or press Enter to skip - required if running from Windows/local): ")
    image_id = ask("Enter the Image OCID (or press Enter to skip): ")

    notify_email = ask_yes_no("Enable Gmail notification? (y/n): ")
    email = ""
    email_password = ""
    if notify_email:
        email = ask("Enter your Gmail address: ")
        email_password = ask("Enter Gmail app password (16 characters, no spaces): ")

    discord_webhook = ask("Enter Discord webhook URL (or press Enter to skip): ")
    telegram_token = ask("Enter Telegram bot token (or press Enter to skip): ")
    telegram_user_id = ask("Enter Telegram user ID (or press Enter to skip): ")

    env_path = BASE_DIR / "oci.env"
    if env_path.is_file():
        backup_path = BASE_DIR / "oci.env.bak"
        env_path.replace(backup_path)
        print(f"Existing oci.env backed up as {backup_path.name}")

    content = f"""# OCI Configuration
# Paths below are relative to this project folder so the setup works
# regardless of your Windows username / drive letter.
OCI_CONFIG=oci_config
OCT_FREE_AD=AD-1
DISPLAY_NAME={instance_name}

# The other free shape is AMD: VM.Standard.E2.1.Micro
OCI_COMPUTE_SHAPE={shape}
SECOND_MICRO_INSTANCE={"True" if second_micro else "False"}
REQUEST_WAIT_TIME_SECS=60
SSH_AUTHORIZED_KEYS_FILE=id_rsa.pub

# SUBNET_ID to use ONLY in case running locally (e.g. from Windows) or
# from a non E2.1.Micro instance.
OCI_SUBNET_ID={subnet_id}
OCI_IMAGE_ID={image_id}

# The following are ignored if OCI_IMAGE_ID is specified
OPERATING_SYSTEM=Canonical Ubuntu
OS_VERSION=22.04

ASSIGN_PUBLIC_IP=false

# Boot volume size in GB (minimum is 50)
BOOT_VOLUME_SIZE=50

# Gmail Notification
NOTIFY_EMAIL={"True" if notify_email else "False"}
EMAIL={email}
EMAIL_PASSWORD={email_password}

# Discord Notification (optional)
DISCORD_WEBHOOK={discord_webhook}

# Telegram Notification (optional)
TELEGRAM_TOKEN={telegram_token}
TELEGRAM_USER_ID={telegram_user_id}
"""

    env_path.write_text(content, encoding="utf-8")
    print(f"\nOCI env configuration saved to {env_path}")
    print(
        "\nNext steps:\n"
        "  1. Put your OCI API private key next to this script (e.g. oci_api_private_key.pem)\n"
        "  2. Create 'oci_config' next to this script - copy sample_oci_config and fill it in\n"
        "  3. Run: python setup_init.py\n"
    )


if __name__ == "__main__":
    main()
