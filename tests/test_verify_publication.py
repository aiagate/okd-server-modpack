import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_publication as v
import publish_pair as p
import release

class PublicVerificationTests(unittest.TestCase):
    def setUp(self):
        self.identity=p.fingerprint(1,'0.0.2','a'*64,'b'*64)
        self.assets={'client':{'name':'client.zip','size':10},'server':{'name':'server.zip','size':20}}
        self.client={'id':11,'projectId':1,'fileName':'client.zip','fileLength':10,'status':4,
            'hasServerPack':True,'additionalFilesCount':1,'additionalServerPackFilesCount':1}
        self.server={'id':12,'projectId':1,'fileName':'server.zip','fileLength':20,'status':4}
        self.children=[dict(self.server,parentProjectFileId=11)]
    def assess(self):return v.assess(self.identity,11,12,self.assets,self.client,self.server,self.children)
    def test_approved_classified_pair_still_requires_exact_cdn_byte_check(self):
        r=self.assess();self.assertEqual(r['status'],'approved_waiting_for_byte_verification')
        self.assertTrue(r['server_pack_classification_verified']);self.assertFalse(r['publication_complete'])
    def test_approved_generic_additional_file_is_not_complete(self):
        self.client.update(hasServerPack=False,additionalServerPackFilesCount=0)
        r=self.assess();self.assertEqual(r['status'],'server_pack_setting_required_or_ambiguous')
        self.assertFalse(r['publication_complete'])
        self.assertEqual(r['required_action']['client_file_id'],11)
        self.assertEqual(r['required_action']['server_file_id'],12)
        self.assertIs(r['required_action']['retry_submission'],False)
    def test_unpublished_server_is_waiting_not_complete(self):
        self.server=None;r=self.assess();self.assertEqual(r['status'],'waiting_for_moderation')
        self.assertFalse(r['publication_complete'])
    def test_pending_server_is_waiting(self):
        self.server['status']=1;self.assertEqual(self.assess()['status'],'waiting_for_moderation')
    def test_wrong_parent_is_rejected(self):
        self.children[0]['parentProjectFileId']=99
        self.assertEqual(self.assess()['status'],'parent_link_not_confirmed')
    def test_another_server_pack_cannot_hide_generic_current_file(self):
        self.children.append(dict(self.server,id=13,parentProjectFileId=11))
        self.client.update(additionalFilesCount=2,additionalServerPackFilesCount=1)
        self.assertFalse(self.assess()['server_pack_classification_verified'])
    def test_public_file_identity_mismatch_fails_closed(self):
        self.server['fileLength']=999
        with self.assertRaises(release.Invalid):self.assess()
    def test_count_boolean_or_counter_mismatch_is_not_type_evidence(self):
        self.client['additionalServerPackFilesCount']=True
        self.assertFalse(self.assess()['server_pack_classification_verified'])

if __name__=='__main__':unittest.main()
