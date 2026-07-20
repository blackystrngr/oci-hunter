# Oracle Free Tier Instance Creation - Windows Edition (Pure Python, No venv)

This is a Windows-friendly rebuild of
[mohankumarpaluru/oracle-freetier-instance-creation](https://github.com/mohankumarpaluru/oracle-freetier-instance-creation).

What changed from the original:

- The two Bash setup scripts (`setup_env.sh`, `setup_init.sh`) are now
  **`setup_env.py`** and **`setup_init.py`** - plain Python, no Bash/WSL/curl needed.
- **No virtual environment.** Dependencies install straight into whichever
  Python you run the scripts with (`pip install -r requirements.txt` under
  the hood via `sys.executable -m pip`).
- `oci.env` and `sample_oci_config` use **relative, portable paths**
  (`oci_config`, `id_rsa.pub`, etc.) instead of hardcoded
  `/home/ubuntu/...` paths. `main.py` resolves relative paths against its
  own folder, so it works no matter what your Windows username or drive
  letter is, and no matter what folder you launch it from.
- `main.py` fails with a clear message instead of crashing if `oci_config`
  is missing, and logs go into the project folder regardless of OS.

## Requirements

- Python 3.9+ for Windows, installed from [python.org](https://www.python.org/downloads/windows/)
  or the Microsoft Store. **When installing, tick "Add python.exe to PATH."**
- An Oracle Cloud account with API key access.

Check Python is on PATH by opening PowerShell or Command Prompt and running:

```
python --version
```

## Setup

1. Download/clone this folder anywhere on your PC, e.g. `C:\Users\you\oracle-freetier-instance-creation`.

2. Open a terminal (PowerShell or CMD) **inside that folder**:

   ```
   cd C:\Users\you\oracle-freetier-instance-creation
   ```

3. Install dependencies directly (no venv):

   ```
   python -m pip install -r requirements.txt
   ```

   (`setup_init.py` also does this automatically on first run - step 3 here
   is just so you can test imports/troubleshoot separately if needed.)

4. Get your OCI API key following Oracle's key-generation steps, then:
   - Save the private key file as `oci_api_private_key.pem` in this folder
     (any name/location works, as long as `key_file` in `oci_config` points
     to it).
   - Copy `sample_oci_config` to a new file named `oci_config` (no
     extension) and fill in `user`, `fingerprint`, `tenancy`, `region`, and
     `key_file`.

5. Generate your `oci.env` interactively:

   ```
   python setup_env.py
   ```

   This asks a few questions (instance name, shape, notifications, etc.)
   and writes `oci.env` for you. If one already exists it's backed up to
   `oci.env.bak` first. You can also just hand-edit `oci.env` directly -
   see the comments in the file.

   **Running from your own Windows PC (not an OCI micro instance):** you
   must fill in `OCI_SUBNET_ID` in `oci.env`, since there's no existing OCI
   VM to inherit a subnet from. Find it in the OCI Console under
   *Networking > Virtual Cloud Networks > `<your VCN>` > Subnet Details*.

## Run

```
python setup_init.py
```

This will:

1. Install/upgrade dependencies (skip with `python setup_init.py rerun`).
2. Launch `main.py`, which retries instance creation every
   `REQUEST_WAIT_TIME_SECS` seconds until it succeeds.
3. Watch the log files and print/notify status.
4. Keep running and checking every 60 seconds until `main.py` exits.

Press **Ctrl+C** at any time to stop it cleanly - it will terminate the
background instance-creation process and send a notification if Discord or
Telegram are configured.

To re-run later without reinstalling dependencies:

```
python setup_init.py rerun
```

### What gets created in this folder while running

- `setup_and_info.log` / `launch_instance.log` - general + API call logs
- `ERROR_IN_CONFIG.log` - written if `oci_config` or `oci.env` is invalid
- `INSTANCE_CREATED` - written once an instance exists, with its details
- `UNHANDLED_ERROR.log` - written on an unexpected error
- `images_list.json` - list of available images for your chosen shape
  (only if `OCI_IMAGE_ID` isn't set)
- `id_rsa.pub` / `id_rsa_private` - auto-generated SSH keypair, if you
  didn't supply your own

## Environment Variables (`oci.env`)

| Variable | Required | Notes |
|---|---|---|
| `OCI_CONFIG` | Yes | Path to your OCI config file. Relative paths resolve next to this script. |
| `OCT_FREE_AD` | Yes | Free-tier-eligible availability domain suffix(es), comma-separated. |
| `DISPLAY_NAME` | No | Name for the instance. |
| `REQUEST_WAIT_TIME_SECS` | No | Seconds between retry attempts. Default 60. |
| `SSH_AUTHORIZED_KEYS_FILE` | No | Public key path; generated automatically if missing. |
| `OCI_SUBNET_ID` | Conditional | **Required if running locally/on Windows** rather than from an OCI micro instance. |
| `OCI_IMAGE_ID` | No | Specific image OCID; if blank, resolved from `OPERATING_SYSTEM`/`OS_VERSION`. |
| `OCI_COMPUTE_SHAPE` | No | `VM.Standard.A1.Flex` (ARM) or `VM.Standard.E2.1.Micro` (AMD). Default ARM. |
| `SECOND_MICRO_INSTANCE` | No | `True`/`False` - set True if this is your 2nd free Micro instance. |
| `OPERATING_SYSTEM` / `OS_VERSION` | No | Used to pick an image when `OCI_IMAGE_ID` is blank. |
| `ASSIGN_PUBLIC_IP` | No | `true`/`false`. |
| `BOOT_VOLUME_SIZE` | No | GB, minimum 50. |
| `NOTIFY_EMAIL` / `EMAIL` / `EMAIL_PASSWORD` | No | Gmail notification on success/failure (use a Gmail App Password). |
| `DISCORD_WEBHOOK` | No | Discord webhook URL for both `main.py` and `setup_init.py` notifications. |
| `TELEGRAM_TOKEN` / `TELEGRAM_USER_ID` | No | Telegram bot notifications from `setup_init.py` (status of the wrapper script). |

## Troubleshooting

- **`python` not recognized** - Python isn't on PATH. Reinstall from
  python.org and tick "Add to PATH," or use `py` instead of `python`.
- **`ERROR_IN_CONFIG.log` appears** - check `oci_config` for typos/extra
  spaces, and confirm `key_file` points to a file that actually exists.
- **`InvalidConfig: fingerprint malformed`** or similar from the OCI SDK -
  double check you copied the fingerprint/keys exactly as shown in the OCI
  Console when you created the API key.
- **Running on your own PC and it can't find a subnet** - set
  `OCI_SUBNET_ID` in `oci.env` (see above).

## Credits

Original project and OCI automation logic by
[mohankumarpaluru](https://github.com/mohankumarpaluru/oracle-freetier-instance-creation),
based in turn on work by
[xitroff](https://github.com/hitrov/oci-arm-host-capacity).
This edition just swaps the Linux/Bash/venv-based tooling for pure Python
so it runs directly on Windows.
