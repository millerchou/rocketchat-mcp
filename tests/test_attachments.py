import copy
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

with patch('logging.handlers.RotatingFileHandler', return_value=logging.NullHandler()):
    import rocketchat


SERVER = 'https://chat.example.com'
MESSAGE = {
    '_id': 'forward-1', 'msg': '', 'ts': '2026-01-01T00:00:00Z',
    'u': {'username': 'example'},
    'attachments': [{
        'message_link': SERVER + '/group/private?msg=original-1',
        'author_name': 'Original author', 'text': 'Please inspect the attached log.',
        'attachments': [{
            'type': 'file', 'title': 'log.txt',
            'title_link': '/file-upload/upload-1/log.txt',
        }],
    }],
}


class AttachmentMetadataTests(unittest.TestCase):
    def test_quotes_keep_text_file_and_containing_message_id(self):
        text = rocketchat.format_message_line(MESSAGE, server_url=SERVER)
        self.assertIn('Please inspect the attached log.', text)
        self.assertIn('log.txt', text)
        self.assertIn('message_id: forward-1, attachment_id: upload-1', text)
        self.assertIn('quoted attachment', text)

    def test_direct_file_and_quote_references_are_deduplicated(self):
        message = copy.deepcopy(MESSAGE)
        message['files'] = [{'_id': 'upload-1', 'name': 'log.txt', 'type': 'text/plain'}]
        files = rocketchat.message_files(message, SERVER)
        self.assertEqual(len(files), 1)
        self.assertFalse(files[0]['quoted'])

    def test_single_file_and_unicode_filenames_remain_supported(self):
        files = rocketchat.message_files({'file': {'_id': 'upload-2', 'name': 'example log #1.txt'}}, SERVER)
        self.assertEqual(files[0]['url'], SERVER + '/file-upload/upload-2/example%20log%20%231.txt')
        self.assertIn('example log #1.txt', rocketchat.format_message_line({'file': {'_id': 'upload-2', 'name': 'example log #1.txt'}}))

    def test_unsupported_destinations_and_bad_metadata_are_not_downloadable(self):
        for value in [
            'https://outside.example.com/file-upload/upload-1/log.txt',
            '//outside.example.com/file-upload/upload-1/log.txt',
            '/api/v1/users.list', '/file-upload/%2e%2e/settings',
            'https://user:password@chat.example.com/file-upload/upload-1/log.txt',
            'https://[invalid/file-upload/upload-1/log.txt',
        ]:
            with self.subTest(value=value):
                self.assertEqual(rocketchat.message_files({'attachments': [{'title_link': value}]}, SERVER), [])
        self.assertEqual(rocketchat.message_files({'attachments': [None, 'bad'], 'files': None}, SERVER), [])

    def test_nested_quotes_are_bounded(self):
        message = {'attachments': []}
        cursor = message
        for _ in range(20):
            child = {'message_link': SERVER + '/group/room?msg=nested', 'text': 'x' * 9000, 'attachments': []}
            cursor['attachments'].append(child)
            cursor = child
        text = rocketchat.format_message_line(message, server_url=SERVER)
        self.assertIn('[quoted text truncated]', text)
        self.assertLess(len(text), 9000)


class AttachmentDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.message = copy.deepcopy(MESSAGE)
        self.file_status = 200
        self.redirect = None
        self.directory = tempfile.TemporaryDirectory()
        self.old_client = rocketchat.rocket_client
        self.client = rocketchat.RocketChatAPI(SERVER, user_id='example-user', auth_token='unit-test-token')
        self.client._client = httpx.AsyncClient(transport=httpx.MockTransport(self.respond))
        rocketchat.rocket_client = self.client
        original_mkstemp = tempfile.mkstemp
        self.temp_patch = patch.object(rocketchat.tempfile, 'mkstemp', side_effect=lambda **kwargs: original_mkstemp(dir=self.directory.name, **kwargs))
        self.temp_patch.start()

    async def asyncTearDown(self):
        self.temp_patch.stop()
        await self.client._client.aclose()
        rocketchat.rocket_client = self.old_client
        self.directory.cleanup()

    def respond(self, request):
        self.requests.append(request)
        if request.url.path == '/api/v1/chat.getMessage':
            if request.url.params['msgId'] == 'original-1':
                return httpx.Response(400, json={'errorType': 'error-not-allowed', 'error': 'Not allowed'})
            self.assertEqual(request.url.params['msgId'], 'forward-1')
            return httpx.Response(200, json={'success': True, 'message': self.message})
        if request.url.host == 'storage.example.com':
            return httpx.Response(200, content=b'synthetic log\n')
        self.assertTrue(request.url.path.startswith('/file-upload/'))
        if self.redirect:
            return httpx.Response(302, headers={'Location': self.redirect})
        return httpx.Response(self.file_status, content=b'synthetic log\n')

    async def test_downloads_quote_without_requesting_inaccessible_original(self):
        result = await rocketchat.download_attachment('forward-1', 'upload-1')
        self.assertIn('Downloaded 1 attachment(s)', result)
        self.assertEqual([r.url.path for r in self.requests], ['/api/v1/chat.getMessage', '/file-upload/upload-1/log.txt'])
        self.assertEqual(next(Path(self.directory.name).iterdir()).read_bytes(), b'synthetic log\n')

    async def test_legacy_call_downloads_all_and_does_not_overwrite_files(self):
        self.message['files'] = [{'_id': 'upload-2', 'name': 'report:1.txt'}]
        for _ in range(2):
            self.assertIn('Downloaded 2 attachment(s)', await rocketchat.download_attachment('forward-1'))
        files = list(Path(self.directory.name).iterdir())
        self.assertEqual(len(files), 4)
        self.assertTrue(all(p.parent == Path(self.directory.name) for p in files))

    async def test_unknown_selection_does_not_download_anything(self):
        result = await rocketchat.download_attachment('forward-1', 'changed-id')
        self.assertIn('read the message again', result)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(os.listdir(self.directory.name), [])

    async def test_cross_origin_storage_redirect_does_not_receive_auth_headers(self):
        self.redirect = 'https://storage.example.com/object'
        self.assertIn('Downloaded 1 attachment(s)', await rocketchat.download_attachment('forward-1'))
        self.assertEqual(self.requests[-2].headers['X-Auth-Token'], 'unit-test-token')
        self.assertNotIn('X-Auth-Token', self.requests[-1].headers)
        self.assertNotIn('X-User-Id', self.requests[-1].headers)

    async def test_server_denial_and_unsafe_redirect_do_not_save_a_file(self):
        self.file_status = 403
        self.assertIn('HTTP 403', await rocketchat.download_attachment('forward-1'))
        self.assertEqual(os.listdir(self.directory.name), [])
        for self.redirect in ['http://storage.example.com/object', SERVER + '/api/v1/users.list']:
            with self.subTest(redirect=self.redirect):
                self.assertIn('Unsupported attachment', await rocketchat.download_attachment('forward-1'))
                self.assertEqual(os.listdir(self.directory.name), [])

    async def test_api_error_preserves_server_reason(self):
        result = await rocketchat.download_attachment('original-1')
        self.assertIn('HTTP 400', result)
        self.assertIn('error-not-allowed', result)
        self.assertIn('Not allowed', result)

    async def test_api_error_keeps_http_exception_type_and_omits_authentication_secret(self):
        await self.client._client.aclose()
        self.client._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: httpx.Response(401, json={'errorType': 'unauthorized', 'message': 'token unit-test-token is invalid'})
        ))
        with self.assertRaises(httpx.HTTPStatusError) as error:
            await self.client.async_request('GET', 'chat.getMessage', params={'msgId': 'forward-1'})
        self.assertEqual(error.exception.response.status_code, 401)
        self.assertIn('unauthorized', str(error.exception))
        self.assertNotIn('unit-test-token', str(error.exception))


if __name__ == '__main__':
    unittest.main()
