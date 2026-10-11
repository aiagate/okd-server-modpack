"""Submission state tests use fake journals and fake POSTs; no API calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import publish_pair as p
import release

class Journal:
    def __init__(self): self.rows={}
    def read(self,k,phase): return self.rows.get((k,phase))
    def claim(self,k):
        release.need((k,'claim') not in self.rows,'unconfirmed previous claim')
        self.rows[k,'claim']=True
    def result(self,k,fid,parent=None):
        row=dict(schema_version=1,**IDENTITY,kind=k,file_id=fid)
        if k=='server': row['parent_file_id']=parent
        self.rows[k,'result']=row

IDENTITY=p.fingerprint(999999,'synthetic-next','a'*64,'b'*64)
CONFIG=dict(project_id=999999,display_name='Synthetic',release_type='alpha',
    game_version_names=['1.21.1','NeoForge','Client'])

class PublicationTests(unittest.TestCase):
    def call(self,j,u,**extra):
        return p.publish(Path('client.zip'),Path('server.zip'),CONFIG,'synthetic-next',
            'test',IDENTITY,None,j,token='synthetic-token',uploader=u,**extra)
    def test_parent_link_and_rerun_never_posts_again(self):
        journal=Journal(); upload=Mock(side_effect=[101,102])
        result=self.call(journal,upload)
        child=upload.call_args_list[1].args[2]
        self.assertEqual(child['parentFileID'],101)
        self.assertIs(child['isServerPack'],True)
        self.assertNotIn('isServerPack',upload.call_args_list[0].args[2])
        self.assertNotIn('gameVersionNames',child)
        self.assertNotIn('gameVersions',child)
        self.assertEqual(result['server_file_id'],102)
        self.call(journal,upload)
        self.assertEqual(upload.call_count,2)
    def test_child_timeout_preserves_parent_and_blocks_fresh_dispatch(self):
        journal=Journal(); upload=Mock(side_effect=[101,release.SubmissionError('timeout','request')])
        with self.assertRaises(release.SubmissionError): self.call(journal,upload)
        self.assertEqual(journal.read('client','result')['file_id'],101)
        with self.assertRaises(release.Invalid): self.call(journal,upload)
        self.assertEqual(upload.call_count,2)
    def test_client_timeout_blocks_every_retry(self):
        journal=Journal(); upload=Mock(side_effect=release.SubmissionError('timeout','response_body'))
        for _ in range(2):
            with self.assertRaises((release.Invalid,release.SubmissionError)): self.call(journal,upload)
        upload.assert_called_once()
    def test_server_only_requires_matching_parent(self):
        upload=Mock(); journal=Journal()
        with self.assertRaises(release.Invalid): self.call(journal,upload,mode='server_only')
        upload.assert_not_called(); self.assertEqual(journal.rows,{})
        journal.result('client',101)
        upload.return_value=102
        self.call(journal,upload,mode='server_only')
        upload.assert_called_once(); self.assertEqual(upload.call_args.args[2]['parentFileID'],101)
        self.assertIs(upload.call_args.args[2]['isServerPack'],True)
    def test_child_metadata_rejection_never_falls_back_to_another_post(self):
        journal=Journal()
        upload=Mock(side_effect=[101,release.SubmissionError('rejected','response_body')])
        with self.assertRaises(release.SubmissionError): self.call(journal,upload)
        self.assertIs(upload.call_args_list[1].args[2]['isServerPack'],True)
        with self.assertRaises(release.Invalid): self.call(journal,upload)
        self.assertEqual(upload.call_count,2)
        self.assertEqual(journal.read('client','result')['file_id'],101)
    def test_explicit_existing_parent_is_verified_before_server_only(self):
        journal=Journal(); upload=Mock(return_value=102); verifier=Mock()
        self.call(journal,upload,mode='server_only',existing_client_file_id=101,verifier=verifier)
        verifier.assert_called_once_with(101,999999,Path('client.zip'))
        upload.assert_called_once()
    def test_wrong_existing_parent_bytes_cannot_post(self):
        upload=Mock(); verifier=Mock(side_effect=release.Invalid('wrong bytes'))
        with self.assertRaises(release.Invalid):
            self.call(Journal(),upload,existing_client_file_id=101,verifier=verifier)
        upload.assert_not_called()
    def test_published_same_version_changed_bytes_stops_before_journal(self):
        known=dict(schema_version=1,**IDENTITY); known['server_sha256']='c'*64
        journal=Mock(); upload=Mock()
        with self.assertRaises(release.Invalid):
            p.publish(Path('c'),Path('s'),CONFIG,'synthetic-next','test',IDENTITY,known,journal,uploader=upload)
        journal.read.assert_not_called(); upload.assert_not_called()
    def test_result_parent_mismatch_fails(self):
        journal=Journal(); journal.result('client',101); journal.result('server',102,999)
        upload=Mock()
        with self.assertRaises(release.Invalid): self.call(journal,upload)
        upload.assert_not_called()
    def test_accepted_id_survives_journal_write_failure(self):
        journal=Journal(); journal.result=Mock(side_effect=release.Invalid('journal failed'))
        with tempfile.TemporaryDirectory() as tmp:
            receipt=Path(tmp)/'receipt.json'
            with self.assertRaises(release.Invalid): self.call(journal,Mock(return_value=101),receipt=receipt)
            record=json.loads(receipt.read_text())
            self.assertEqual(record['client_file_id'],101)
            self.assertEqual(record['status'],'accepted_pending_journal')
    def test_known_pair_skips_posts(self):
        known=dict(schema_version=1,**IDENTITY,client={'file_id':101},server={'file_id':102,'parent_file_id':101})
        journal=Mock(); upload=Mock()
        p.publish(Path('c'),Path('s'),CONFIG,'synthetic-next','test',IDENTITY,known,journal,uploader=upload)
        upload.assert_not_called(); journal.read.assert_not_called()
    def test_unwritable_receipt_stops_before_any_claim_or_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Mock();upload=Mock()
            with self.assertRaises(OSError):self.call(journal,upload,receipt=Path(tmp))
            journal.read.assert_not_called();upload.assert_not_called()
    def test_manual_publication_flag_is_explicit(self):
        upload=Mock(side_effect=[101,102]); self.call(Journal(),upload,manual=True)
        self.assertTrue(all(c.args[2]['isMarkedForManualRelease'] for c in upload.call_args_list))

class AuthenticationPreflightTests(unittest.TestCase):
    def test_failed_get_blocks_github_mutation_and_post_and_keeps_sanitized_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'server.json'; source.write_text(json.dumps({'sha256':'b'*64}))
            (root/'client.json').write_text('{}')
            receipt=root/'receipt.json'
            (root/'client.json').write_text('{}')
            args=['publish_pair.py','--client-receipt',str(root/'client.json'),'--client',str(root/'client.zip'),'--server',str(root/'server.zip'),
                '--server-receipt',str(source),'--receipt',str(receipt),'--state',str(root/'absent.json'),'--submit']
            config=dict(CONFIG)
            with patch.object(sys,'argv',args), patch.dict('os.environ',{
                    'GITHUB_REF':'refs/heads/main','CURSEFORGE_SUBMISSION_ENABLED':'true',
                    'CURSEFORGE_API_TOKEN':'synthetic-token'}), \
                 patch('native_pack.load_inputs',return_value=({'version':'synthetic-next'}, {}, {}, 'source')), patch('native_pack.runtime_config',return_value=config), \
                 patch('native_pack.verify_client',return_value='a'*64), \
                 patch('native_pack.policy',return_value={}), \
                 patch('serverpack.verify_prepared'), \
                 patch('diagnose_api.audit',return_value={'status':'unconfirmed','http_status':400,'category':'http_non_success'}), \
                 patch.object(p,'publish_github') as github, patch.object(p,'publish') as publisher:
                self.assertEqual(p.main(),1)
            github.assert_not_called(); publisher.assert_not_called()
            self.assertEqual(json.loads(receipt.read_text())['status'],'authentication_preflight_failed')

class RepositoryValidationTests(unittest.TestCase):
    def test_changed_client_fails_before_github_or_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'client.json').write_text('{}')
            args=['publish_pair.py','--client',str(root/'client.zip'),'--client-receipt',str(root/'client.json'),
                '--server',str(root/'server.zip'),'--server-receipt',str(root/'server.json'),
                '--receipt',str(root/'receipt.json'),'--submit']
            with patch.object(sys,'argv',args),patch('native_pack.load_inputs',return_value=({'version':'0.0.2'},{},{},'source')), \
                 patch('native_pack.verify_client',side_effect=release.Invalid('changed source bytes')), \
                 patch.object(p,'publish_github') as github,patch.object(p,'publish') as publisher:
                self.assertEqual(p.main(),1)
            github.assert_not_called();publisher.assert_not_called()
            self.assertFalse((root/'receipt.json').exists())

class VersionVariantPublicationTests(unittest.TestCase):
    def test_documented_string_metadata_passes_audit_with_multiple_type_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'server.json'; source.write_text(json.dumps({'sha256':'b'*64}))
            (root/'client.json').write_text('{}')
            args=['publish_pair.py','--client-receipt',str(root/'client.json'),'--client',str(root/'client.zip'),'--server',str(root/'server.zip'),
                '--server-receipt',str(source),'--receipt',str(root/'receipt.json'),
                '--state',str(root/'absent.json'),'--submit']
            report={'status':'read_complete','category':'all_metadata_names_present_with_variants','missing_names':[]}
            with patch.object(sys,'argv',args), patch.dict('os.environ',{
                    'GITHUB_REF':'refs/heads/main','CURSEFORGE_SUBMISSION_ENABLED':'true',
                    'CURSEFORGE_API_TOKEN':'synthetic-token'}), \
                 patch('native_pack.load_inputs',return_value=({'version':'synthetic-next'}, {}, {}, 'source')), patch('native_pack.runtime_config',return_value=dict(CONFIG)), \
                 patch('native_pack.verify_client',return_value='a'*64), \
                 patch('native_pack.policy',return_value={}), \
                 patch('serverpack.verify_prepared'), \
                 patch('diagnose_api.audit',return_value=report), \
                 patch.object(p,'publish_github') as github, \
                 patch.object(p,'publish',return_value={'status':'synthetic-no-network'}) as publisher:
                self.assertEqual(p.main(),0)
            github.assert_called_once(); publisher.assert_called_once()

if __name__=='__main__': unittest.main()
