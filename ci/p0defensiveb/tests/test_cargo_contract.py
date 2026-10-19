"""Synthetic offline contract tests only; never run Cargo, Rust, Xcode or sources."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import cargo_contract as c
import native_build as native


class CargoContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'cargo-home'
        self.target = self.base / 'cargo-target'
        self.install = self.base / 'cargo-tools'
        self.rustup = self.base / 'rustup-home'
        self.env = {'CARGO_HOME': str(self.home), 'CARGO_TARGET_DIR': str(self.target),
                    'CARGO_INSTALL_ROOT': str(self.install), 'RUSTUP_HOME': str(self.rustup),
                    'RUSTUP_TOOLCHAIN': '1.98.1-aarch64-apple-darwin', 'PATH': '/synthetic'}

    def validate(self, **kw):
        return c.validate_cargo_home(self.home, self.target, self.install, cwd=self.base,
                                     env=self.env, rustup_home=self.rustup, **kw)

    def test_roots_must_be_fresh_and_isolated(self):
        self.assertTrue(self.validate(before_setup=True)['fresh_checked'])
        self.home.mkdir()
        self.validate()
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.validate(before_setup=True)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            c.validate_cargo_home(self.home, self.home / 'target', self.install)
        self.rustup.symlink_to(self.home, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.validate()

    def test_directory_alias_is_rejected_even_when_target_is_fresh(self):
        real = self.base / 'real'
        real.mkdir()
        alias = self.base / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked'):
            c.validate_cargo_home(alias/'cargo',self.target,self.install,before_setup=True)

    def test_native_environment_and_commands_have_no_ambient_overrides(self):
        base = dict(self.env, HOME=str(self.base), DEVELOPER_DIR=native.TOOLCHAIN['developer_dir'],
                    RUSTC_WRAPPER='unreviewed',CARGO_BUILD_TARGET='unreviewed',RUSTFLAGS='unreviewed',
                    OPENSSL_DIR='/foreign',OPENSSL_INCLUDE_DIR='/foreign/include',OPENSSL_LIB_DIR='/foreign/lib',
                    CC='/foreign/cc',DYLD_INSERT_LIBRARIES='/foreign/library',PKG_CONFIG_LIBDIR='/foreign/lib/pkgconfig',
                    PKG_CONFIG_PATH='/foreign',BINDGEN_EXTRA_CLANG_ARGS='unreviewed')
        env = native.native_environment(self.base,base)
        for key in ('RUSTC_WRAPPER','CARGO_BUILD_TARGET','RUSTFLAGS','OPENSSL_DIR','CC',
                    'DYLD_INSERT_LIBRARIES','PKG_CONFIG_PATH','BINDGEN_EXTRA_CLANG_ARGS','OPENSSL_INCLUDE_DIR',
                    'OPENSSL_LIB_DIR','PKG_CONFIG_LIBDIR'):
            self.assertNotIn(key,env)
        self.assertEqual(env['RUSTUP_TOOLCHAIN'],native.RUST_TOOLCHAIN)
        self.assertEqual(env['RUSTUP_HOME'],str(self.rustup))
        command = native.cargo_metadata_command(Path('/synthetic/rustup'),Path('/synthetic/idevice'))
        self.assertEqual(command[:4],[Path('/synthetic/rustup'),'run',native.RUST_TOOLCHAIN,'cargo'])
        self.assertIn('--locked',command)
        self.assertIn('--offline',command)
        self.assertEqual(command[-4:],['--features','obfuscate','--filter-platform','aarch64-apple-ios'])
        self.assertNotIn('--no-deps',command)

    def test_host_openssl_overrides_are_rejected_before_ios_transport(self):
        class Candidate(native.NativeBuildMixin):
            pass
        candidate=Candidate()
        candidate.work=self.base
        candidate.native_env=dict(self.env)
        self.home.mkdir()
        candidate.check_cargo_storage()
        for key in native.HOST_OPENSSL_OVERRIDES:
            candidate.native_env[key]='/synthetic/Homebrew/Cellar/openssl@3/3.6.5'
            with self.assertRaisesRegex(ValueError,'must not enter the iOS'):
                candidate.check_cargo_storage()
            del candidate.native_env[key]

    def test_config_in_cargo_home_or_command_ancestor_is_rejected(self):
        self.home.mkdir()
        for path in (self.home / 'config', self.home / 'config.toml',
                     self.base / '.cargo/config', self.base / '.cargo/config.toml'):
            path.parent.mkdir(exist_ok=True)
            path.write_text('[source.crates-io]\nreplace-with="foreign"\n')
            with self.assertRaisesRegex(ValueError, 'config'):
                self.validate()
            path.unlink()

    def test_ambient_overrides_and_moving_toolchain_are_rejected(self):
        self.home.mkdir()
        for key in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTFLAGS',
                    'CARGO_ENCODED_RUSTFLAGS', 'CARGO_BUILD_RUSTC', 'CARGO_SOURCE_CRATES_IO_REPLACE_WITH',
                    'RUSTUP_DIST_SERVER', 'SCCACHE_BUCKET'):
            self.env[key] = 'unreviewed'
            with self.assertRaisesRegex(ValueError, 'environment'):
                self.validate()
            del self.env[key]
        for value in ('stable', 'nightly', '1.98.1', '1.98.1-x86_64-apple-darwin'):
            self.env['RUSTUP_TOOLCHAIN'] = value
            with self.assertRaisesRegex(ValueError, 'exact Rust'):
                self.validate()
        self.env['RUSTUP_TOOLCHAIN'] = '1.98.1-aarch64-apple-darwin'
        self.env['RUSTUP_HOME'] = '/warm/rustup'
        with self.assertRaisesRegex(ValueError, 'storage'):
            self.validate()

    def registry_fixture(self, name='fake', version='1.0.0'):
        self.home.mkdir(exist_ok=True)
        dirname=name+'-'+version
        root = self.home / 'registry/src/index' / dirname
        root.mkdir(parents=True)
        files = {'Cargo.toml': ('[package]\nname='+json.dumps(name)+'\nversion='+json.dumps(version)+'\n').encode(),
                 'src/lib.rs': b'// synthetic input, never executed\n'}
        archive = self.home / 'registry/cache/index' / (dirname+'.crate')
        archive.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive, 'w:gz') as tar:
            for relative, raw in files.items():
                info = tarfile.TarInfo(dirname+'/' + relative)
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        (root / '.cargo-ok').write_text('{"v":1}')
        return {'name': name, 'version': version, 'source': c.REGISTRY,
                'id': 'opaque-'+name, 'manifest_path': str(root / 'Cargo.toml')}, c.sha(archive.read_bytes())

    def test_registry_source_is_verified_from_locked_archive(self):
        package, checksum = self.registry_fixture()
        result = c.registry_source(package, self.home, checksum)
        self.assertEqual(set(result['source_files']), {'Cargo.toml', 'src/lib.rs'})
        self.assertEqual(result['archive_sha256'], checksum)
        with self.assertRaisesRegex(ValueError, 'archive differs'):
            c.registry_source(package, self.home, '0' * 64)
        root = Path(package['manifest_path']).parent
        (root / 'src/lib.rs').write_text('mutated after build')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            c.registry_source(package, self.home, checksum)

    def test_registry_escaping_paths_extra_files_and_symlinks_fail(self):
        package, checksum = self.registry_fixture()
        root = Path(package['manifest_path']).parent
        (root / 'extra.rs').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            c.registry_source(package, self.home, checksum)
        (root / 'extra.rs').unlink()
        (root / 'link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'linked'):
            c.registry_source(package, self.home, checksum)
        (root / 'link').unlink()
        package['manifest_path'] = str(self.base / 'elsewhere/Cargo.toml')
        Path(package['manifest_path']).parent.mkdir()
        Path(package['manifest_path']).write_text('fake')
        with self.assertRaisesRegex(ValueError, 'escaped'):
            c.registry_source(package, self.home, checksum)

    def metadata_fixture(self):
        package, checksum = self.registry_fixture()
        roots = {'idevice': self.base / 'sources/idevice', 'jktcp': self.base / 'sources/jktcp'}
        packages, ids, nodes, lock = [], {}, [], 'version = 4\n'
        for name, (owner, path, version) in c.LOCAL_MANIFESTS.items():
            manifest = roots[owner] / path
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text('[package]\nname=' + json.dumps(name) + '\nversion=' + json.dumps(version) + '\n')
            identifier = 'opaque-local-' + name
            ids[name] = identifier
            packages.append({'id': identifier, 'name': name, 'version': version, 'source': None,
                             'manifest_path': str(manifest)})
            nodes.append({'id': identifier, 'features': ['aws-lc','obfuscate'], 'dependencies': [], 'deps': []})
            lock += '\n[[package]]\nname=' + json.dumps(name) + '\nversion=' + json.dumps(version) + '\n'
        for source, dest in (('idevice-ffi', 'idevice'), ('idevice', 'jktcp')):
            node = next(n for n in nodes if n['id'] == ids[source])
            node['dependencies'].append(ids[dest])
            node['deps'].append({'name': dest, 'pkg': ids[dest], 'dep_kinds': [{'kind': None, 'target': None}]})
        nodes.append({'id': package['id'], 'features': [], 'dependencies': [], 'deps': []})
        packages.append(package)
        lock += '\n[[package]]\nname="fake"\nversion="1.0.0"\nsource=' + json.dumps(c.REGISTRY) + '\nchecksum=' + json.dumps(checksum) + '\n'
        for name,version in (('aws-lc-rs','1.16.2'),('aws-lc-sys','0.39.0')):
            extra,checksum=self.registry_fixture(name,version)
            packages.append(extra)
            ids[name]=extra['id']
            nodes.append({'id':extra['id'],'features':[],'dependencies':[],'deps':[]})
            lock+='\n[[package]]\nname='+json.dumps(name)+'\nversion='+json.dumps(version)+'\nsource='+json.dumps(c.REGISTRY)+'\nchecksum='+json.dumps(checksum)+'\n'
        for source,dest in (('idevice','aws-lc-rs'),('aws-lc-rs','aws-lc-sys')):
            node=next(n for n in nodes if n['id']==ids[source])
            node['dependencies'].append(ids[dest])
            node['deps'].append({'name':dest.replace('-','_'),'pkg':ids[dest],'dep_kinds':[{'kind':None,'target':None}]})
        (roots['idevice'] / 'Cargo.lock').write_text(lock)
        data = {'version': 1, 'workspace_root': str(roots['idevice']), 'target_directory': str(self.target),
                'workspace_members': [ids[n] for n in c.LOCAL_MANIFESTS if n != 'jktcp'], 'packages': packages,
                'resolve': {'root': ids['idevice-ffi'], 'nodes': nodes}}
        return roots, data

    def test_real_metadata_contract_accepts_complete_synthetic_shape_only(self):
        roots, data = self.metadata_fixture()
        with mock.patch.object(c, 'source_inputs', return_value={'synthetic': True}):
            result = c.verify_cargo_metadata(json.dumps(data), roots, self.home, self.target)
        self.assertEqual(set(result['local_packages']), set(c.LOCAL_MANIFESTS))
        self.assertEqual(set(result['registry_packages']), {'opaque-fake','opaque-aws-lc-rs','opaque-aws-lc-sys'})
        self.assertFalse(result['transport_features']['active_openssl'])

    def test_metadata_rejects_source_pin_workspace_feature_and_edge_drift(self):
        roots, data = self.metadata_fixture()
        changes = (
            lambda d: d.update(workspace_root='/other'),
            lambda d: d.update(target_directory='/warm'),
            lambda d: d.update(resolve=None),
            lambda d: d['resolve'].update(root='opaque-local-idevice-tools'),
            lambda d: d['workspace_members'].append('opaque-local-jktcp'),
            lambda d: d['packages'][0].update(manifest_path='/other/Cargo.toml'),
            lambda d: d['packages'][-1].update(source='git+https://example.invalid/repo'),
            lambda d: d['packages'][-1].update(version='2.0.0'),
            lambda d: d['packages'].append(copy.deepcopy(d['packages'][0])),
            lambda d: d['resolve']['nodes'][0].update(features=[]),
            lambda d: d['resolve']['nodes'][1].update(dependencies=[]),
            lambda d: d['resolve']['nodes'][0].update(deps=[]),
            lambda d: d['resolve']['nodes'][0]['dependencies'].append('missing-id'),
        )
        with mock.patch.object(c, 'source_inputs', return_value={'synthetic': True}):
            for change in changes:
                altered = copy.deepcopy(data)
                change(altered)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    c.verify_cargo_metadata(altered, roots, self.home, self.target)

    def test_optional_openssl_is_allowed_but_active_transport_openssl_is_rejected(self):
        roots,data=self.metadata_fixture()
        package,checksum=self.registry_fixture('openssl-sys','0.9.112')
        lock=roots['idevice']/'Cargo.lock'
        lock.write_text(lock.read_text()+'\n[[package]]\nname="openssl-sys"\nversion="0.9.112"\nsource='+json.dumps(c.REGISTRY)+'\nchecksum='+json.dumps(checksum)+'\n')
        data['packages'].append(package)
        with mock.patch.object(c,'source_inputs',return_value={'synthetic':True}):
            # An optional locked package may appear in package inventory while
            # absent from the active resolve graph. That is not consumption.
            c.verify_cargo_metadata(data,roots,self.home,self.target)
            data['resolve']['nodes'].append({'id':package['id'],'features':[],'dependencies':[],'deps':[]})
            core=next(n for n in data['resolve']['nodes'] if n['id']=='opaque-local-idevice')
            core['dependencies'].append(package['id'])
            edge={'name':'openssl_sys','pkg':package['id'],'dep_kinds':[{'kind':'dev','target':None}]}
            core['deps'].append(edge)
            c.verify_cargo_metadata(data,roots,self.home,self.target)
            for kind in (None,'build'):
                edge['dep_kinds'][0]['kind']=kind
                with self.assertRaisesRegex(ValueError,'active OpenSSL transport edge'):
                    c.verify_cargo_metadata(data,roots,self.home,self.target)

    def test_transport_requires_reachable_aws_lc_and_classified_edges(self):
        roots,data=self.metadata_fixture()
        core=next(n for n in data['resolve']['nodes'] if n['id']=='opaque-local-idevice')
        core['dependencies'].remove('opaque-aws-lc-rs')
        core['deps']=[d for d in core['deps'] if d['pkg']!='opaque-aws-lc-rs']
        with mock.patch.object(c,'source_inputs',return_value={'synthetic':True}):
            with self.assertRaisesRegex(ValueError,'dependency closure missing'):
                c.verify_cargo_metadata(data,roots,self.home,self.target)
            core['deps'][0]['dep_kinds']=[{'target':None}]
            with self.assertRaisesRegex(ValueError,'unclassified'):
                c.verify_cargo_metadata(data,roots,self.home,self.target)

    def test_source_inputs_rejects_lock_or_local_path_mutation(self):
        roots, data = self.metadata_fixture()
        core = roots['idevice'] / 'idevice/Cargo.toml'
        core.write_text(core.read_text() + '\n[dependencies]\njktcp={path="../../jktcp", optional=true, default-features=false}\n')
        (roots['jktcp'] / 'Cargo.lock').write_text('version=4\n')
        blobs, records = {}, {}
        for owner in roots:
            blobs[owner], records[owner] = {}, {}
            for path in roots[owner].rglob('*'):
                if path.is_file():
                    raw = path.read_bytes()
                    name = str(path.relative_to(roots[owner]))
                    oid = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
                    blobs[owner][name] = oid
                    records[owner][name] = ('100644', 'blob', oid)
        def fake_git(root, *args):
            owner = Path(root).name
            return (c.NATIVE_TUPLES[owner][1 if args[-1] == 'HEAD^{tree}' else 0] + '\n').encode()
        with mock.patch.object(c, 'SOURCE_BLOBS', blobs), mock.patch.object(c, 'git', side_effect=fake_git), \
             mock.patch.object(c, 'entries', side_effect=lambda root, commit: records[Path(root).name]), \
             mock.patch.object(c, 'verify_checkout', return_value={'synthetic': True}):
            c.source_inputs(roots)
            core.write_text(core.read_text().replace('../../jktcp', '../../other'))
            with self.assertRaisesRegex(ValueError, 'worktree changed'):
                c.source_inputs(roots)

    def test_bindgen_must_be_fresh_explicit_install_and_exact_version(self):
        (self.install / 'bin').mkdir(parents=True)
        (self.install / 'bin/bindgen').write_bytes(b'synthetic non-executable binary')
        key = 'bindgen-cli 0.72.1 (' + c.REGISTRY + ')'
        receipt = self.install / '.crates2.json'
        receipt.write_text(json.dumps({'installs': {key: {'bins': ['bindgen']}}}))
        c.verify_bindgen_install(self.install, 'bindgen 0.72.1\n')
        with self.assertRaisesRegex(ValueError, 'exact bindgen'):
            c.verify_bindgen_install(self.install, 'bindgen 0.72.0')
        receipt.write_text(json.dumps({'installs': {key: {'bins': ['other']}}}))
        with self.assertRaisesRegex(ValueError, 'installation'):
            c.verify_bindgen_install(self.install, 'bindgen 0.72.1')

    def test_openssl_preserves_real_formula_and_cellar_version(self):
        real = self.base / 'homebrew/Cellar/openssl@3/3.6.5'
        (real / 'bin').mkdir(parents=True)
        (real / 'bin/openssl').write_bytes(b'synthetic non-executable binary')
        opt = self.base / 'homebrew/opt/openssl@3'
        opt.parent.mkdir()
        opt.symlink_to(real, target_is_directory=True)
        info = {'formulae': [{'name': 'openssl@3', 'installed': [{'version': '3.6.5', 'poured_from_bottle': True}]}]}
        output = 'OpenSSL 3.6.5 1 Oct 2026\nsynthetic test version output\n'
        result = c.verify_openssl_provenance(info, opt, output, expected_version='3.6.5')
        self.assertEqual(result['real_prefix'], str(real))
        with self.assertRaisesRegex(ValueError, 'version'):
            c.verify_openssl_provenance(info, opt, output, expected_version='3.6.4')
        with self.assertRaisesRegex(ValueError, 'executable version'):
            c.verify_openssl_provenance(info, opt, output.replace('3.6.5', '3.6.4'))
        info['formulae'][0]['installed'].append({'version': '3.6.4'})
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            c.verify_openssl_provenance(info, opt, output)


if __name__ == '__main__':
    unittest.main()
