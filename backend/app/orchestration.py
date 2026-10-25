"""Local Fetch.ai uAgents messaging, embedded in FastAPI's event loop.

No agent endpoints, mailbox, ledger registration, or public discovery are enabled.
The SDK is pinned: setup() owns background tasks but offers no scoped teardown,
so we retain exactly the tasks it creates and unregister its local dispatcher sinks.
Never use Agent.run_async()/Bureau.run_async() in the API loop: their teardown
cancels unrelated asyncio tasks as well.
"""
import asyncio
import copy
import logging
import secrets
from unittest.mock import patch
from typing import Literal
from uuid import uuid4

from uagents import Agent, Context, Model
from uagents.dispatch import dispatcher
import uagents.agent as sdk_agent
from .errors import AgentError, error_code


class RoleRequest(Model):
    request_id: str
    task_id: str
    operation: Literal['plan', 'negotiate', 'review', 'authorize', 'report']
    task: dict
    arguments: dict


class RoleResult(Model):
    request_id: str
    task_id: str
    value: dict
    error: bool = False
    error_code: str = ''


ROLES = {'plan': 'Planner', 'negotiate': 'Negotiator', 'review': 'Guardrail',
         'authorize': 'Guardrail', 'report': 'Reporter'}
logger = logging.getLogger('holdon.orchestration')


class FetchOrchestrator:
    def __init__(self, roles, timeout=75):
        self.roles = roles
        self.timeout = timeout
        self.members = {}
        self.pending = {}
        self.background = set()
        self.context = None

    @property
    def configured(self):
        return self.roles.configured

    @property
    def ready(self):
        return self.context is not None and all(not t.done() for t in self.background)

    def info(self):
        return {'framework': 'Fetch.ai uAgents', 'version': '0.23.6', 'ready': self.ready,
                'transport': 'local uAgents dispatcher', 'public_registration': False,
                'agents': {name: agent.address for name, agent in self.members.items()}}

    async def start(self):
        if self.context is not None:
            raise RuntimeError('Orchestrator is already running')
        loop = asyncio.get_running_loop()
        seed = secrets.token_hex(32)  # ephemeral local identities; no wallet files
        try:
            for name in ['Orchestrator', 'Planner', 'Negotiator', 'Guardrail', 'Reporter']:
                # SDK 0.23.6 probes the ledger even with no endpoints. Suppress
                # that constructor-only lookup for this strictly local runtime.
                # This synchronous scope contains no await; restore immediately.
                with patch.object(sdk_agent, 'get_almanac_contract', return_value=None):
                    self.members[name] = Agent(name=f'HoldOn {name}', seed=f'{seed}:{name}',
                        loop=loop, enable_agent_inspector=False, log_level=logging.WARNING)
            gateway = self.members['Orchestrator']
            started = loop.create_future()

            @gateway.on_event('startup')
            async def gateway_ready(ctx: Context):
                if not started.done():
                    started.set_result(ctx)

            @gateway.on_message(model=RoleResult)
            async def receive(ctx: Context, sender: str, result: RoleResult):
                entry = self.pending.get(result.request_id)
                if not entry:
                    return  # cancelled or timed-out request
                future, expected_sender, task_id = entry
                if sender != expected_sender or result.task_id != task_id or future.done():
                    return
                if result.error:
                    future.set_exception(AgentError(result.error_code) if result.error_code else
                                         RuntimeError('uAgent role execution failed'))
                else:
                    future.set_result(result.value)

            for name, agent in self.members.items():
                if name != 'Orchestrator':
                    self._register_role(agent, name, gateway.address)
                before = asyncio.all_tasks()
                agent.setup()
                self.background.update(asyncio.all_tasks() - before)
            self.context = await asyncio.wait_for(started, timeout=5)
            # Startup tasks have completed; retain only long-running SDK tasks.
            await asyncio.sleep(0)
            self.background = {t for t in self.background if not t.done()}
        except BaseException:
            await self.close()
            raise

    def _register_role(self, agent, name, gateway_address):
        @agent.on_message(model=RoleRequest, replies={RoleResult})
        async def handle(ctx: Context, sender: str, request: RoleRequest):
            if sender != gateway_address:
                return
            try:
                if ROLES[request.operation] != name or request.task.get('id') != request.task_id:
                    raise ValueError('Invalid role routing')
                method = getattr(self.roles, request.operation)
                value = await method(request.task, **request.arguments)
                result = RoleResult(request_id=request.request_id, task_id=request.task_id,
                                    value={'result': value})
            except Exception as error:
                logger.exception('uAgent %s failed for task %s', name, request.task_id)
                result = RoleResult(request_id=request.request_id, task_id=request.task_id,
                                    value={}, error=True, error_code=error_code(error))
            await ctx.send(sender, result)

    async def close(self):
        self.context = None
        for future, _, _ in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()
        for task in self.background:
            task.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        self.background.clear()
        for agent in self.members.values():
            dispatcher.unregister(agent.address, agent)
        self.members.clear()

    async def request(self, operation, task, **arguments):
        if not self.ready:
            raise RuntimeError('Fetch.ai orchestrator is unavailable')
        role = ROLES[operation]
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        destination = self.members[role].address
        self.pending[request_id] = (future, destination, task['id'])
        try:
            # Serialize a snapshot: a delayed role must never mutate persisted task state.
            message = RoleRequest(request_id=request_id, task_id=task['id'], operation=operation,
                                  task=copy.deepcopy(task), arguments=arguments)
            async with asyncio.timeout(self.timeout):
                await self.context.send(destination, message)
                value = await future
                return value['result']
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def plan(self, task):
        return await self.request('plan', task)

    async def negotiate(self, task):
        return await self.request('negotiate', task)

    async def review(self, task, description):
        return await self.request('review', task, description=description)

    async def authorize(self, task, approval_id):
        return await self.request('authorize', task, approval_id=approval_id)

    async def report(self, task):
        return await self.request('report', task)
