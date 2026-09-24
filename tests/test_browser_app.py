"""App boundary tests. Chromium and the Supervisor are mocked, never launched."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'empower_browser'))
import browser
import server


class BrowserTests(unittest.TestCase):
    def test_safe_fields_only(self):
        result = browser.safe_payload({'readsStartDate':'2025-06-05T00:15:00', 'deliveredReads':'.165,.117', 'custId':'synthetic-private'})
        self.assertEqual(result['deliveredReads'], [.165,.117])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(server.summary(result)['latest'], '2025-06-05T00:30:00')

    def test_reject_invalid_data(self):
        for raw in (None, {'error':'sign_in_required'}, {'readsStartDate':'x','deliveredReads':'1,,2'}, {'readsStartDate':'x','deliveredReads':[True]}):
            with self.assertRaises(browser.BrowserFailure):
                browser.safe_payload(raw)

    def test_selenium_error_redaction(self):
        reader = browser.Browser()
        reader.driver = Mock()
        reader.driver.execute_script.side_effect = RuntimeError('synthetic-cookie-secret')
        with self.assertRaises(browser.BrowserFailure) as caught:
            reader.read()
        self.assertNotIn('synthetic-cookie-secret', str(caught.exception))


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingress_ip_not_forwarding_header(self):
        handler = AsyncMock(return_value=web.Response(text='ok'))
        request = Mock(remote='127.0.0.1', method='GET', headers={'X-Forwarded-For':'172.30.32.2'})
        with self.assertRaises(web.HTTPForbidden):
            await server.ingress_only(request, handler)
        handler.assert_not_called()
        request.remote = '172.30.32.2'
        self.assertEqual((await server.ingress_only(request, handler)).text, 'ok')

    async def test_action_header_required(self):
        request = Mock(remote='172.30.32.2', method='POST', headers={})
        with self.assertRaises(web.HTTPForbidden):
            await server.ingress_only(request, AsyncMock())

    async def test_collect_without_integration_token(self):
        pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(pool.shutdown)
        state = {'browser':Mock(), 'pool':pool, 'lock':asyncio.Lock(), 'armed':False}
        state['browser'].read.return_value = {'version':1,'readsStartDate':'2025-06-05T00:15:00','deliveredReads':[.165,.117]}
        with patch.dict('os.environ', {}, clear=True):
            await server.collect(state, False)
        self.assertTrue(state['armed'])
        self.assertEqual(state['summary']['count'], 2)
        self.assertIn('API access is unavailable', state['message'])

    async def test_collect_expired_session(self):
        pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(pool.shutdown)
        state = {'browser':Mock(), 'pool':pool, 'lock':asyncio.Lock(), 'armed':False}
        state['browser'].read.side_effect = browser.BrowserFailure('Sign in again.')
        await server.collect(state, True)
        self.assertEqual(state['message'], 'Sign in again.')
        self.assertFalse(state['armed'])
