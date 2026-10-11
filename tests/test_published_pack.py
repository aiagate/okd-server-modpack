"""Immutable published bytes, pinned source and recovery failure cases. No real network."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import published_pack as p
import release


class PublishedPackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.c = self.root / 'okd-server-modpack-0.0.1.zip'; self.c.write_bytes(b'client')
        self.s = self.root / 'okd-server-modpack-0.0.1-serverpack.zip'; self.s.write_bytes(b'server')
        self.meta = {'version': '0.0.1', 'project_id': 1}
        self.inputs = (self.meta, {'client': {}, 'server': {}}, {}, 'a' * 64)
        self.cr = {'filename': self.c.name, 'sha256': hashlib.sha256(b'client').hexdigest()}
        self.sr = {'filename': self.s.name, 'sha256': hashlib.sha256(b'server').hexdigest()}
        self.record = dict(schema_version=1, repository=p.REPOSITORY, tag='v0.0.1',
            source_commit='b'*40, source_sha256='a'*64, client=self.cr, server=self.sr)
        self.provenance = json.dumps(self.record).encode()
        self.assets = [self.asset(1, self.c.name, b'client'), self.asset(2, self.s.name, b'server'),
            self.asset(3, 'github-release-receipt.json', self.provenance)]
        self.row = dict(id=10, tag_name='v0.0.1', draft=False, published_at='synthetic-date', assets=self.assets)
        self.ref = dict(ref='refs/tags/v0.0.1', object={'type': 'commit', 'sha': 'b'*40})
    def asset(self, ident, name, raw):
        return dict(id=ident, name=name, size=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest())
    def api(self, path, binary=False):
        if path.startswith('releases/tags/'): return json.dumps(self.row).encode()
        if path.startswith('git/ref/'): return json.dumps(self.ref).encode()
        if path == 'releases/assets/3': return self.provenance
        self.fail('unexpected network read '+path)
    def validate(self, record=None):
        with patch.object(p.native,'load_inputs',return_value=self.inputs), \
             patch.object(p,'source_inputs',return_value=self.inputs), \
             patch.object(p.native,'verify_client') as verify, \
             patch.object(p.serverpack,'verify_prepared'), \
             patch.object(p,'gh_api',side_effect=self.api):
            result=p.validate_receipt(record or self.record,self.c,self.cr,self.s,self.sr,published=True)
            verify.assert_called_once()
            return result
    def test_exact_release_pair_and_recorded_source_are_accepted(self):
        self.assertEqual(self.validate(),self.inputs)
    def test_retargeted_project_or_changed_version_refs_settings_stop(self):
        other=(dict(self.meta,project_id=2),self.inputs[1],self.inputs[2],'c'*64)
        with patch.object(p.native,'load_inputs',return_value=other),patch.object(p,'source_inputs',return_value=self.inputs), \
             patch.object(p,'gh_api') as api:
            with self.assertRaises(release.Invalid):p.validate_receipt(self.record,self.c,self.cr,self.s,self.sr,published=True)
            api.assert_not_called()
    def test_wrong_repository_version_and_receipt_digests_stop(self):
        for edit in ({'repository':'someone/another-pack'}, {'tag':'v9.9.9'}, {'source_sha256':'c'*64}, {'client':dict(self.cr,sha256='d'*64)}):
            with self.subTest(edit=edit),self.assertRaises(release.Invalid):self.validate(dict(self.record,**edit))
    def test_tag_moved_to_different_commit_is_rejected(self):
        self.ref['object']['sha']='c'*40
        with self.assertRaises(release.Invalid):self.validate()
    def test_draft_or_wrong_release_tag_is_rejected(self):
        for edit in ({'draft':True},{'tag_name':'v2.0.0'},{'published_at':None}):
            self.row.update(edit)
            with self.subTest(edit=edit),self.assertRaises(release.Invalid):self.validate()
            self.row.update(tag_name='v0.0.1',draft=False,published_at='synthetic-date')
    def test_mutated_zip_even_with_unchanged_receipt_is_rejected(self):
        self.c.write_bytes(b'changed client')
        with self.assertRaises(release.Invalid):self.validate()
    def test_changed_published_provenance_is_rejected(self):
        self.provenance=json.dumps(dict(self.record,source_commit='d'*40)).encode()
        self.assets[2]=self.asset(3,'github-release-receipt.json',self.provenance)
        with self.assertRaises(release.Invalid):self.validate()
    def test_missing_duplicate_and_digestless_assets_stop(self):
        for assets in ([],[self.assets[0],self.assets[0]],[dict(self.assets[0],digest=None)]):
            with self.subTest(assets=assets),self.assertRaises(release.Invalid):p.asset_by_name({'assets':assets},self.c.name)
    def test_corrupt_download_wrong_size_or_digest_is_rejected(self):
        for raw in (b'corrupt',b'client extra'):
            with patch.object(p,'gh_api',return_value=raw),self.assertRaises(release.Invalid):p.download_asset(self.assets[0],release.MAX_ZIP)
    def test_download_bounds_are_checked_before_network(self):
        with patch.object(p,'gh_api') as api,self.assertRaises(release.Invalid):p.download_asset(self.assets[0],1)
        api.assert_not_called()
    def test_no_rebuild_fallback_when_source_or_api_unavailable(self):
        with patch.object(p.native,'load_inputs',return_value=self.inputs),patch.object(p,'gh_api',side_effect=release.Invalid('unavailable')), \
             patch.object(p.native,'build') as build:
            with self.assertRaises(release.Invalid):p.acquire(self.root/'new-output')
            build.assert_not_called()
    def test_source_must_be_ancestor_and_regular_pack_tree(self):
        with patch.object(p,'git',side_effect=release.Invalid('not ancestor')),self.assertRaises(release.Invalid):p.source_inputs('b'*40)
        tree=b'120000 blob '+b'a'*40+b'\tpack/overrides/link\0'
        with patch.object(p,'git',side_effect=[b'',tree]),self.assertRaises(release.Invalid):p.source_inputs('b'*40)
    def test_new_build_refuses_existing_release_and_non404_errors(self):
        for response in (subprocess.CompletedProcess([],0,stderr=b''),subprocess.CompletedProcess([],1,stderr=b'network failure')):
            with patch.object(p.native,'load_inputs',return_value=self.inputs),patch.object(p.subprocess,'run',return_value=response), \
                 patch.object(p,'gh_api') as api,self.assertRaises(release.Invalid):p.require_new_version()
            api.assert_not_called()


if __name__=='__main__': unittest.main()
