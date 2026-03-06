"""
provision_ec2.py
────────────────
Fully automated provisioning script for the Healthcare Appointment System.

What this script does:
  1. Creates an AWS Security Group (SSH:22, HTTP:80, API:5000)
  2. Launches a t3.micro EC2 instance (Amazon Linux 2023, eu-north-1)
  3. Waits until the instance is running and has a public IP
  4. Sets GitHub Actions secrets (EC2_PUBLIC_IP + EC2_SSH_KEY) via gh CLI
  5. SSHs into the instance and:
       - Updates the system
       - Installs Python 3, pip, git
       - Clones the GitHub repository
       - Creates the .env production file
       - Installs Python dependencies
       - Creates the DynamoDB table + SQS queue + seeds slots
       - Installs and starts the systemd service

Usage (run once from your local machine):
  pip install boto3 paramiko
  python provision_ec2.py

AWS credentials are read from environment variables or a local .env file.
Never hardcode credentials in this file.
"""

import base64
import json
import os
import subprocess
import sys
import time

import boto3
import paramiko
from botocore.exceptions import ClientError

# ──────────────────────────────────────────────────────────────────────────────
# Load credentials from environment (set these before running, or use .env)
# ──────────────────────────────────────────────────────────────────────────────
def _load_env_file():
    """Load key=value pairs from .env into os.environ (if not already set)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_env_file()

AWS_REGION            = os.environ.get("AWS_REGION", "eu-north-1")
AWS_ACCESS_KEY_ID     = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

AMI_ID              = "ami-056335ec4a8783947"
INSTANCE_TYPE       = "t3.micro"
KEY_PAIR_NAME       = "cloud-key-pair"
PEM_FILE            = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud-key-pair.pem")
SECURITY_GROUP_NAME = "healthcare-backend-sg"
INSTANCE_NAME       = "Healthcare-Backend"

GITHUB_REPO         = "Hunter00315/api-project"
GITHUB_BRANCH       = "main"
REPO_URL            = f"https://github.com/{GITHUB_REPO}.git"
REMOTE_DIR          = "/home/ec2-user/api-project"

DYNAMODB_TABLE      = "HealthcareSlots"
SQS_QUEUE_NAME      = "healthcare-reservations"
API_KEY_VALUE       = "healthcare-api-key-2024"
WAQI_TOKEN          = "demo"
HEALTH_API_URL      = "https://slc5duy34c.execute-api.us-east-1.amazonaws.com/Prod/calculate"


# ──────────────────────────────────────────────────────────────────────────────
# AWS clients
# ──────────────────────────────────────────────────────────────────────────────
def get_ec2_client():
    return boto3.client(
        "ec2",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )

def get_sqs_client():
    return boto3.client(
        "sqs",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — Security Group
# ──────────────────────────────────────────────────────────────────────────────
def create_security_group(ec2):
    print("\n[1/6] Setting up Security Group ...")

    # Check if it already exists
    try:
        resp = ec2.describe_security_groups(GroupNames=[SECURITY_GROUP_NAME])
        sg_id = resp["SecurityGroups"][0]["GroupId"]
        print(f"      ✓ Security group already exists: {sg_id}")
        return sg_id
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "InvalidGroup.NotFound":
            raise

    # Create it
    resp = ec2.create_security_group(
        GroupName=SECURITY_GROUP_NAME,
        Description="Healthcare API - allows SSH, HTTP, and port 5000",
    )
    sg_id = resp["GroupId"]
    print(f"      + Created security group: {sg_id}")

    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp", "FromPort": 22,   "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
            },
            {
                "IpProtocol": "tcp", "FromPort": 80,   "ToPort": 80,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTP"}],
            },
            {
                "IpProtocol": "tcp", "FromPort": 5000, "ToPort": 5000,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Flask API"}],
            },
        ],
    )
    print(f"      ✓ Inbound rules added (22, 80, 5000)")
    return sg_id


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — Launch EC2 Instance
# ──────────────────────────────────────────────────────────────────────────────
def launch_instance(ec2, sg_id):
    print("\n[2/6] Launching EC2 Instance ...")

    # Check if a named instance is already running
    existing = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name",          "Values": [INSTANCE_NAME]},
            {"Name": "instance-state-name", "Values": ["running", "pending", "stopped"]},
        ]
    )
    reservations = existing.get("Reservations", [])
    if reservations:
        instance = reservations[0]["Instances"][0]
        instance_id = instance["InstanceId"]
        state = instance["State"]["Name"]
        print(f"      ✓ Instance already exists: {instance_id} ({state})")

        if state == "stopped":
            print("      → Starting stopped instance ...")
            ec2.start_instances(InstanceIds=[instance_id])
        return instance_id

    resp = ec2.run_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_PAIR_NAME,
        SecurityGroups=[SECURITY_GROUP_NAME],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": INSTANCE_NAME}],
            }
        ],
    )
    instance_id = resp["Instances"][0]["InstanceId"]
    print(f"      + Launched instance: {instance_id}")
    return instance_id


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 — Wait for instance running + public IP
# ──────────────────────────────────────────────────────────────────────────────
def wait_for_instance(ec2, instance_id):
    print(f"\n[3/6] Waiting for instance {instance_id} to be running ...")
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])

    # Fetch public IP
    for attempt in range(12):
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        instance = resp["Reservations"][0]["Instances"][0]
        public_ip = instance.get("PublicIpAddress")
        if public_ip:
            print(f"      ✓ Instance running. Public IP: {public_ip}")
            return public_ip
        print(f"      … waiting for public IP (attempt {attempt + 1}/12)")
        time.sleep(10)

    raise RuntimeError("Instance has no public IP after waiting. Check the AWS console.")


# ──────────────────────────────────────────────────────────────────────────────
# Step 4 — Set GitHub Actions secrets
# ──────────────────────────────────────────────────────────────────────────────
def find_gh():
    """Locate gh.exe on Windows, trying common install paths."""
    import shutil
    # 1. Already on PATH
    found = shutil.which("gh")
    if found:
        return found
    # 2. Common winget / MSI install locations
    candidates = [
        r"C:\Program Files\GitHub CLI\gh.exe",
        r"C:\Program Files (x86)\GitHub CLI\gh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\GitHub CLI\gh.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # 3. Search PATH entries explicitly
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, "gh.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def set_github_secrets(public_ip):
    print(f"\n[4/6] Setting GitHub Actions secrets ...")

    gh = find_gh()
    if not gh:
        print("      ! gh CLI not found — skipping secret setup.")
        print(f"        Set these manually in GitHub → Settings → Secrets → Actions:")
        print(f"          EC2_PUBLIC_IP = {public_ip}")
        print(f"          EC2_SSH_KEY   = (contents of cloud-key-pair.pem)")
        return

    pem_content = open(PEM_FILE, "r").read()

    for name, value in [("EC2_PUBLIC_IP", public_ip), ("EC2_SSH_KEY", pem_content)]:
        result = subprocess.run(
            [gh, "secret", "set", name, "--repo", GITHUB_REPO, "--body", value],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"      ✓ Secret set: {name}")
        else:
            print(f"      ✗ Failed to set {name}: {result.stderr.strip()}")


# ──────────────────────────────────────────────────────────────────────────────
# Step 5 — SSH setup helpers
# ──────────────────────────────────────────────────────────────────────────────
def ssh_run(ssh, cmd, description=""):
    if description:
        print(f"      → {description}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if exit_status != 0 and err:
        print(f"        ! {err[:200]}")
    return out, exit_status


def wait_for_ssh(public_ip, retries=20, delay=15):
    print(f"\n[5/6] Waiting for SSH to become available on {public_ip} ...")
    pkey = paramiko.RSAKey.from_private_key_file(PEM_FILE)
    for attempt in range(retries):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(public_ip, username="ec2-user", pkey=pkey, timeout=10)
            print(f"      ✓ SSH connection established")
            return ssh
        except Exception as exc:
            print(f"      … attempt {attempt + 1}/{retries}: {exc}")
            time.sleep(delay)
    raise RuntimeError("Could not connect via SSH after multiple attempts.")


# ──────────────────────────────────────────────────────────────────────────────
# Step 6 — Configure EC2 instance
# ──────────────────────────────────────────────────────────────────────────────
def configure_instance(ssh, public_ip):
    print(f"\n[6/6] Configuring EC2 instance ...")

    account_id = boto3.client(
        "sts",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    ).get_caller_identity()["Account"]

    sqs_queue_url = (
        f"https://sqs.{AWS_REGION}.amazonaws.com/{account_id}/{SQS_QUEUE_NAME}"
    )

    env_content = (
        f"AWS_ACCESS_KEY_ID={AWS_ACCESS_KEY_ID}\n"
        f"AWS_SECRET_ACCESS_KEY={AWS_SECRET_ACCESS_KEY}\n"
        f"AWS_REGION={AWS_REGION}\n"
        f"USE_DYNAMODB=true\n"
        f"DYNAMODB_TABLE={DYNAMODB_TABLE}\n"
        f"SQS_QUEUE_URL={sqs_queue_url}\n"
        f"API_KEY={API_KEY_VALUE}\n"
        f"WAQI_TOKEN={WAQI_TOKEN}\n"
        f"HEALTH_API_URL={HEALTH_API_URL}\n"
        f"PORT=5000\n"
        f"FLASK_ENV=production\n"
    )

    commands = [
        ("sudo dnf update -y",
         "Updating system packages"),

        ("sudo dnf install -y python3 python3-pip git",
         "Installing Python 3, pip, git"),

        ("pip3 install --user flask boto3 requests gunicorn paramiko",
         "Installing Python dependencies"),

        (f"[ -d {REMOTE_DIR} ] && git -C {REMOTE_DIR} pull origin {GITHUB_BRANCH} "
         f"|| git clone {REPO_URL} {REMOTE_DIR}",
         "Cloning / updating repository"),

        (f"cat > {REMOTE_DIR}/.env << 'ENVEOF'\n{env_content}ENVEOF",
         "Writing .env file"),

        (f"cd {REMOTE_DIR} && python3 setup_dynamodb.py",
         "Creating DynamoDB table + SQS queue + seeding slots"),

        ("sudo mkdir -p /var/log/healthcare-api && sudo chown ec2-user /var/log/healthcare-api",
         "Creating log directory"),

        (f"sudo cp {REMOTE_DIR}/healthcare-api.service /etc/systemd/system/healthcare-api.service",
         "Installing systemd service file"),

        ("sudo systemctl daemon-reload",
         "Reloading systemd"),

        ("sudo systemctl enable healthcare-api",
         "Enabling service on boot"),

        ("sudo systemctl restart healthcare-api",
         "Starting healthcare-api service"),

        ("sudo systemctl --no-pager status healthcare-api",
         "Checking service status"),
    ]

    for cmd, desc in commands:
        out, exit_status = ssh_run(ssh, cmd, desc)
        if out and "status" in desc.lower():
            # Print service status output
            print(f"\n{out}\n")

    # Quick liveness check
    time.sleep(3)
    out, _ = ssh_run(ssh, "curl -s http://localhost:5000/health", "Verifying API is live")
    if out:
        print(f"\n      API response: {out}")
    else:
        print("      ! API did not respond on port 5000 — check logs: sudo journalctl -u healthcare-api -n 50")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("  Healthcare Appointment System — EC2 Provisioner")
    print("=" * 62)

    if not os.path.exists(PEM_FILE):
        print(f"\n✗ PEM file not found: {PEM_FILE}")
        print("  Place cloud-key-pair.pem in the project root and retry.")
        sys.exit(1)

    ec2 = get_ec2_client()

    sg_id       = create_security_group(ec2)
    instance_id = launch_instance(ec2, sg_id)
    public_ip   = wait_for_instance(ec2, instance_id)

    set_github_secrets(public_ip)

    ssh = wait_for_ssh(public_ip)
    try:
        configure_instance(ssh, public_ip)
    finally:
        ssh.close()

    print("\n" + "=" * 62)
    print("  ✓ Provisioning complete!")
    print(f"  API URL   : http://{public_ip}:5000")
    print(f"  Health    : http://{public_ip}:5000/health")
    print(f"  Slots     : http://{public_ip}:5000/slots")
    print(f"  GitHub    : https://github.com/{GITHUB_REPO}")
    print("=" * 62)
    print("\n  Every push to 'main' will now automatically deploy to EC2.")
    print(f"  Test with: curl http://{public_ip}:5000/health")
    print()


if __name__ == "__main__":
    main()
