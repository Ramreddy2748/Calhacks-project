"""Explicit, single-recipient summary delivery. Never called automatically."""
import os
import re

import httpx


class SmsDelivery:
    def __init__(self, client=None):
        self.client = client

    def configured(self):
        return bool(re.fullmatch(r'AC[0-9a-fA-F]{32}', os.getenv('TWILIO_ACCOUNT_SID', ''))
            and os.getenv('TWILIO_AUTH_TOKEN')
            and all(re.fullmatch(r'\+[1-9]\d{7,14}', os.getenv(key, ''))
                    for key in ['TWILIO_SMS_FROM', 'TWILIO_SMS_TO']))

    def info(self):
        number = os.getenv('TWILIO_SMS_TO', '')
        return {'configured': self.configured(), 'recipient': f'•••• {number[-4:]}' if self.configured() else None}

    def body(self, task):
        return f"HoldOn: {task['goal'][:90]}\n{task['summary'][:500]}"[:620]

    async def send(self, task):
        if not self.configured():
            raise ValueError('Twilio SMS is not configured')
        sid = os.environ['TWILIO_ACCOUNT_SID']
        async def post(client):
            return await client.post(f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json',
                auth=(sid, os.environ['TWILIO_AUTH_TOKEN']), data={
                    'From': os.environ['TWILIO_SMS_FROM'], 'To': os.environ['TWILIO_SMS_TO'], 'Body': self.body(task)})
        if self.client:
            response = await post(self.client)
        else:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await post(client)
        response.raise_for_status()
        result = response.json()
        if not re.fullmatch(r'SM[0-9a-fA-F]{32}', result.get('sid', '')):
            raise ValueError('Provider acceptance could not be confirmed')
        return {'id': result['sid'], 'status': result.get('status', 'accepted')}

    async def status(self, message_id):
        if not self.configured() or not re.fullmatch(r'SM[0-9a-fA-F]{32}', message_id):
            raise ValueError('SMS status is unavailable')
        sid = os.environ['TWILIO_ACCOUNT_SID']
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages/{message_id}.json',
                auth=(sid, os.environ['TWILIO_AUTH_TOKEN']))
        response.raise_for_status()
        return response.json().get('status', 'unknown')
