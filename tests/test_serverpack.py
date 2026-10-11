"""Synthetic installer inputs; no MOD/runtime is executed."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import serverpack as s
import release

class ServerSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.client=Path(self.tmp.name)/'client.zip'
        self.server=Path(self.tmp.name)/'server.zip'
        self.manifest=b'{ "version": "synthetic-next", "files": [{"projectID":1,"fileID":10,"required":true},{"projectID":2,"fileID":20,"required":true}] }'
        self.config=b'enabled = true\n'
        with zipfile.ZipFile(self.client,'w') as z:
            z.writestr('manifest.json',self.manifest); z.writestr('modlist.html',b'<html>test</html>')
            z.writestr('overrides/config/example.toml',self.config)
            z.writestr('overrides/config/iris.properties',b'client=true')
        self.policy={'override_sha256':{'client':{
            'overrides/config/example.toml':hashlib.sha256(self.config).hexdigest(),
            'overrides/config/iris.properties':hashlib.sha256(b'client=true').hexdigest()}}}
        self.refs={'client':{1:{'projectID':1,'fileID':10,'required':True},2:{'projectID':2,'fileID':20,'required':True}},
                   'server':{1:{'projectID':1,'fileID':10,'required':True}}}
    def build(self):
        files=s.blobs(self.client,self.policy,self.refs,'synthetic-next')
        s.write_zip(self.server,files)
        return files,dict(schema_version=1,version='synthetic-next',client_sha256=s.sha(self.client),
            sha256=s.sha(self.server),size_bytes=self.server.stat().st_size,filename=self.server.name,
            format='manifest-installer-input')
    def test_unchanged_manifest_configs_no_jars_and_explicit_consent(self):
        files,receipt=self.build()
        self.assertEqual(files['manifest.json'],self.manifest)
        self.assertEqual(files['overrides/config/example.toml'],self.config)
        self.assertNotIn('overrides/config/iris.properties',files)
        self.assertFalse(any(n.endswith('.jar') for n in files))
        compose=files['compose.yaml'].decode()
        self.assertIn('CF_EXCLUDE_MODS: "2"',compose)
        self.assertIn('CF_FORCE_INCLUDE_MODS: "1"',compose)
        self.assertIn('${EULA:?',compose)
        self.assertNotIn('EULA: true',compose)
        self.assertIn('server-data:/data',compose)
        s.verify_prepared(self.server,receipt,self.client,self.policy,'synthetic-next',self.refs)
    def test_added_private_or_jar_entry_rejected_even_with_new_receipt_hash(self):
        _,receipt=self.build()
        with zipfile.ZipFile(self.server,'a') as z: z.writestr('secrets.env',b'not-real')
        receipt.update(sha256=s.sha(self.server),size_bytes=self.server.stat().st_size)
        with self.assertRaises(release.Invalid): s.verify_prepared(self.server,receipt,self.client,self.policy,'synthetic-next',self.refs)
    def test_changed_reviewed_config_rejected(self):
        self.policy['override_sha256']['client']['overrides/config/example.toml']='a'*64
        with self.assertRaises(release.Invalid): self.build()
    def test_deterministic_bytes(self):
        files,_=self.build(); other=Path(self.tmp.name)/'again.zip'; s.write_zip(other,files)
        self.assertEqual(s.sha(self.server),s.sha(other))

if __name__=='__main__': unittest.main()
