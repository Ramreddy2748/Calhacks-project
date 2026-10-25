"""Explicit public registration command; never runs as part of app startup."""
import os

from uagents_core.utils.registration import RegistrationRequestCredentials, register_chat_agent

from .public_agent import settings


def register():
    seed, endpoint = settings()
    key = os.getenv('AGENTVERSE_API_KEY', '')
    if not key:
        raise ValueError('Set AGENTVERSE_API_KEY before registering')
    return register_chat_agent(name='HoldOn Public Planner', endpoint=endpoint, active=True,
        credentials=RegistrationRequestCredentials(agent_seed_phrase=seed, agentverse_api_key=key),
        description='Build a safe plan for a tedious phone call. Planning only; calls and approvals stay private.',
        readme='# HoldOn Public Planner\nReturns a suggested plan with AI disclosure and approval steps. '
               'Does not place calls, expose private transcripts, access accounts, or authorize commitments.',
        metadata={'is_public': 'True', 'categories': ['productivity']})


if __name__ == '__main__':
    try:
        success = register()
    except Exception:
        raise SystemExit('Agentverse registration failed. Check credentials, seed, public endpoint, and account setup.')
    if not success:
        raise SystemExit('Agentverse did not confirm registration')
    print('Agentverse confirmed registration of HoldOn Public Planner.')
