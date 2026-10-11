"""Synthetic source/exports; publication and compiler are mocked here."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import native_pack as n
import release

class NativePackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'pack';(self.root/'overrides/config').mkdir(parents=True)
        self.config=b'enabled = true\n';(self.root/'overrides/config/example.toml').write_bytes(self.config)
        self.meta={'schema_version':1,'version':'0.0.2','name':'Synthetic','author':'Tests',
            'minecraft_version':'1.21.1','loader_id':'neoforge-21.1.243','project_id':1,
            'game_version_names':['1.21.1','NeoForge','Client'],'release_type':'alpha'}
        self.refs=[{'projectID':1,'fileID':100,'required':True},{'projectID':2,'fileID':200,'required':True}]
        for kind,rows in [('client',self.refs),('server',self.refs[:1])]:
            (self.root/f'{kind}.refs.json').write_text(json.dumps({'files':rows}))
        self.migration={'schema_version':1,'module_version':n.MODULE,'go_version':n.GO_VERSION,
            'migration_version':'0.0.2','reference_sha256':{kind:n.digest(json.dumps({f['projectID']:f for f in rows},sort_keys=True).encode()) for kind,rows in [('client',self.refs),('server',self.refs[:1])]},'override_sha256':{'overrides/config/example.toml':n.digest(self.config)}}
        self.save()
    def save(self):
        (self.root/'release.json').write_text(json.dumps(self.meta))
        (self.root/'migration.json').write_text(json.dumps(self.migration))
    def export(self,change=None,extra=None):
        inputs=n.load_inputs(self.root)
        manifest={'name':'Synthetic','author':'Tests','version':'0.0.2','manifestType':'minecraftModpack',
            'manifestVersion':1,'overrides':'overrides','minecraft':{'version':'1.21.1',
            'modLoaders':[{'id':'neoforge-21.1.243','primary':True}]},'files':copy.deepcopy(self.refs)}
        if change: change(manifest)
        raw=self.root.parent/'raw.zip'
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('manifest.json',json.dumps(manifest));z.writestr('modlist.html','<ul>test</ul>')
            z.writestr('overrides/config/example.toml',self.config)
            for name,blob in (extra or {}).items():z.writestr(name,blob)
        out=self.root.parent/'client.zip';n.canonical_zip(raw,out)
        with zipfile.ZipFile(out) as z:
            receipt=dict(schema_version=1,exporter='packwiz',module_version=n.MODULE,version='0.0.2',
                source_sha256=inputs[3],sha256=n.digest(out.read_bytes()),size_bytes=out.stat().st_size,
                filename=out.name,manifest_sha256=n.digest(z.read('manifest.json')),modlist_sha256=n.digest(z.read('modlist.html')))
        return out,receipt,inputs
    def test_exact_refs_and_settings_roundtrip(self):
        client,receipt,inputs=self.export(); self.assertEqual(n.verify_client(client,receipt,inputs),receipt['sha256'])
    def test_changed_file_id_fails_even_with_fresh_zip_receipt_hash(self):
        client,receipt,inputs=self.export(lambda m:m['files'][0].update(fileID=999))
        with self.assertRaises(release.Invalid):n.verify_client(client,receipt,inputs)
    def test_secret_or_jar_cannot_enter_generated_client(self):
        client,receipt,inputs=self.export(extra={'overrides/mods/not-a-real.jar':b'test'})
        with self.assertRaises(release.Invalid):n.verify_client(client,receipt,inputs)
    def test_first_migration_changed_config_rejected(self):
        (self.root/'overrides/config/example.toml').write_bytes(b'enabled = false\n')
        with self.assertRaises(release.Invalid):n.load_inputs(self.root)
    def test_first_migration_changed_reference_rejected(self):
        (self.root/'client.refs.json').write_text(json.dumps({'files':[dict(self.refs[0],fileID=999),self.refs[1]]}))
        with self.assertRaises(release.Invalid):n.load_inputs(self.root)
    def test_initial_migration_client_only_reference_change_rejected(self):
        rows=copy.deepcopy(self.refs);rows[1]['fileID']=999
        (self.root/'client.refs.json').write_text(json.dumps({'files':rows}))
        with self.assertRaises(release.Invalid):n.load_inputs(self.root)
    def test_duplicate_reference_rejected_in_future_source(self):
        self.meta['version']='0.0.3';self.save()
        (self.root/'client.refs.json').write_text(json.dumps({'files':self.refs+[self.refs[0]]}))
        with self.assertRaises(release.Invalid):n.load_inputs(self.root)
    def test_future_update_uses_repository_source_not_app_gate(self):
        self.meta['version']='0.0.3';self.save()
        (self.root/'overrides/config/example.toml').write_bytes(b'enabled = false\n')
        self.assertEqual(n.load_inputs(self.root)[0]['version'],'0.0.3')
    def test_source_symlink_rejected_before_read(self):
        (self.root/'overrides/config/link.toml').symlink_to(self.root/'release.json')
        with self.assertRaises(release.Invalid):n.load_inputs(self.root)
    def test_repack_preserves_manifest_bytes_and_is_reproducible(self):
        client,_,_=self.export(); other=self.root.parent/'again.zip';n.canonical_zip(self.root.parent/'raw.zip',other)
        self.assertEqual(client.read_bytes(),other.read_bytes())
        with zipfile.ZipFile(client) as a,zipfile.ZipFile(self.root.parent/'raw.zip') as b:
            self.assertEqual(a.read('manifest.json'),b.read('manifest.json'))
    def compare_fixture(self,changed=False):
        a=self.root.parent/'a';b=self.root.parent/'b';a.mkdir();b.mkdir()
        for directory,reverse in ((a,False),(b,True)):
            for report in ('client','server'):
                (directory/f'{report}.json').write_text(json.dumps({'version':'0.0.2','filename':f'{report}.zip'}))
                with zipfile.ZipFile(directory/f'{report}.zip','w') as z:
                    rows=list(reversed(self.refs)) if reverse else self.refs
                    z.writestr('manifest.json',json.dumps({'files':rows,'version':'0.0.2'}))
                    z.writestr('modlist.html','b\na' if reverse else 'a\nb')
                    z.writestr('overrides/config/example.toml',b'changed' if changed and reverse else self.config)
        return a,b
    def test_independent_export_order_is_semantically_equal(self):
        n.compare_builds(*self.compare_fixture())
    def test_independent_changed_settings_rejected(self):
        with self.assertRaises(release.Invalid):n.compare_builds(*self.compare_fixture(changed=True))
    def test_builder_module_and_compiler_are_verified(self):
        raw=f'packwiz: go{n.GO_VERSION}\n\tmod\tgithub.com/packwiz/packwiz\t{n.MODULE}\t{n.MODULE_SUM}\n'
        with patch('subprocess.check_output',return_value=raw.encode()):n.verify_tool(Path('binary'))
        with patch('subprocess.check_output',return_value=raw.replace(n.MODULE,'other').encode()),self.assertRaises(release.Invalid):
            n.verify_tool(Path('binary'))
    def test_export_staging_has_fixed_ids_no_fabricated_download_hashes(self):
        meta,refs,overrides,_=n.load_inputs(self.root);stage=self.root.parent/'stage';stage.mkdir()
        n.stage(stage,meta,refs,overrides)
        text=(stage/'mods/2.pw.toml').read_text()
        self.assertIn('side = "client"',text);self.assertIn('file-id = 200',text)
        self.assertNotIn('[download]',text)
        self.assertEqual((stage/'config/example.toml').read_bytes(),self.config)

if __name__=='__main__':unittest.main()
