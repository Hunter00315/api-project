import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError


class ReservationService:
    """
    Manages appointment slot reservations.

    Storage backend is selected at construction time:
      - USE_DYNAMODB=true  → AWS DynamoDB + SQS (production, scalable)
      - USE_DYNAMODB=false → local slots.json  (development / testing)

    DynamoDB table schema
    ─────────────────────
      Partition key : doctor  (String)
      Sort key      : time    (String)
    Additional attributes: available (Bool), patient_name, reservation_id, reserved_at
    """

    def __init__(self, slots_file: str = None):
        region = os.environ.get('AWS_REGION', 'eu-north-1')
        self.use_dynamodb = os.environ.get('USE_DYNAMODB', 'true').lower() == 'true'
        self.table_name = os.environ.get('DYNAMODB_TABLE', 'HealthcareSlots')
        self.queue_url = os.environ.get('SQS_QUEUE_URL', '')

        # Resolve the local slots file path
        if slots_file:
            self.slots_file = slots_file
        else:
            self.slots_file = os.environ.get(
                'SLOTS_FILE',
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'slots.json',
                ),
            )

        if self.use_dynamodb:
            self.dynamodb = boto3.resource('dynamodb', region_name=region)
            self.table = self.dynamodb.Table(self.table_name)
            self.sqs = (
                boto3.client('sqs', region_name=region) if self.queue_url else None
            )
        else:
            self.dynamodb = None
            self.table = None
            self.sqs = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_slots(self, doctor: str = None) -> list:
        if self.use_dynamodb:
            return self._get_slots_dynamodb(doctor)
        return self._get_slots_json(doctor)

    def reserve_slot(self, patient_name: str, doctor: str, time: str) -> dict:
        if self.use_dynamodb:
            return self._reserve_slot_dynamodb(patient_name, doctor, time)
        return self._reserve_slot_json(patient_name, doctor, time)

    def cancel_reservation(self, reservation_id: str) -> dict:
        if self.use_dynamodb:
            return self._cancel_reservation_dynamodb(reservation_id)
        return self._cancel_reservation_json(reservation_id)

    def get_reservations(self, doctor: str = None) -> list:
        if self.use_dynamodb:
            return self._get_reservations_dynamodb(doctor)
        return self._get_reservations_json(doctor)

    # ------------------------------------------------------------------
    # DynamoDB implementations
    # ------------------------------------------------------------------

    def _get_slots_dynamodb(self, doctor: str = None) -> list:
        try:
            if doctor:
                response = self.table.query(
                    KeyConditionExpression=Key('doctor').eq(doctor)
                )
            else:
                response = self.table.scan()
            return [self._clean_item(i) for i in response.get('Items', [])]
        except ClientError:
            return self._get_slots_json(doctor)

    def _reserve_slot_dynamodb(self, patient_name: str, doctor: str, time: str) -> dict:
        reservation_id = str(uuid.uuid4())
        try:
            self.table.update_item(
                Key={'doctor': doctor, 'time': time},
                UpdateExpression=(
                    'SET available = :avail, patient_name = :name, '
                    'reservation_id = :rid, reserved_at = :ts'
                ),
                # Atomic: slot must exist AND still be available
                ConditionExpression='attribute_exists(doctor) AND available = :true',
                ExpressionAttributeValues={
                    ':avail': False,
                    ':name': patient_name,
                    ':rid': reservation_id,
                    ':ts': datetime.now(timezone.utc).isoformat(),
                    ':true': True,
                },
            )
            self._send_to_sqs({
                'action': 'reserve',
                'reservation_id': reservation_id,
                'patient_name': patient_name,
                'doctor': doctor,
                'time': time,
            })
            return {'reservation_id': reservation_id}
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
                # Distinguish "not found" from "already booked"
                try:
                    resp = self.table.get_item(Key={'doctor': doctor, 'time': time})
                    if 'Item' not in resp:
                        return {'error': 'slot_not_found'}
                except ClientError:
                    pass
                return {'error': 'slot_unavailable'}
            return {'error': str(exc)}

    def _cancel_reservation_dynamodb(self, reservation_id: str) -> dict:
        try:
            response = self.table.scan(
                FilterExpression=Attr('reservation_id').eq(reservation_id)
            )
            items = response.get('Items', [])
            if not items:
                return {'error': 'not_found'}
            item = items[0]
            self.table.update_item(
                Key={'doctor': item['doctor'], 'time': item['time']},
                UpdateExpression='SET available = :avail REMOVE patient_name, reservation_id, reserved_at',
                ConditionExpression='reservation_id = :rid',
                ExpressionAttributeValues={
                    ':avail': True,
                    ':rid': reservation_id,
                },
            )
            self._send_to_sqs({'action': 'cancel', 'reservation_id': reservation_id})
            return {'success': True}
        except ClientError as exc:
            return {'error': str(exc)}

    def _get_reservations_dynamodb(self, doctor: str = None) -> list:
        try:
            if doctor:
                response = self.table.query(
                    KeyConditionExpression=Key('doctor').eq(doctor),
                    FilterExpression=Attr('available').eq(False),
                )
            else:
                response = self.table.scan(
                    FilterExpression=Attr('available').eq(False)
                )
            return [self._clean_item(i) for i in response.get('Items', [])]
        except ClientError:
            return self._get_reservations_json(doctor)

    # ------------------------------------------------------------------
    # JSON file implementations (development / testing fallback)
    # ------------------------------------------------------------------

    def _load_json(self) -> dict:
        with open(self.slots_file, 'r') as fh:
            return json.load(fh)

    def _save_json(self, data: dict) -> None:
        with open(self.slots_file, 'w') as fh:
            json.dump(data, fh, indent=2)

    def _get_slots_json(self, doctor: str = None) -> list:
        data = self._load_json()
        slots = data.get('slots', [])
        if doctor:
            slots = [s for s in slots if s.get('doctor') == doctor]
        return slots

    def _reserve_slot_json(self, patient_name: str, doctor: str, time: str) -> dict:
        data = self._load_json()
        reservation_id = str(uuid.uuid4())
        for slot in data.get('slots', []):
            if slot.get('doctor') == doctor and slot.get('time') == time:
                if not slot.get('available', True):
                    return {'error': 'slot_unavailable'}
                slot['available'] = False
                slot['patient_name'] = patient_name
                slot['reservation_id'] = reservation_id
                slot['reserved_at'] = datetime.now(timezone.utc).isoformat()
                self._save_json(data)
                return {'reservation_id': reservation_id}
        return {'error': 'slot_not_found'}

    def _cancel_reservation_json(self, reservation_id: str) -> dict:
        data = self._load_json()
        for slot in data.get('slots', []):
            if slot.get('reservation_id') == reservation_id:
                slot['available'] = True
                slot.pop('patient_name', None)
                slot.pop('reservation_id', None)
                slot.pop('reserved_at', None)
                self._save_json(data)
                return {'success': True}
        return {'error': 'not_found'}

    def _get_reservations_json(self, doctor: str = None) -> list:
        data = self._load_json()
        reservations = [s for s in data.get('slots', []) if not s.get('available', True)]
        if doctor:
            reservations = [r for r in reservations if r.get('doctor') == doctor]
        return reservations

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_to_sqs(self, message: dict) -> None:
        """Fire-and-forget: publish reservation event to SQS for async processing."""
        if self.sqs and self.queue_url:
            try:
                self.sqs.send_message(
                    QueueUrl=self.queue_url,
                    MessageBody=json.dumps(message),
                )
            except Exception:
                pass  # SQS failure must not break the reservation flow

    @staticmethod
    def _clean_item(item: dict) -> dict:
        """Convert DynamoDB Decimal types to native Python int/float for JSON serialisation."""
        from decimal import Decimal
        cleaned = {}
        for k, v in item.items():
            if isinstance(v, Decimal):
                cleaned[k] = int(v) if v % 1 == 0 else float(v)
            else:
                cleaned[k] = v
        return cleaned
