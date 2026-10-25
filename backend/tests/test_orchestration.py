import asyncio

import pytest
from uagents.dispatch import dispatcher

from app.agents import Agents
from app.orchestration import FetchOrchestrator, RoleResult


def task(task_id='one'):
    return {'id': task_id, 'goal': f'Goal for {task_id}', 'mode': 'demo',
            'status': 'in_progress', 'context': '', 'approval': None}


def test_real_messages_concurrent_tasks_and_scoped_shutdown(monkeypatch):
    # Local orchestration must not register agents, send telemetry, or use HTTP.
    import aiohttp
    import httpx
    import requests
    from uagents.network import AlmanacContract

    ledger_queries = []

    def forbidden_ledger(*args, **kwargs):
        ledger_queries.append(True)
        raise AssertionError('Local runtime attempted a ledger query')

    def forbidden(*args, **kwargs):
        raise AssertionError('Local uAgents orchestration attempted external HTTP')

    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(aiohttp.ClientSession, '_request', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.setattr(AlmanacContract, 'check_version', forbidden_ledger)

    async def scenario():
        baseline = set(dispatcher.sinks)
        runtime = FetchOrchestrator(Agents())
        unrelated = asyncio.create_task(asyncio.sleep(60))
        try:
            await runtime.start()
            assert runtime.ready
            assert len(set(runtime.info()['agents'].values())) == 5
            first, second = await asyncio.gather(runtime.plan(task('one')), runtime.plan(task('two')))
            assert 'Goal for one' in first[1]
            assert 'Goal for two' in second[1]
            proposal = await runtime.negotiate(task())
            approval = await runtime.review(task(), proposal['description'])
            record = {**task(), 'status': 'awaiting_approval', 'approval': approval}
            assert not await runtime.authorize(record, approval['id'])
            approval['status'] = 'approved'
            record['decision'] = 'approved'
            assert not await runtime.authorize(record, 'wrong-id')
            assert await runtime.authorize(record, approval['id'])
            record['status'] = 'cancelled'
            assert not await runtime.authorize(record, approval['id'])
            assert 'HOLD-2048' in await runtime.report(record)
            assert not runtime.pending
        finally:
            await runtime.close()
            assert not unrelated.done()
            unrelated.cancel()
            await asyncio.gather(unrelated, return_exceptions=True)
        assert not runtime.ready
        assert set(dispatcher.sinks) == baseline
        # A second FastAPI lifespan can safely initialize a fresh SDK runtime.
        await runtime.start()
        await runtime.close()
        assert set(dispatcher.sinks) == baseline

    asyncio.run(scenario())
    assert not ledger_queries


def test_timeout_cancellation_late_replies_and_role_errors():
    class ControlledRoles(Agents):
        async def plan(self, data):
            if data['id'] == 'fail':
                raise ValueError('Simulated role failure')
            if data['id'] == 'slow':
                await asyncio.sleep(0.12)
            return [data['id']]

    async def scenario():
        runtime = FetchOrchestrator(ControlledRoles(), timeout=0.04)
        await runtime.start()
        try:
            with pytest.raises(TimeoutError):
                await runtime.plan(task('slow'))
            assert not runtime.pending
            await asyncio.sleep(0.15)
            assert await runtime.plan(task('next')) == ['next']
            request = asyncio.create_task(runtime.plan(task('slow')))
            await asyncio.sleep(0.01)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert not runtime.pending
            await asyncio.sleep(0.15)
            with pytest.raises(RuntimeError, match='role execution failed'):
                await runtime.plan(task('fail'))
            assert await runtime.plan(task('recovered')) == ['recovered']
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_results_from_wrong_sender_or_task_cannot_complete_request():
    class SlowRoles(Agents):
        async def plan(self, data):
            await asyncio.sleep(0.03)
            return ['actual planner result']

    async def scenario():
        runtime = FetchOrchestrator(SlowRoles())
        await runtime.start()
        try:
            pending = asyncio.create_task(runtime.plan(task()))
            await asyncio.sleep(0)
            request_id = next(iter(runtime.pending))
            for sender, task_id in [(runtime.members['Reporter'].address, 'one'),
                                    (runtime.members['Planner'].address, 'another-task')]:
                forged = RoleResult(request_id=request_id, task_id=task_id, value={'result': ['forged']})
                await dispatcher.dispatch_msg(sender, runtime.members['Orchestrator'].address,
                    RoleResult.build_schema_digest(forged), forged.model_dump_json(), runtime.context.session)
            assert await pending == ['actual planner result']
        finally:
            await runtime.close()

    asyncio.run(scenario())
