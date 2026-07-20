"""
main.py - Oracle Free Tier Instance Creation

Pure-Python, cross-platform (Windows / macOS / Linux) version.
Repeatedly tries to launch an Oracle Cloud "Always Free" compute instance
(ARM A1.Flex or E2.1.Micro) until it succeeds, then optionally notifies you
by email and/or Discord.

Run directly with the system Python interpreter - no virtual environment
required:

    python main.py

Configuration comes from oci.env (see setup_env.py to generate one
interactively) and from the OCI config file referenced by OCI_CONFIG
inside oci.env.
"""

import configparser
import itertools
import json
import logging
import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Union

import oci
import paramiko
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths - resolved relative to THIS FILE, not the current working directory.
# This means the script behaves the same whether you double-click it,
# run it from PowerShell in the project folder, or launch it from a
# scheduled task on Windows.
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "oci.env"

# Load environment variables from oci.env
load_dotenv(ENV_FILE)

ARM_SHAPE = "VM.Standard.A1.Flex"
E2_MICRO_SHAPE = "VM.Standard.E2.1.Micro"


def resolve_path(value: str, default_name: str) -> str:
    """Resolve a path from oci.env.

    - If the env var is blank, fall back to a file of `default_name`
      sitting next to this script.
    - If the env var holds a relative path, resolve it relative to this
      script's directory (so it doesn't matter what folder you launched
      the script from).
    - If it's already absolute (e.g. "C:/Users/you/oci_config" or
      "/home/ubuntu/oci_config"), leave it alone.
    """
    value = (value or "").strip()
    if not value:
        return str(BASE_DIR / default_name)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


# Access loaded environment variables and strip white spaces
OCI_CONFIG = resolve_path(os.getenv("OCI_CONFIG", ""), "oci_config")
OCT_FREE_AD = os.getenv("OCT_FREE_AD", "").strip()
DISPLAY_NAME = os.getenv("DISPLAY_NAME", "").strip()
WAIT_TIME = int(os.getenv("REQUEST_WAIT_TIME_SECS", "60").strip() or "60")
SSH_AUTHORIZED_KEYS_FILE = resolve_path(os.getenv("SSH_AUTHORIZED_KEYS_FILE", ""), "id_rsa.pub")
OCI_IMAGE_ID = os.getenv("OCI_IMAGE_ID", "").strip() or None
OCI_COMPUTE_SHAPE = os.getenv("OCI_COMPUTE_SHAPE", ARM_SHAPE).strip()
SECOND_MICRO_INSTANCE = os.getenv("SECOND_MICRO_INSTANCE", "False").strip().lower() == "true"
OCI_SUBNET_ID = os.getenv("OCI_SUBNET_ID", "").strip() or None
OPERATING_SYSTEM = os.getenv("OPERATING_SYSTEM", "").strip()
OS_VERSION = os.getenv("OS_VERSION", "").strip()
ASSIGN_PUBLIC_IP = os.getenv("ASSIGN_PUBLIC_IP", "false").strip()
BOOT_VOLUME_SIZE = os.getenv("BOOT_VOLUME_SIZE", "50").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "False").strip().lower() == "true"
EMAIL = os.getenv("EMAIL", "").strip()
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "").strip()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()

# ---------------------------------------------------------------------------
# Validate the oci_config file and the oci.env values before doing anything
# expensive. Mirrors the original bash-driven workflow: a bad config drops
# an ERROR_IN_CONFIG.log file that setup_init.py checks for.
# ---------------------------------------------------------------------------
env_config_parser = configparser.ConfigParser()
try:
    if not Path(OCI_CONFIG).is_file():
        raise configparser.Error(f"oci_config file not found at: {OCI_CONFIG}")

    env_config_parser.read(OCI_CONFIG)
    OCI_USER_ID = env_config_parser.get("DEFAULT", "user")

    if OCI_COMPUTE_SHAPE not in (ARM_SHAPE, E2_MICRO_SHAPE):
        raise ValueError(f"{OCI_COMPUTE_SHAPE} is not an acceptable shape")

    
except (configparser.Error, ValueError) as e:
    with open(BASE_DIR / "ERROR_IN_CONFIG.log", "w", encoding="utf-8") as file:
        file.write(str(e))
    print(f"Error reading the configuration file: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename=str(BASE_DIR / "setup_and_info.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging_step5 = logging.getLogger("launch_instance")
logging_step5.setLevel(logging.INFO)
fh = logging.FileHandler(str(BASE_DIR / "launch_instance.log"))
fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logging_step5.addHandler(fh)

# ---------------------------------------------------------------------------
# OCI SDK clients
# ---------------------------------------------------------------------------
oci_config = oci.config.from_file(OCI_CONFIG)
iam_client = oci.identity.IdentityClient(oci_config)
network_client = oci.core.VirtualNetworkClient(oci_config)
compute_client = oci.core.ComputeClient(oci_config)

IMAGE_LIST_KEYS = [
    "lifecycle_state",
    "display_name",
    "id",
    "operating_system",
    "operating_system_version",
    "size_in_mbs",
    "time_created",
]


def write_into_file(file_path, data):
    """Append data into a file located next to this script."""
    full_path = BASE_DIR / file_path
    with open(full_path, mode="a", encoding="utf-8") as file_writer:
        file_writer.write(data)


def send_email(subject, body, email, password):
    """Send an HTML email using the SMTP protocol (Gmail)."""
    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = email
    message["To"] = email

    html_body = MIMEText(body, "html")
    message.attach(html_body)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        try:
            server.starttls()
            server.login(email, password)
            server.sendmail(email, email, message.as_string())
        except smtplib.SMTPException as mail_err:
            logging.error("Error while sending email: %s", mail_err)
            raise


def list_all_instances(compartment_id):
    """Retrieve a list of all instances in the specified compartment."""
    list_instances_response = compute_client.list_instances(compartment_id=compartment_id)
    return list_instances_response.data


def generate_html_body(instance):
    """Generate HTML body for the email with instance details."""
    template_path = BASE_DIR / "email_content.html"
    with open(template_path, "r", encoding="utf-8") as email_temp:
        html_template = email_temp.read()
    html_body = html_template.replace("<INSTANCE_ID>", instance.id)
    html_body = html_body.replace("<DISPLAY_NAME>", instance.display_name)
    html_body = html_body.replace("<AD>", instance.availability_domain)
    html_body = html_body.replace("<SHAPE>", instance.shape)
    html_body = html_body.replace("<STATE>", instance.lifecycle_state)
    return html_body


def create_instance_details_file_and_notify(instance, shape=ARM_SHAPE):
    """Create a file with details of the instance and notify the user."""
    details = [
        f"Instance ID: {instance.id}",
        f"Display Name: {instance.display_name}",
        f"Availability Domain: {instance.availability_domain}",
        f"Shape: {instance.shape}",
        f"State: {instance.lifecycle_state}",
        "\n",
    ]
    micro_body = "Two Micro Instances are already existing and running"
    arm_body = "\n".join(details)
    body = arm_body if shape == ARM_SHAPE else micro_body
    write_into_file("INSTANCE_CREATED", body)

    html_body = generate_html_body(instance)

    if NOTIFY_EMAIL:
        send_email("OCI INSTANCE CREATED", html_body, EMAIL, EMAIL_PASSWORD)


def notify_on_failure(failure_msg):
    """Notify the user when instance creation fails with an unhandled error."""
    mail_body = (
        "The script encountered an unhandled error and exited unexpectedly.\n\n"
        "Please re-run the script by executing 'python setup_init.py rerun'.\n\n"
        "And raise an issue on GitHub if it's not already existing:\n"
        "https://github.com/mohankumarpaluru/oracle-freetier-instance-creation/issues\n\n"
        "And include the following error message to help investigate and resolve the problem:\n\n"
        f"{failure_msg}"
    )
    write_into_file("UNHANDLED_ERROR.log", mail_body)

    if NOTIFY_EMAIL:
        send_email("OCI INSTANCE CREATION SCRIPT: FAILED DUE TO AN ERROR", mail_body, EMAIL, EMAIL_PASSWORD)


def check_instance_state_and_write(compartment_id, shape, states=("RUNNING", "PROVISIONING"), tries=3):
    """Check the state of instances in the compartment and act if found."""
    for _ in range(tries):
        instance_list = list_all_instances(compartment_id=compartment_id)
        if shape == ARM_SHAPE:
            running_arm_instance = next(
                (
                    instance
                    for instance in instance_list
                    if instance.shape == shape and instance.lifecycle_state in states
                ),
                None,
            )
            if running_arm_instance:
                create_instance_details_file_and_notify(running_arm_instance, shape)
                return True
        else:
            micro_instance_list = [
                instance
                for instance in instance_list
                if instance.shape == shape and instance.lifecycle_state in states
            ]
            if len(micro_instance_list) > 1 and SECOND_MICRO_INSTANCE:
                create_instance_details_file_and_notify(micro_instance_list[-1], shape)
                return True
            if len(micro_instance_list) == 1 and not SECOND_MICRO_INSTANCE:
                create_instance_details_file_and_notify(micro_instance_list[-1], shape)
                return True

        if tries - 1 > 0:
            time.sleep(60)
    return False


def handle_errors(command, data, log):
    """Handle errors from OCI API calls; retry on known-transient errors."""
    if "code" in data:
        if (data["code"] in ("TooManyRequests", "Out of host capacity.", "InternalError")) or (
            data.get("message") in ("Out of host capacity.", "Bad Gateway")
        ):
            log.info("Command: %s--\nOutput: %s", command, data)
            time.sleep(WAIT_TIME)
            return True

    if data.get("status") == 502:
        log.info("Command: %s~~\nOutput: %s", command, data)
        time.sleep(WAIT_TIME)
        return True

    failure_msg = "\n".join([f"{key}: {value}" for key, value in data.items()])
    notify_on_failure(failure_msg)
    raise Exception(f"Error: {data}")


def execute_oci_command(client, method, *args, **kwargs):
    """Execute an OCI SDK call, retrying on transient errors."""
    while True:
        try:
            response = getattr(client, method)(*args, **kwargs)
            return response.data if hasattr(response, "data") else response
        except oci.exceptions.ServiceError as srv_err:
            data = {"status": srv_err.status, "code": srv_err.code, "message": srv_err.message}
            handle_errors(args, data, logging_step5)


def generate_ssh_key_pair(public_key_file: Union[str, Path], private_key_file: Union[str, Path]):
    """Generate an SSH key pair and save them to the specified files."""
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(str(private_key_file))
    write_into_file(
        public_key_file,
        f"ssh-rsa {key.get_base64()} {Path(public_key_file).stem}_auto_generated",
    )


def read_or_generate_ssh_public_key(public_key_file: Union[str, Path]):
    """Read the SSH public key from file, generating a key pair if needed."""
    public_key_path = Path(public_key_file)
    if not public_key_path.is_file():
        logging.info("SSH key doesn't exist... Generating SSH Key Pair")
        public_key_path.parent.mkdir(parents=True, exist_ok=True)
        private_key_path = public_key_path.with_name(f"{public_key_path.stem}_private")
        generate_ssh_key_pair(public_key_path, private_key_path)

    with open(public_key_path, "r", encoding="utf-8") as pub_key_file:
        return pub_key_file.read()


def send_discord_message(message):
    """Send a message to Discord using the configured webhook URL."""
    if DISCORD_WEBHOOK:
        try:
            response = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error("Failed to send Discord message: %s", e)


def launch_instance():
    """Launch an OCI Compute instance, retrying until it succeeds."""
    # Step 1 - Get TENANCY
    user_info = execute_oci_command(iam_client, "get_user", OCI_USER_ID)
    oci_tenancy = user_info.compartment_id
    logging.info("OCI_TENANCY: %s", oci_tenancy)

    # Step 2 - Get AD Name(s)
    availability_domains = execute_oci_command(
        iam_client, "list_availability_domains", compartment_id=oci_tenancy
    )
    oci_ad_name = [
        item.name
        for item in availability_domains
        if any(item.name.endswith(oct_ad) for oct_ad in OCT_FREE_AD.split(","))
    ]
    if not oci_ad_name:
        raise ValueError(
            f"No availability domain matched OCT_FREE_AD='{OCT_FREE_AD}'. "
            "Check the value in oci.env."
        )
    oci_ad_names = itertools.cycle(oci_ad_name)
    logging.info("OCI_AD_NAME: %s", oci_ad_name)

    # Step 3 - Get Subnet ID
    oci_subnet_id = OCI_SUBNET_ID
    if not oci_subnet_id:
        subnets = execute_oci_command(network_client, "list_subnets", compartment_id=oci_tenancy)
        oci_subnet_id = subnets[0].id
    logging.info("OCI_SUBNET_ID: %s", oci_subnet_id)

    # Step 4 - Get Image ID
    if not OCI_IMAGE_ID:
        images = execute_oci_command(
            compute_client, "list_images", compartment_id=oci_tenancy, shape=OCI_COMPUTE_SHAPE
        )
        shortened_images = [
            {key: json.loads(str(image))[key] for key in IMAGE_LIST_KEYS} for image in images
        ]
        write_into_file("images_list.json", json.dumps(shortened_images, indent=2))
        oci_image_id = next(
            image.id
            for image in images
            if image.operating_system == OPERATING_SYSTEM and image.operating_system_version == OS_VERSION
        )
        logging.info("OCI_IMAGE_ID: %s", oci_image_id)
    else:
        oci_image_id = OCI_IMAGE_ID

    assign_public_ip = ASSIGN_PUBLIC_IP.lower() in ("true", "1", "y", "yes")
    boot_volume_size = max(50, int(BOOT_VOLUME_SIZE))
    ssh_public_key = read_or_generate_ssh_public_key(SSH_AUTHORIZED_KEYS_FILE)

    # Step 5 - Launch instance if it doesn't already exist
    instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE, tries=1)

    if OCI_COMPUTE_SHAPE == ARM_SHAPE:
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=4, memory_in_gbs=24)
    else:
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1, memory_in_gbs=1)

    while not instance_exist_flag:
        try:
            launch_instance_response = compute_client.launch_instance(
                launch_instance_details=oci.core.models.LaunchInstanceDetails(
                    availability_domain=next(oci_ad_names),
                    compartment_id=oci_tenancy,
                    create_vnic_details=oci.core.models.CreateVnicDetails(
                        assign_public_ip=assign_public_ip,
                        assign_private_dns_record=True,
                        display_name=DISPLAY_NAME,
                        subnet_id=oci_subnet_id,
                    ),
                    display_name=DISPLAY_NAME,
                    shape=OCI_COMPUTE_SHAPE,
                    availability_config=oci.core.models.LaunchInstanceAvailabilityConfigDetails(
                        recovery_action="RESTORE_INSTANCE"
                    ),
                    instance_options=oci.core.models.InstanceOptions(
                        are_legacy_imds_endpoints_disabled=False
                    ),
                    shape_config=shape_config,
                    source_details=oci.core.models.InstanceSourceViaImageDetails(
                        source_type="image",
                        image_id=oci_image_id,
                        boot_volume_size_in_gbs=boot_volume_size,
                    ),
                    metadata={"ssh_authorized_keys": ssh_public_key},
                )
            )

            if launch_instance_response.status == 200:
                logging_step5.info("Command: launch_instance\nOutput: %s", launch_instance_response.data)
                instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE)

        except oci.exceptions.ServiceError as srv_err:
            if srv_err.code == "LimitExceeded":
                logging_step5.info(
                    "Encountered LimitExceeded error, checking if instance was created. "
                    "code: %s, message: %s, status: %s",
                    srv_err.code,
                    srv_err.message,
                    srv_err.status,
                )
                instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE)
                if instance_exist_flag:
                    logging_step5.info("%s , exiting the program", srv_err.code)
                    sys.exit()
                logging_step5.info("Didn't find an instance, proceeding with retries")

            data = {"status": srv_err.status, "code": srv_err.code, "message": srv_err.message}
            handle_errors("launch_instance", data, logging_step5)


if __name__ == "__main__":
    send_discord_message("\U0001F680 OCI Instance Creation Script: Starting up! Let's create some cloud magic!")
    try:
        launch_instance()
        send_discord_message("\U0001F389 Success! OCI Instance has been created. Time to celebrate!")
    except Exception as e:
        error_message = f"\U0001F631 Oops! Something went wrong with the OCI Instance Creation Script:\n{str(e)}"
        send_discord_message(error_message)
        raise
