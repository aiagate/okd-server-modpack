"""Synthetic fixtures only; never distribute these manifests as real exports."""
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import ssl
import http.client
import tempfile
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release as r
import publish_pair


class ReleaseTests(unittest.TestCase):
    def submit(self,blob,config,metadata,token,factory):
        # Exercise the production streaming uploader, not an unused legacy POST.
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'okd-server-modpack.zip';path.write_bytes(blob)
        return publish_pair.submit_file(path,config['project_id'],metadata,token,factory)

    def fixture(self, extra=None, change=None):
        manifest = {'manifestType': 'minecraftModpack', 'manifestVersion': 1,
                    'name': 'Synthetic test', 'version': 'test', 'author': 'tests',
                    'overrides': 'overrides',
                    'minecraft': {'version': 'test-version', 'modLoaders': [
                        {'id': 'forge-test-loader', 'primary': True}]},
                    'files': [{'projectID': 1, 'fileID': 2, 'required': True}]}
        if change:
            change(manifest)
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json', json.dumps(manifest))
            z.writestr('overrides/', b'')
            for name, content in (extra or {}).items():
                z.writestr(name, content)
        blob = out.getvalue()
        config = {'project_id': 1,  'minecraft_version': 'test-version',
                  'loader_id': 'forge-test-loader',
                  'game_version_names': ['test-version', 'Forge', 'Client'],
                  'release_type': 'alpha', 'display_name': 'Synthetic test',
                  'reviewed_sha256': hashlib.sha256(blob).hexdigest()}
        return blob, config

    def test_valid_synthetic_export(self):
        b, c = self.fixture({'overrides/config/example.toml': 'enabled = true'})
        self.assertEqual(r.validate(b, c), c['reviewed_sha256'])

    def test_pack_display_name_allowed_but_all_known_draft_markers_rejected(self):
        # A genuine App export may use the pack name; draft versions and
        # unset manifest identity placeholders must still be rejected.
        b, c = self.fixture(change=lambda m: m.update(name='OKD Server Modpack'))
        self.assertEqual(r.validate(b, c), c['reviewed_sha256'])
        for identity in ({'name': 'REPLACE_WITH_APP_PROFILE_NAME'},
                         {'name': 'OKD Server Modpack', 'version': '0.0.0-local.test'},
                         {'name': 'OKD Server Modpack', 'author': 'REPLACE_WITH_AUTHOR'}):
            b, c = self.fixture(change=lambda m: m.update(identity))
            with self.subTest(identity=identity), self.assertRaisesRegex(
                    r.Invalid, 'local reconstruction draft'):
                r.validate(b, c)

    def test_official_shader_modlist_links_allowed_without_broader_url_exemption(self):
        for path in ('complementary-unbound', 'solas-shader'):
            b, c = self.fixture({'modlist.html':
                '<a href="https://www.curseforge.com/minecraft/shaders/' + path + '">shader</a>'})
            self.assertEqual(r.validate(b, c), c['reviewed_sha256'])
        for url in ('https://www.curseforge.com.evil.invalid/minecraft/shaders/solas-shader',
                    'https://www.curseforge.com/minecraft/shaders/solas-shader?token=dummy-secret',
                    'https://dummy-secret@www.curseforge.com/minecraft/shaders/solas-shader',
                    'https://www.curseforge.com/minecraft/shaders/solas-shader/other'):
            b, c = self.fixture({'modlist.html': '<a href="' + url + '">shader</a>'})
            with self.subTest(url=url), self.assertRaises(r.Invalid):
                r.validate(b, c)

    def test_unconfigured_target_allows_only_explicit_offline_validation(self):
        b, c = self.fixture()
        c['project_id'] = None
        self.assertEqual(r.validate(b, c, allow_unconfigured=True), c['reviewed_sha256'])
        with self.assertRaises(r.Invalid): r.validate(b, c)
        c['project_id'] = 1733082
        with self.assertRaises(r.Invalid): r.validate(b, c, allow_unconfigured=True)

    def test_no_other_pack_comment_exceptions_are_imported(self):
        for name in ('overrides/config/c2me.toml', 'overrides/config/apotheosis/enchantments.cfg'):
            b, c = self.fixture({name: '# Documentation: https://example.invalid'})
            with self.subTest(name=name), self.assertRaises(r.Invalid):
                r.validate(b, c)

    def test_reviewed_documentation_does_not_exempt_credentials(self):
        from tempfile import NamedTemporaryFile
        name = 'overrides/config/example.toml'
        comment = '# api_key="dummy-secret"'
        # Even an erroneous future policy entry cannot whitelist a credential.
        with NamedTemporaryFile(mode='w+', suffix='.json') as policy:
            json.dump({name: [hashlib.sha256(comment.encode()).hexdigest()]}, policy)
            policy.flush()
            with patch.object(r, 'REVIEWED_COMMENTS_PATH', Path(policy.name)):
                b, c = self.fixture({name: comment})
                with self.assertRaises(r.Invalid):
                    r.validate(b, c)

    def test_empty_manifest_author_allowed_but_nonstring_author_rejected(self):
        b, c = self.fixture(change=lambda m: m.update(author=''))
        self.assertEqual(r.validate(b, c), c['reviewed_sha256'])
        for author in (None, 1, False):
            b, c = self.fixture(change=lambda m: m.update(author=author))
            with self.subTest(author=author), self.assertRaises(r.Invalid):
                r.validate(b, c)

    def test_paths_and_private_files(self):
        for name in ('../escape', '/absolute', 'overrides/../escape',
                     'overrides\\escape', 'C:/escape', 'wrapper/manifest.json',
                     'overrides/saves/test/level.dat', 'overrides/options.txt',
                     'overrides/servers.dat', 'overrides/.env', 'overrides/mods/mod.jar',
                     'overrides/logs/latest.log'):
            with self.subTest(name=name):
                b, c = self.fixture({name: 'test'})
                with self.assertRaises(r.Invalid):
                    r.validate(b, c)

    def test_sensitive_content_and_binary(self):
        for content in ('api_key = "not-a-real-key"', 'host=192.168.1.1',
                        'endpoint=https://example.invalid', 'host=server.internal', b'\xff'):
            with self.subTest(content=content):
                b, c = self.fixture({'overrides/config/test.txt': content})
                with self.assertRaises(r.Invalid):
                    r.validate(b, c)

    def test_metadata_mismatch(self):
        for key, value in (('minecraft_version', 'other'), ('loader_id', 'fabric-other'),
                           ('game_version_names', ['other']), ('project_id', None),
                           ('project_id', True), ('reviewed_sha256', '0' * 64)):
            with self.subTest(key=key):
                b, c = self.fixture()
                c[key] = value
                with self.assertRaises(r.Invalid):
                    r.validate(b, c)

    def test_manifest_bad_references(self):
        for change in (lambda m: m.update(files=[]),
                       lambda m: m['files'][0].update(fileID=True),
                       lambda m: m.update(manifestVersion=2),
                       lambda m: m['minecraft']['modLoaders'][0].update(primary=False)):
            b, c = self.fixture(change=change)
            with self.assertRaises(r.Invalid):
                r.validate(b, c)

    def test_limits_and_corruption(self):
        b, c = self.fixture()
        with patch.object(r, 'MAX_ZIP', 1), self.assertRaises(r.Invalid):
            r.validate(b, c)
        with patch.object(r, 'MAX_TOTAL', 1), self.assertRaises(r.Invalid):
            r.validate(b, c)
        with patch.object(r, 'MAX_ENTRIES', 0), self.assertRaises(r.Invalid):
            r.validate(b, c)
        b, c = self.fixture({'overrides/config/bomb.txt': 'a' * 100000})
        with self.assertRaises(r.Invalid):
            r.validate(b, c)
        c['reviewed_sha256'] = hashlib.sha256(b'broken').hexdigest()
        with self.assertRaises(zipfile.BadZipFile):
            r.validate(b'broken', c)

    def test_symlink_and_duplicate(self):
        for special in ('symlink', 'duplicate'):
            b, c = self.fixture()
            out = io.BytesIO(b)
            with zipfile.ZipFile(out, 'a') as z:
                entry = zipfile.ZipInfo('overrides/config/link')
                if special == 'symlink':
                    entry.create_system = 3
                    entry.external_attr = 0o120777 << 16
                else:
                    entry = 'MANIFEST.JSON'
                z.writestr(entry, 'target')
            b = out.getvalue()
            c['reviewed_sha256'] = hashlib.sha256(b).hexdigest()
            with self.assertRaises(r.Invalid):
                r.validate(b, c)

    def test_json_duplicate(self):
        with self.assertRaises(r.Invalid):
            r.parse_json('{"a":1,"a":2}')

    def test_changelog_required(self):
        _, c = self.fixture()
        for text in ('', 'REPLACE_ME'):
            with self.assertRaises(r.Invalid):
                r.metadata(c, text)

    def test_submit_same_bytes_and_header_only_token(self):
        b, c = self.fixture()
        r.validate(b, c)
        factory = Mock()
        conn = factory.return_value
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.read.return_value = b'{"id":123}'
        self.assertEqual(self.submit(b, c, r.metadata(c, 'test changes'), 'dummy-token', factory), 123)
        method, path, body, headers = conn.request.call_args.args
        self.assertEqual(method, 'POST')
        self.assertEqual(path, '/api/projects/1/upload-file')
        body=b''.join(body)
        self.assertIn(b, body)
        self.assertIn(b'filename="okd-server-modpack.zip"', body)
        self.assertNotIn(b'dummy-token', body)
        self.assertEqual(headers['X-Api-Token'], 'dummy-token')
        self.assertEqual(int(headers['Content-Length']),len(body))
        conn.request.assert_called_once()
        conn.close.assert_called_once()

    def test_failure_and_redirect_never_retry(self):
        b, c = self.fixture()
        for status in (302, 401, 429, 500):
            factory = Mock()
            conn = factory.return_value
            conn.getresponse.return_value.status = status
            conn.getresponse.return_value.read.return_value = b'{}'
            with self.assertRaises(r.Invalid):
                self.submit(b, c, {}, 'dummy-token', factory)
            conn.request.assert_called_once()

    def test_missing_token_no_network(self):
        b, c = self.fixture()
        factory = Mock()
        with self.assertRaises(r.Invalid):
            self.submit(b, c, {}, '', factory)
        factory.assert_not_called()

    def test_http_diagnostics_record_only_whitelisted_projection_of_server_text(self):
        b, c = self.fixture()
        for status in (302, 401, 403, 429, 500):
            factory = Mock()
            conn = factory.return_value
            response = conn.getresponse.return_value
            response.status = status
            response.reason = 'dummy-token user@example.invalid'
            response.read.return_value = b'X-Api-Token: dummy-token user@example.invalid'
            conn.close.side_effect = OSError('dummy-token')
            with self.subTest(status=status), self.assertRaises(r.SubmissionError) as error:
                self.submit(b, c, {}, 'dummy-token', factory)
            self.assertEqual(error.exception.diagnostics, {
                'category': 'http_non_success', 'phase': 'response_headers',
                'http_status': status, 'response_body_recorded': False,
                'response_summary': {'response_format': 'non_json',
                                     'validation_fields': [], 'validation_codes': []}})
            self.assertNotIn('dummy-token', str(error.exception))
            self.assertNotIn('user@example.invalid', json.dumps(error.exception.diagnostics))
            response.read.assert_called_once_with(65537)
            response.getheader.assert_not_called()
            conn.request.assert_called_once()

    def test_transport_categories_are_safe_and_preserve_known_http_status(self):
        b, c = self.fixture()
        for phase, failure, category, status in (
                ('request', ssl.SSLError('dummy-token'), 'tls_error', None),
                ('getresponse', TimeoutError('user@example.invalid'), 'timeout', None),
                ('request', OSError('dummy-token'), 'connection_error', None),
                ('getresponse', http.client.BadStatusLine('dummy-token'), 'http_protocol_error', None),
                ('read', TimeoutError('dummy-token'), 'timeout', 200)):
            factory = Mock()
            conn = factory.return_value
            response = conn.getresponse.return_value
            response.status = 200
            target = response.read if phase == 'read' else getattr(conn, phase)
            target.side_effect = failure
            with self.subTest(phase=phase, category=category), self.assertRaises(r.SubmissionError) as error:
                self.submit(b, c, {}, 'dummy-token', factory)
            self.assertEqual(error.exception.diagnostics['category'], category)
            self.assertEqual(error.exception.diagnostics['http_status'], status)
            self.assertNotIn('dummy-token', str(error.exception))
            self.assertNotIn('user@example.invalid', str(error.exception))
            conn.request.assert_called_once()
            conn.close.assert_called_once()
        factory = Mock(side_effect=OSError('dummy-token'))
        with self.assertRaises(r.SubmissionError) as error:
            self.submit(b, c, {}, 'dummy-token', factory)
        self.assertEqual(error.exception.diagnostics['phase'], 'connection_setup')

    def test_response_diagnostics_keep_status_without_body_content(self):
        b, c = self.fixture()
        for body, category in ((b'not-json dummy-token', 'invalid_json_response'),
                               (b'{"id":1,"id":2}', 'invalid_json_response'),
                               (b'{"id": "dummy-token"}', 'missing_valid_file_id'),
                               (b'a' * 65537, 'response_too_large')):
            factory = Mock()
            conn = factory.return_value
            response = conn.getresponse.return_value
            response.status = 201
            response.read.return_value = body
            with self.subTest(category=category), self.assertRaises(r.SubmissionError) as error:
                self.submit(b, c, {}, 'dummy-token', factory)
            self.assertEqual(error.exception.diagnostics['category'], category)
            self.assertEqual(error.exception.diagnostics['http_status'], 201)
            self.assertNotIn('dummy-token', json.dumps(error.exception.diagnostics))
            response.read.assert_called_once_with(65537)
            conn.request.assert_called_once()


    def test_validation_projection_drops_free_text_unknown_fields_and_codes(self):
        raw = json.dumps({'errorCode': 400, 'errorMessage': 'dummy-token user@example.invalid',
                          'errors': {'metadata.gameVersions[0]': [{'code': 'invalid_value',
                                     'message': 'dummy-token'}],
                                     'dummy-token': [{'code': 'dummy-token'}]},
                          'validationErrors': [{'field': 'releaseType', 'code': 'required',
                                                'message': 'user@example.invalid'},
                                               {'field': 'user@example.invalid', 'code': 'private'}]})
        self.assertEqual(r.safe_api_error(raw), {
            'response_format': 'json_object', 'error_code': 400,
            'validation_fields': ['gameVersions', 'releaseType'],
            'validation_codes': ['invalid_value', 'required']})
        for raw in (b'private non-json dummy-token', b'a' * 65537,
                    b'{"errorCode":"dummy-token","errors":{"password":["dummy-token"]}}',
                    b'{"errorCode":123456789,"message":"user@example.invalid"}'):
            result = json.dumps(r.safe_api_error(raw))
            for text in ('dummy-token', 'password', 'user@example.invalid', '123456789'):
                self.assertNotIn(text, result)

    def test_protocol_diagnostic_keeps_parent_approval_reason(self):
        result=r.safe_api_error(json.dumps({'errorCode':1013,'errorMessage':'Only approved files can be used as parent file.'}))
        self.assertEqual(result['diagnostic_messages'],['Only approved files can be used as parent file .'])
        self.assertEqual(result['error_code'],1013)
    def test_protocol_diagnostic_redacts_reflected_secrets_urls_and_unknown_values(self):
        raw=json.dumps({'errorMessage':'Invalid parentFileID: approved https://private.invalid/a?token=abc user@example.invalid 123456 /private/path unknownvalue'})
        result=r.safe_api_error(raw,secrets=('approved',))
        text=json.dumps(result)
        for private in ('approved','private.invalid','user@example','123456','unknownvalue','private/path'):
            self.assertNotIn(private,text)
        self.assertIn('Invalid parentFileID',text)
    def test_error_transport_passes_token_to_diagnostic_redaction(self):
        b,c=self.fixture();factory=Mock();response=factory.return_value.getresponse.return_value
        response.status=400;response.read.return_value=b'{"message":"Invalid token approved"}'
        with self.assertRaises(r.SubmissionError) as err:self.submit(b,c,{},'approved',factory)
        self.assertNotIn('approved',json.dumps(err.exception.diagnostics))
        self.assertIn('Invalid token',json.dumps(err.exception.diagnostics))

    def test_error_response_read_failure_keeps_original_http_rejection(self):
        b, c = self.fixture()
        factory = Mock()
        conn = factory.return_value
        conn.getresponse.return_value.status = 400
        conn.getresponse.return_value.read.side_effect = TimeoutError('dummy-token')
        with self.assertRaises(r.SubmissionError) as error:
            self.submit(b, c, {}, 'dummy-token', factory)
        self.assertEqual(error.exception.diagnostics['http_status'], 400)
        self.assertEqual(error.exception.diagnostics['category'], 'http_non_success')
        self.assertEqual(error.exception.diagnostics['response_summary']['response_format'], 'read_failed')
        conn.request.assert_called_once()

    def test_nested_error_codes_and_authentication_hints_never_retain_messages(self):
        raw = json.dumps({'Error': {'ErrorCode': 1009,
                                   'ErrorMessage': 'Invalid API token: dummy-token user@example.invalid'},
                          'ModelState': {'Metadata.GameVersions[0]': ['private response']}})
        result = r.safe_api_error(raw)
        self.assertEqual(result['error_code'], 1009)
        self.assertEqual(result['message_hints'], ['invalid_authentication'])
        self.assertEqual(result['validation_fields'], ['gameVersions'])
        for forbidden in ('dummy-token', 'user@example.invalid', 'private response', 'ErrorMessage'):
            self.assertNotIn(forbidden, json.dumps(result))


    def test_timeout_and_invalid_responses_never_retry(self):
        b, c = self.fixture()
        for response in (b'{}', b'{"id":true}', b'{"id":-1}', b'not-json',
                         b'{"id":1,"id":2}', TimeoutError('dummy timeout')):
            factory = Mock()
            conn = factory.return_value
            conn.getresponse.return_value.status = 200
            if isinstance(response, Exception):
                conn.getresponse.side_effect = response
            else:
                conn.getresponse.return_value.read.return_value = response
            with self.subTest(response=response), self.assertRaises(r.Invalid):
                self.submit(b, c, {}, 'dummy-token', factory)
            conn.request.assert_called_once()
            conn.close.assert_called_once()



    def test_manifest_and_modlist_secrets_rejected_without_disclosure(self):
        changes = [lambda m: m.update(api_key='dummy-review-secret'),
                   lambda m: m.update(version='token=dummy-review-secret'),
                   lambda m: m.update(author='https://private.example.invalid')]
        for change in changes:
            b, c = self.fixture(change=change)
            with self.assertRaises(r.Invalid) as error:
                r.validate(b, c)
            self.assertNotIn('dummy-review-secret', str(error.exception))
        for content in ('password=dummy-review-secret',
                        '<a href="https://example.invalid">private destination</a>',
                        'password&#61;dummy-review-secret', b'\xff', b'\x00'):
            b, c = self.fixture({'modlist.html': content})
            with self.assertRaises(r.Invalid) as error:
                r.validate(b, c)
            self.assertNotIn('dummy-review-secret', str(error.exception))

    def test_public_modlist_links_allowed_but_credentials_in_url_rejected(self):
        for url in ('https://www.curseforge.com/minecraft/mc-mods/create',
                    'https://minecraft.curseforge.com/projects/create',
                    'https://www.curseforge.com/minecraft/mc-mods/create/files/123'):
            b, c = self.fixture({'modlist.html': f'<a href="{url}">Create</a>'})
            self.assertEqual(r.validate(b, c), c['reviewed_sha256'])
        for url in ('https://www.curseforge.com/minecraft/mc-mods/create?token=dummy-secret',
                    'https://www.curseforge.com.example.invalid/minecraft/mc-mods/create'):
            b, c = self.fixture({'modlist.html': f'<a href="{url}">test</a>'})
            with self.assertRaises(r.Invalid):
                r.validate(b, c)

    def test_overrides_must_be_directory(self):
        b, c = self.fixture({'overrides': 'not a directory'})
        with self.assertRaises(r.Invalid):
            r.validate(b, c)
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(b)) as original, zipfile.ZipFile(out, 'w') as archive:
            archive.writestr('manifest.json', original.read('manifest.json'))
        b = out.getvalue()
        c['reviewed_sha256'] = hashlib.sha256(b).hexdigest()
        with self.assertRaisesRegex(r.Invalid, 'overrides directory missing'):
            r.validate(b, c)



if __name__ == '__main__':
    unittest.main()
