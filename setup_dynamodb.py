"""
setup_dynamodb.py
─────────────────
One-time setup script: creates the DynamoDB table and SQS queue,
then seeds the initial appointment slots from slots.json.

Run once on the EC2 instance after cloning the repository:
  python3 setup_dynamodb.py
"""
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError


def _load_env_file():
    """Load .env key=value pairs into os.environ before boto3 is used."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())


_load_env_file()

REGION     = os.environ.get('AWS_REGION',      'eu-north-1')
TABLE_NAME = os.environ.get('DYNAMODB_TABLE',  'HealthcareSlots')
QUEUE_NAME = os.environ.get('SQS_QUEUE_NAME',  'healthcare-reservations')
SLOTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slots.json')


def create_table(dynamodb):
    """Create the DynamoDB table if it does not already exist."""
    try:
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {'AttributeName': 'doctor', 'KeyType': 'HASH'},
                {'AttributeName': 'time',   'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'doctor', 'AttributeType': 'S'},
                {'AttributeName': 'time',   'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        print(f"Creating table '{TABLE_NAME}' — waiting for it to become active …")
        table.wait_until_exists()
        print(f"✓ Table '{TABLE_NAME}' is active.")
    except ClientError as exc:
        if exc.response['Error']['Code'] == 'ResourceInUseException':
            print(f"✓ Table '{TABLE_NAME}' already exists — skipping creation.")
            table = dynamodb.Table(TABLE_NAME)
        else:
            print(f"✗ Failed to create table: {exc}", file=sys.stderr)
            sys.exit(1)
    return table


def seed_slots(table):
    """Seed the table with initial slot data from slots.json."""
    if not os.path.exists(SLOTS_FILE):
        print(f"✗ {SLOTS_FILE} not found — skipping seed.", file=sys.stderr)
        return

    with open(SLOTS_FILE, 'r') as fh:
        data = json.load(fh)

    slots = data.get('slots', [])
    with table.batch_writer() as batch:
        for slot in slots:
            batch.put_item(Item={
                'doctor':    slot['doctor'],
                'time':      slot['time'],
                'available': slot.get('available', True),
            })
    print(f"✓ Seeded {len(slots)} slots into '{TABLE_NAME}'.")


def create_sqs_queue(sqs_client):
    """Create the SQS queue used for async reservation event processing."""
    try:
        response = sqs_client.create_queue(
            QueueName=QUEUE_NAME,
            Attributes={
                'MessageRetentionPeriod': '86400',  # 1 day
                'VisibilityTimeout':      '30',
            },
        )
        queue_url = response['QueueUrl']
        print(f"✓ SQS queue ready: {queue_url}")
        print(f"\n  → Add this to your .env file:")
        print(f"    SQS_QUEUE_URL={queue_url}\n")
        return queue_url
    except ClientError as exc:
        print(f"✗ Failed to create SQS queue: {exc}", file=sys.stderr)
        return None


if __name__ == '__main__':
    dynamodb   = boto3.resource('dynamodb',  region_name=REGION)
    sqs_client = boto3.client('sqs',         region_name=REGION)

    table = create_table(dynamodb)
    seed_slots(table)
    create_sqs_queue(sqs_client)

    print("\nSetup complete. You can now start the application.")
