import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import diagnose_api as d


class AuditTests(unittest.TestCase):
    def test_one_get_resolves_only_exact_public_names_and_ids(self):
        factory = Mock()
        conn = factory.return_value
        response = conn.getresponse.return_value
        response.status = 200
        rows = [{'name': name, 'id': i + 1, 'gameVersionTypeID': i + 2,
                 'private': 'dummy-token user@example.invalid'} for i, name in enumerate(d.WANTED)]
        rows.append({'name': 'dummy-token', 'id': 4, 'gameVersionTypeID': 5})
        response.read.return_value = json.dumps(rows).encode()
        result = d.audit('dummy-token', factory)
        self.assertEqual(result['category'], 'all_metadata_names_exist')
        self.assertEqual(result['missing_names'], [])
        self.assertEqual(len(result['matched_versions']), 3)
        conn.request.assert_called_once_with('GET', '/api/game/versions',
                                            headers={'X-Api-Token': 'dummy-token'})
        conn.close.assert_called_once()
        for forbidden in ('dummy-token', 'user@example.invalid', 'private'):
            self.assertNotIn(forbidden, json.dumps(result))

    def test_missing_names_are_not_hidden_by_duplicate_rows(self):
        for rows, category in (([], 'missing_version_names'),
                               ([{'name': 'Client', 'id': 1, 'gameVersionTypeID': 2}] * 2,
                                'missing_version_names')):
            factory = Mock()
            response = factory.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = json.dumps(rows).encode()
            self.assertEqual(d.audit('dummy-token', factory)['category'], category)
            factory.return_value.request.assert_called_once()

    def test_read_only_errors_are_sanitized_and_never_retry(self):
        factory = Mock()
        response = factory.return_value.getresponse.return_value
        response.status = 403
        response.read.return_value = b'{"errorCode":403,"errorMessage":"dummy-token user@example.invalid"}'
        result = d.audit('dummy-token', factory)
        self.assertEqual(result['http_status'], 403)
        self.assertEqual(result['response_summary']['error_code'], 403)
        self.assertNotIn('dummy-token', json.dumps(result))
        self.assertNotIn('user@example.invalid', json.dumps(result))
        factory.return_value.request.assert_called_once()
        with self.assertRaises(d.Invalid):
            d.audit('', factory)
        factory.return_value.request.assert_called_once()


class CredentialPreflightTests(unittest.TestCase):
    def test_reports_properties_without_token_value_prefix_length_or_hash(self):
        token=' synthetic-example-value\n'
        result=d.credential_preflight(token)
        self.assertTrue(result['present'])
        self.assertTrue(result['has_whitespace'])
        self.assertTrue(result['has_control_characters'])
        self.assertFalse(result['token_kind_verified_from_format'])
        self.assertTrue(all(type(v) is bool for v in result.values()))
        self.assertNotIn(token,json.dumps(result))
    def test_opaque_format_does_not_prove_token_kind(self):
        result=d.credential_preflight('synthetic-example-value')
        self.assertFalse(result['has_whitespace'])
        self.assertFalse(result['has_control_characters'])
        self.assertFalse(result['has_non_ascii_characters'])
        self.assertFalse(result['token_kind_verified_from_format'])


class MalformedTokenResponseTests(unittest.TestCase):
    def test_token_parse_error_is_fixed_hint_and_secret_text_is_discarded(self):
        factory=Mock(); response=factory.return_value.getresponse.return_value
        response.status=400
        response.read.return_value=b'{"errorCode":3,"errorMessage":"Cannot parse token synthetic-secret-value"}'
        result=d.audit('dummy-token',factory)
        self.assertEqual(result['response_summary']['error_code'],3)
        self.assertEqual(result['response_summary']['message_hints'],['malformed_authentication'])
        self.assertNotIn('synthetic-secret-value',json.dumps(result))
        factory.return_value.request.assert_called_once()


class VersionNameVariantTests(unittest.TestCase):
    def test_required_names_in_multiple_types_do_not_require_guessing_numeric_ids(self):
        factory=Mock(); response=factory.return_value.getresponse.return_value
        response.status=200
        rows=[{'name':name,'id':i+1,'gameVersionTypeID':100+i} for i,name in enumerate(d.WANTED)]
        rows.append({'name':'1.21.1','id':1000,'gameVersionTypeID':1})
        response.read.return_value=json.dumps(rows).encode()
        result=d.audit('dummy-token',factory)
        self.assertEqual(result['status'],'read_complete')
        self.assertEqual(result['missing_names'],[])
        self.assertEqual(result['category'],'all_metadata_names_present_with_variants')
        self.assertFalse(result['numeric_ids_selected'])
        self.assertEqual(len(result['matched_versions']),4)
