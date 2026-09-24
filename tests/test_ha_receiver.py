"""Receiver logic with explicit HA doubles, not an HA runtime boot test."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]


def load_receiver():
    modules = {}
    names = ['homeassistant','homeassistant.components','homeassistant.components.recorder',
             'homeassistant.components.recorder.models','homeassistant.components.recorder.statistics',
             'homeassistant.const','homeassistant.core','homeassistant.helpers','homeassistant.helpers.http',
             'homeassistant.helpers.storage','homeassistant.helpers.update_coordinator',
             'homeassistant.util','homeassistant.util.unit_conversion']
    for name in names:
        modules[name] = types.ModuleType(name)
    class View:
        @staticmethod
        def json(data, status_code=200):
            return web.json_response(data, status=status_code)
    modules['homeassistant.helpers.http'].HomeAssistantView = View
    key = web.AppKey('hass')
    modules['homeassistant.helpers.http'].KEY_HASS = key
    modules['homeassistant.components.recorder.models'].StatisticMeanType = types.SimpleNamespace(NONE=0)
    queue = Mock()
    modules['homeassistant.components.recorder.statistics'].async_add_external_statistics = queue
    modules['homeassistant.const'].Platform = types.SimpleNamespace(SENSOR='sensor')
    modules['homeassistant.core'].HomeAssistant = object
    modules['homeassistant.helpers.storage'].Store = Mock()
    modules['homeassistant.helpers.update_coordinator'].DataUpdateCoordinator = Mock()
    modules['homeassistant.util.unit_conversion'].EnergyConverter = types.SimpleNamespace(UNIT_CLASS='energy')
    path = ROOT / 'custom_components/empower_naperville/__init__.py'
    spec = importlib.util.spec_from_file_location('receiver_under_test', path, submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, key, queue


RECEIVER, KEY, QUEUE = load_receiver()


class Content:
    def __init__(self, body): self.body = body
    async def iter_chunked(self, size):
        for index in range(0, len(self.body), size):
            yield self.body[index:index+size]


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        QUEUE.reset_mock()
        self.entry = types.SimpleNamespace(entry_id='abc123', data={'time_zone':'America/Chicago', 'timestamp_label':'end'}, options={})
        self.state = {'entry':self.entry,'saved':None,'lock':asyncio.Lock(),'active':True,
                      'store':Mock(async_save=AsyncMock()),'coordinator':Mock()}
        async def executor(fn,*args): return fn(*args)
        self.hass = types.SimpleNamespace(data={'empower_naperville':{'state':self.state}}, async_add_executor_job=executor)
        self.payload = {'version':1,'readsStartDate':'2025-06-05T00:15:00','deliveredReads':[1,2,3,4,5,6,7,8]}

    async def post(self, payload=None, body=None):
        request = types.SimpleNamespace(app={KEY:self.hass}, content=Content(body if body is not None else json.dumps(payload or self.payload).encode()))
        return await RECEIVER.ReadingsView().post(request)

    async def test_default_no_statistics_and_secret_drop(self):
        self.assertTrue(RECEIVER.ReadingsView.requires_auth)
        self.payload['customerID']='synthetic-private'
        response = await self.post()
        self.assertEqual(response.status, 200)
        QUEUE.assert_not_called()
        self.assertNotIn('synthetic-private', str(self.state['saved']))
        self.assertEqual(self.state['saved']['summary']['count'], 8)

    async def test_repeat_is_deterministic_and_correction_updates(self):
        self.entry.options['import_statistics']=True
        self.assertEqual((await self.post()).status, 200)
        first = QUEUE.call_args.args[2]
        await self.post()
        self.assertEqual(first, QUEUE.call_args.args[2])
        self.payload['deliveredReads'][0]=2
        await self.post()
        self.assertEqual(QUEUE.call_args.args[2][-1]['sum'],37)

    async def test_reject_short_history_without_mutation(self):
        await self.post()
        previous = self.state['saved']
        self.payload['deliveredReads']=[1]
        self.assertEqual((await self.post()).status, 400)
        self.assertIs(previous,self.state['saved'])

    async def test_bad_json_and_oversize(self):
        self.assertEqual((await self.post(body=b'not JSON')).status, 400)
        self.assertEqual((await self.post(body=b'x'*(RECEIVER.MAX_BYTES+1))).status, 413)

    async def test_unloaded_and_storage_errors(self):
        self.state['active']=False
        self.assertEqual((await self.post()).status,503)
        self.state['active']=True
        self.state['store'].async_save.side_effect=OSError('synthetic-private')
        with self.assertLogs(RECEIVER._LOGGER,level='ERROR') as captured:
            result=await self.post()
        self.assertEqual(result.status,503)
        self.assertNotIn('synthetic-private',' '.join(captured.output))
        self.assertNotIn('synthetic-private',result.text)
