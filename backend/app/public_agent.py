"""Separate, public ACP planner. Never imports the private API or task store."""
import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
import uagents.agent as sdk_agent
from uagents.registration import AlmanacApiRegistrationPolicy
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, TextContent, EndSessionContent, chat_protocol_spec,
)

from .agents import Agents

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


def settings():
    seed = os.getenv('AGENTVERSE_SEED', '')
    endpoint = os.getenv('AGENTVERSE_ENDPOINT', '')
    parsed = urlparse(endpoint)
    if len(seed) < 32 or parsed.scheme != 'https' or not parsed.netloc or parsed.path != '/submit' or parsed.query or parsed.fragment:
        raise ValueError('Set a 32+ character AGENTVERSE_SEED and HTTPS AGENTVERSE_ENDPOINT ending in /submit')
    return seed, endpoint


async def public_reply(text):
    goal = text.strip()
    if not 5 <= len(goal) <= 1200:
        return 'Describe a phone-call goal in 5 to 1200 characters. Leave out account secrets.'
    # Deliberately deterministic: unauthenticated public requests do not spend
    # provider credits, create private tasks, dial phones, or authorize actions.
    plan = await Agents().plan({'mode': 'demo', 'goal': goal, 'context': ''})
    return ('HoldOn public planner — a suggested plan only. No call was placed.\n\n'
            + '\n'.join(f'{index + 1}. {step}' for index, step in enumerate(plan))
            + '\n\nUse your private HoldOn workspace to start a session and approve commitments.')


def create_agent(loop):
    seed, endpoint = settings()
    with patch.object(sdk_agent, 'get_almanac_contract', return_value=None):
        agent = Agent(name='HoldOn Public Planner', seed=seed, endpoint=endpoint,
            port=int(os.getenv('AGENTVERSE_PORT', '8001')), loop=loop,
            enable_agent_inspector=False, registration_policy=AlmanacApiRegistrationPolicy())
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def on_message(ctx: Context, sender: str, message: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=message.msg_id))
        text = ''.join(item.text for item in message.content if isinstance(item, TextContent))
        await ctx.send(sender, ChatMessage(content=[TextContent(text=await public_reply(text)), EndSessionContent()]))

    @protocol.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, message: ChatAcknowledgement):
        pass

    agent.include(protocol, publish_manifest=False)
    return agent


if __name__ == '__main__':
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    create_agent(event_loop).run()
