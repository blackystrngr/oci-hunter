# Oracle Cloud Free Tier Instance Creator (GitHub Actions Edition)

This repository contains a Python script and a GitHub Actions workflow that **automatically attempts to create an Always Free OCI compute instance** (ARM Ampere A1.Flex or AMD E2.1.Micro) on Oracle Cloud Infrastructure. It keeps retrying until it succeeds, making use of GitHub Actions’ generous 6‑hour runtime limit.

The script handles common transient errors (e.g. `Out of host capacity`, `TooManyRequests`, `LimitExceeded`) and can notify you via **Telegram**, **Discord**, or **email** when an instance is created or an error occurs.

---

## 🚀 Features

- ✅ **Unlimited retries** – keeps trying until an instance is successfully launched.
- ✅ **Supports both ARM (A1.Flex) and AMD (E2.1.Micro)** shapes.
- ✅ **Works with one or two E2.1.Micro instances** (second free micro option).
- ✅ **Automatic SSH key generation** if you don’t provide one.
- ✅ **Notifications**: Telegram (recommended), Discord, email (Gmail).
- ✅ **GitHub Actions ready** – schedule runs every 6 hours or trigger manually.
- ✅ **Live log tailing** in the Actions console (`launch_instance.log`).
- ✅ **Artifact upload** – logs and instance details are saved after each run.

---

## 📋 Prerequisites

- An Oracle Cloud Free Tier account (or any OCI tenancy with sufficient quota).
- A GitHub repository (public or private) with **Actions enabled**.
- OCI API credentials (user OCID, tenancy OCID, fingerprint, private key).
- **Telegram** (optional but recommended) – create a bot and get your user ID for instant notifications.

---

## 🔐 Setting up Secrets in GitHub

Go to your repository → **Settings** → **Secrets and variables** → **Actions** and add these secrets:

| Secret Name | Description |
|-------------|-------------|
| `OCI_USER_OCID` | Your OCI user OCID (e.g., `ocid1.user.oc1..aaaa...`) |
| `OCI_TENANCY_OCID` | Your OCI tenancy OCID |
| `OCI_FINGERPRINT` | Fingerprint of the API key (from OCI console) |
| `OCI_PRIVATE_KEY` | **PEM‑encoded private key** (including the `-----BEGIN RSA PRIVATE KEY-----` block) |
| `OCI_REGION` | OCI region (e.g., `us-ashburn-1`, `eu-frankfurt-1`) |
| `OCI_SUBNET_ID` | (Optional) Subnet OCID; if not provided, the first subnet is used. |
| `OCI_IMAGE_ID` | (Optional) Custom image OCID; if omitted, the latest Ubuntu 22.04 image is used. |
| `SSH_PUBLIC_KEY` | (Optional) Your public SSH key (`id_rsa.pub`). If not provided, a new key pair is generated automatically. |
| `TELEGRAM_TOKEN` | (Optional) Bot token from [@BotFather](https://t.me/botfather). |
| `TELEGRAM_USER_ID` | (Optional) Your Telegram user ID (you can get it from [@userinfobot](https://t.me/userinfobot)). |

> **Note:** `TELEGRAM_TOKEN` and `TELEGRAM_USER_ID` are **recommended** for real‑time status updates. If you don’t set them, notifications will be skipped.

---

## ⚙️ Configuration (Environment Variables)

Most settings are controlled via `oci.env` (generated automatically in the workflow). You can adjust these in the `Write oci.env` step of the workflow:

| Variable | Default | Description |
|----------|---------|-------------|
| `OCI_COMPUTE_SHAPE` | `VM.Standard.A1.Flex` | Use `VM.Standard.E2.1.Micro` for AMD. |
| `SECOND_MICRO_INSTANCE` | `True` | Allow a second E2.1.Micro instance (only relevant for AMD shape). |
| `REQUEST_WAIT_TIME_SECS` | `90` | Seconds to wait before retrying after a capacity error. |
| `DISPLAY_NAME` | `agokola` | Name of the instance. |
| `OCT_FREE_AD` | `AD-1` | Availability Domain (e.g., `AD-1`, `AD-2`). Use comma‑separated values to cycle. |
| `ASSIGN_PUBLIC_IP` | `false` | Set to `true` to assign a public IP to the instance. |
| `BOOT_VOLUME_SIZE` | `50` | Boot volume size in GB (minimum 50). |

---

## 🧪 Running Locally (for testing)

1. **Clone** this repository.
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
