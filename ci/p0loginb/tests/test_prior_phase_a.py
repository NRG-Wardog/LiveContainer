"""Isolated offline synthetic prechecks; no successful native run is asserted."""
import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
PLAN = HERE.parents[3]
spec = importlib.util.spec_from_file_location("phase_b_prior_test_subject", HERE.parent / "prior_phase_a.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
HOST = HERE.parent / "prior_adapter"
REVIEW = HOST
SOURCES = Path(os.environ["P0LOGINB_SOURCE_OBJECTS"]) if "P0LOGINB_SOURCE_OBJECTS" in os.environ else None
CAPTURE = Path(os.environ["P0LOGINB_PRIOR_CAPTURE"]) if "P0LOGINB_PRIOR_CAPTURE" in os.environ else None


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


class PriorPhaseATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p.require(SOURCES is not None and CAPTURE is not None,"explicit local source/evidence fixtures required via run_tests.py")
        cls.verifier, cls.gate, cls.data, cls.input_raw = p._load_trusted_adapter(
            HOST, p.INPUT_SHA256, REVIEW / "verify_phase_a_artifact.py", p.REFERENCE_VERIFIER_SHA256)
        cls.overlay = p.parse((REVIEW / "phase-a-overlay-manifest.json").read_bytes())
        cls.original_lock = cls.gate.git(SOURCES / "SideSign", "show",
            cls.data["owners"]["SideSign"]["commit"] + ":Package.resolved")
        cls.source_fixture = {}
        proof = {}
        for owner, row in cls.data["owners"].items():
            records = cls.gate.entries(SOURCES / owner, row["commit"])
            proof[owner] = {"commit": row["commit"], "tree": row["tree"],
                "tracked_entries": len(records), "gitlinks_unpopulated":
                    {name: entry[2] for name, entry in records.items() if entry[1] == "commit"},
                "status": "", "origin": {"kind": "direct", "repository": row["repository"]}}
        cls.source_fixture["provenance/source-before.json"] = encoded(proof)
        proof["SideSign"]["status"] = " M Package.resolved\n"
        cls.source_fixture["provenance/source-after.json"] = encoded(proof)
        ak = cls.data["owners"]["AnisetteKit"]["commit"]
        names = ("Native/Loader/elf_metadata_bounds.h", "Native/anisette_base.h",
                 "Native/include/anisette_core.h", ".ci/native-tests/fixtures/elf_metadata_bounds_unit.cpp")
        cls.source_fixture["metadata-units/result.json"] = encoded({"source_sha256":
            {name: p.sha(cls.gate.git(SOURCES / "AnisetteKit", "show", ak + ":" + name)) for name in names}})

    def expected(self):
        return {"repository": p.REPOSITORY, "run_id": 101, "run_attempt": 2,
            "host_commit": "a" * 40, "host_tree": self.overlay["prospective_approved_host_tree"],
            "artifact_id": 202, "artifact_sha256": "d" * 64, "artifact_size": 123,
            "lock_sha256": "e" * 64, "evidence_index_sha256": "f" * 64}

    def test_default_draft_contains_no_guessed_future_success_binding(self):
        prior = p.make_draft_prior()
        self.assertTrue(all(value is None for value in prior["expected"].values()))
        self.assertTrue(all(prior[key] is None for key in
            ("approved_inputs_sha256", "approved_overlay_sha256", "approved_verifier_sha256")))
        self.assertEqual(p.validate_prior_inputs(prior)["status"], "DRAFT_PRIOR_UNRESOLVED")
        self.assertFalse(p.validate_prior_inputs(prior)["execution_admitted"])
        with self.assertRaisesRegex(ValueError, "unresolved"):
            p.verify_prior_capture(prior, None, None, None, None)

    def test_explicit_adapter_metadata_does_not_fill_success_tuple(self):
        metadata = {"approved_inputs_sha256": p.INPUT_SHA256,
                    "approved_overlay_sha256": p.OVERLAY_SHA256,
                    "approved_verifier_sha256": p.REFERENCE_VERIFIER_SHA256}
        prior = p.make_draft_prior(metadata)
        p.validate_prior_inputs(prior)
        self.assertTrue(all(value is None for value in prior["expected"].values()))
        with self.assertRaises(ValueError):
            p.make_draft_prior({"approved_inputs_sha256": p.INPUT_SHA256})

    def test_even_complete_synthetic_tuple_cannot_disable_replay_guard(self):
        prior = p.make_draft_prior({"approved_inputs_sha256": p.INPUT_SHA256,
            "approved_overlay_sha256": p.OVERLAY_SHA256,
            "approved_verifier_sha256": p.REFERENCE_VERIFIER_SHA256})
        prior["expected"] = self.expected()
        p.validate_prior_inputs(prior)
        with self.assertRaisesRegex(ValueError, "execution replay review is unresolved"):
            p.verify_prior_capture(prior, None, None, None, None)
        prior["execution_replay_reviewed"] = True
        with self.assertRaisesRegex(ValueError, "schema"):
            p.validate_prior_inputs(prior)

    def test_partial_tuple_malformed_hashes_and_boolean_ids_reject(self):
        partial = p.make_draft_prior()
        partial["expected"]["run_id"] = 101
        with self.assertRaises(ValueError):
            p.validate_prior_inputs(partial)
        for key, value in (("run_attempt", True), ("run_id", 0), ("artifact_id", "202"),
                           ("host_commit", "main"), ("host_tree", "0" * 40),
                           ("lock_sha256", "0" * 64), ("repository", "attacker/LiveContainer")):
            expected = self.expected()
            expected[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                p._validate_expected(expected)

    def review_fixture(self):
        raw=(HOST/'independent-review.json').read_bytes();review=p.parse(raw)
        prior=p.make_draft_prior({"approved_inputs_sha256":p.INPUT_SHA256,"approved_overlay_sha256":p.OVERLAY_SHA256,"approved_verifier_sha256":p.REFERENCE_VERIFIER_SHA256})
        prior['expected']={key:review[key] for key in ('run_id','run_attempt','host_commit','host_tree','artifact_id','artifact_sha256','evidence_index_sha256')}
        prior['expected'].update(repository=p.REPOSITORY,artifact_size=557731,lock_sha256=review['sidesign_lock']['sha256'])
        prior['independent_review']={'receipt_sha256':p.sha(raw),'reviewer':'/root/diagnose_new_p0_initializer_failure/review_cxx_builder_admission'}
        return prior,review,raw

    def test_original_review_bytes_bind_without_synthesizing_attestation(self):
        prior,review,raw=self.review_fixture()
        self.assertEqual(p._validate_independent_review(raw,prior),review)
        self.assertNotIn('reviewer',review)
        with self.assertRaisesRegex(ValueError,'upload identity is unresolved'):p.validate_prior_inputs(prior,execution=True)
        prior['independent_review']=True
        with self.assertRaises(ValueError):p.validate_prior_inputs(prior)

    def test_review_digest_scope_tuple_and_required_evidence_counts_reject(self):
        changes=[lambda r:r.update(status='FAILED'),lambda r:r.update(run_attempt=2),lambda r:r.update(input_sha256='a'*64),
            lambda r:r.update(exact_ordered_top_level_commands=66),lambda r:r.update(guest_execution=True),
            lambda r:r['swift_tests']['AnisetteKit'].update(failed=1),lambda r:r['source_tracked_entries'].update(SideStore=1)]
        for index,change in enumerate(changes):
            prior,review,raw=self.review_fixture();change(review);raw=encoded(review);prior['independent_review']['receipt_sha256']=p.sha(raw)
            with self.subTest(index=index),self.assertRaises(ValueError):p._validate_independent_review(raw,prior)
        prior,review,raw=self.review_fixture()
        with self.assertRaisesRegex(ValueError,'receipt bytes changed'):p._validate_independent_review(raw+b'\n',prior)

    def test_archive_precheck_does_not_extract_or_execute_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            archive = root / "fixture.zip"
            code = b"raise RuntimeError('archive code must never execute')\n"
            files = {"untrusted.py": code}
            files["evidence-index.json"] = encoded({name: p.sha(raw) for name, raw in files.items()})
            with zipfile.ZipFile(archive, "w") as out:
                for name, raw in files.items():
                    out.writestr(name, raw)
            read, report = self.verifier.read_archive(archive)
            self.assertEqual(read, files)
            self.assertEqual(report["sha256"], p.sha(archive.read_bytes()))
            self.assertFalse((root / "untrusted.py").exists())

    def failed_evidence_fixture(self):
        identity = p._validate_api(self.verifier, *self.api_fixture())
        group = {"pgid": 321, "quiescent": True, "pipesJoined": True, "leaderReaped": True,
            "errors": [], "signals": [], "reapedBeforeSignals": True,
            "identityRetainedForSignals": False, "postReapPolicy": "read-only-group-disappearance"}
        result = {"status": "FAILED_OR_INCOMPLETE", "source_basis": self.data["source_basis"],
            "phase": "phase-a", "source_seal_sha256": self.data["source_seal_sha256"],
            "approved_inputs_sha256": p.sha(self.input_raw), "owners": self.data["owners"],
            "run": {key: identity[key] for key in ("repository", "run_id", "run_attempt", "host_commit", "host_tree")},
            "writers_quiescent": True, "production_ready": False, "ipa_built": False,
            "guest_execution": False, "real_ADI_executed": False, "device_validation": False,
            "app_typechecked": False}
        files = {"provenance/result.json": encoded(result), "provenance/reviewed-inputs.json": self.input_raw,
            "provenance/owned-command-groups.json": encoded([dict(group, label="synthetic")]),
            "logs/synthetic.command.json": encoded({"argv": ["synthetic-not-executed"], "cwd": "/synthetic"}),
            "logs/synthetic.settlement.json": encoded({"ownedProcessGroup": group, "returncode": 1}),
            "logs/synthetic.log": b"synthetic", "logs/synthetic.stderr.log": b"",
            "logs/synthetic.exit-code.txt": b"1\n"}
        return self.reindex(files), identity

    def reindex(self, files):
        files["evidence-index.json"] = encoded({name: p.sha(raw) for name, raw in files.items()
                                                if name != "evidence-index.json"})
        return files

    def test_complete_index_settled_writers_and_false_complete_claim_reject(self):
        for mutation in ("unindexed", "changed", "unsettled", "false-complete"):
            files, identity = self.failed_evidence_fixture()
            if mutation == "unindexed":
                files["extra"] = b"unindexed"
            elif mutation == "changed":
                files["logs/synthetic.log"] = b"corrupted"
            else:
                result = p.parse(files["provenance/result.json"])
                if mutation == "unsettled":
                    result["writers_quiescent"] = False
                else:
                    result["status"] = "CAPTURED_FOR_REVIEW"
                files["provenance/result.json"] = encoded(result)
                self.reindex(files)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.verifier.evidence(files, self.gate, self.data, self.input_raw, identity, SOURCES)

    def test_failed_capture_precheck_never_reports_admission_or_complete_capture(self):
        files, identity = self.failed_evidence_fixture()
        report = self.verifier.evidence(files, self.gate, self.data, self.input_raw, identity, SOURCES)
        self.assertFalse(report["complete_capture"])
        self.assertFalse(report["admission_granted"])
        self.assertFalse(report["independent_command_source_replay_performed"])
        self.assertEqual(report["verification_scope"], "TRANSPORT_AND_SCHEMA_PRECHECK_ONLY")

    def test_duplicate_json_and_unsafe_local_paths_reject(self):
        with self.assertRaises(ValueError):
            p.parse(b'{"same":1,"same":2}')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "file").write_bytes(b"data")
            (root / "link").symlink_to(root / "file")
            for name in ("../file", "/file", "x//file", "x\\file", "x:file", "link"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    p._ordinary(root, name)

    def test_frozen_import_is_private_and_does_not_use_existing_gate_modules(self):
        sentinels = {name: types.ModuleType("poisoned_" + name)
                     for name in ("native_gate", "source_primitives", "inventory", "lifecycle")}
        before_path = list(sys.path)
        before_flag = sys.dont_write_bytecode
        with mock.patch.dict(sys.modules, sentinels):
            verifier, gate, data, raw = p._load_trusted_adapter(
                HOST, p.INPUT_SHA256, REVIEW / "verify_phase_a_artifact.py", p.REFERENCE_VERIFIER_SHA256)
            self.assertIsNot(gate, sentinels["native_gate"])
            self.assertEqual(data, self.data)
            self.assertEqual(raw, self.input_raw)
            self.assertIsNot(gate.primitives, sentinels["source_primitives"])
            for key, sentinel in sentinels.items():
                self.assertIs(sys.modules[key], sentinel)
            self.assertIsNotNone(verifier.evidence)
        self.assertEqual(sys.path, before_path)
        self.assertEqual(sys.dont_write_bytecode, before_flag)

    def test_unapproved_adapter_bytes_are_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Path(directory).resolve() / "host"
            shutil.copytree(HOST, host)
            sentinel = Path(directory).resolve() / "executed"
            target = host / "ci/p0login/native_gate.py"
            target.write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").touch()\n")
            with self.assertRaisesRegex(ValueError, "frozen adapter bytes changed"):
                p._load_trusted_adapter(host, p.INPUT_SHA256,
                    REVIEW / "verify_phase_a_artifact.py", p.REFERENCE_VERIFIER_SHA256)
            self.assertFalse(sentinel.exists())

    def test_unapproved_verifier_bytes_are_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory).resolve() / "executed"
            verifier = Path(directory).resolve() / "verifier.py"
            verifier.write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").touch()\n")
            with self.assertRaisesRegex(ValueError, "frozen verifier bytes changed"):
                p._load_trusted_adapter(HOST, p.INPUT_SHA256, verifier, p.REFERENCE_VERIFIER_SHA256)
            self.assertFalse(sentinel.exists())

    def test_adapter_extra_file_wrong_input_and_symlink_reject(self):
        with self.assertRaises(ValueError):
            p._load_trusted_adapter(HOST, "a" * 64,
                REVIEW / "verify_phase_a_artifact.py", p.REFERENCE_VERIFIER_SHA256)
        with tempfile.TemporaryDirectory() as directory:
            host = Path(directory).resolve() / "host"
            shutil.copytree(HOST, host)
            extra = host / "ci/p0login/unapproved.py"
            extra.write_text("raise RuntimeError('must not execute')\n")
            with self.assertRaisesRegex(ValueError, "extra or missing"):
                p._load_trusted_adapter(host, p.INPUT_SHA256,
                    REVIEW / "verify_phase_a_artifact.py", p.REFERENCE_VERIFIER_SHA256)
            extra.unlink()
            target = host / "ci/p0login/native_gate.py"
            target.unlink()
            target.symlink_to(HOST / "ci/p0login/native_gate.py")
            with self.assertRaisesRegex(ValueError, "linked"):
                p._load_trusted_adapter(host, p.INPUT_SHA256,
                    REVIEW / "verify_phase_a_artifact.py", p.REFERENCE_VERIFIER_SHA256)

    def api_fixture(self):
        expected = self.expected()
        run = {"id": 101, "run_attempt": 2, "head_sha": expected["host_commit"],
            "repository": {"full_name": p.REPOSITORY}, "head_branch": self.verifier.BRANCH,
            "status": "completed", "event": "push", "path": self.verifier.WORKFLOW,
            "html_url": "https://github.com/" + p.REPOSITORY + "/actions/runs/101", "conclusion": "success"}
        artifact = {"id": 202, "expired": False,
            "url": "https://api.github.com/repos/" + p.REPOSITORY + "/actions/artifacts/202",
            "name": "p0-login-trace-phase-a-" + expected["host_commit"] + "-101-2",
            "workflow_run": {"id": 101, "head_sha": expected["host_commit"], "head_branch": self.verifier.BRANCH},
            "size_in_bytes": 123, "digest": "sha256:" + expected["artifact_sha256"]}
        commit = {"sha": expected["host_commit"],
            "parents": [{"sha": self.overlay["required_single_parent"]}],
            "tree": {"sha": expected["host_tree"]}}
        upload = {"GITHUB_REPOSITORY": p.REPOSITORY, "GITHUB_SHA": expected["host_commit"],
            "GITHUB_RUN_ID": "101", "GITHUB_RUN_ATTEMPT": "2", "CAPTURE_ARTIFACT_ID": "202",
            "CAPTURE_ARTIFACT_URL": run["html_url"] + "/artifacts/202",
            "CAPTURE_ARTIFACT_DIGEST": expected["artifact_sha256"]}
        archive = {"sha256": expected["artifact_sha256"], "bytes": 123}
        return [run, artifact, commit, upload, copy.deepcopy(self.overlay), archive, expected]

    def test_synthetic_api_tuple_precheck_is_exact(self):
        actual = p._validate_api(self.verifier, *self.api_fixture())
        self.assertEqual(actual["run_attempt"], 2)
        self.assertEqual(actual["workflow_conclusion"], "success")

    def test_failed_pending_attempt_zip_digest_and_host_corruption_reject(self):
        changes = [lambda a: a[0].update(conclusion="failure"),
            lambda a: a[0].update(status="in_progress"), lambda a: a[0].update(run_attempt=3),
            lambda a: a[0].update(run_attempt=True), lambda a: a[1].update(expired=True),
            lambda a: a[1].update(digest="sha256:" + "e" * 64),
            lambda a: a[2]["parents"][0].update(sha="b" * 40),
            lambda a: a[2]["tree"].update(sha="c" * 40),
            lambda a: a[3].update(CAPTURE_ARTIFACT_ID="203"),
            lambda a: a[5].update(bytes=124), lambda a: a[6].update(run_id=999),
            lambda a: a[6].update(host_commit="b" * 40)]
        for index, change in enumerate(changes):
            args = self.api_fixture()
            change(args)
            with self.subTest(index=index), self.assertRaises(ValueError):
                p._validate_api(self.verifier, *args)

    def transport_fixture(self):
        import retrieve_prior as helper
        current={'repository':p.REPOSITORY,'run_id':303,'run_attempt':4,'host_commit':'b'*40}
        environment={'GITHUB_REPOSITORY':p.REPOSITORY,'GITHUB_RUN_ID':'303','GITHUB_RUN_ATTEMPT':'4','GITHUB_SHA':'b'*40,'GITHUB_REF':p.PHASE_B_REF}
        raw={name:('synthetic-'+name).encode() for name in p.RECEIPT_FILES}
        fixed=HERE.parent/'retrieve_prior.py';inputs=HERE.parent/'inputs-phase-b.json';work=HERE.parent;out=HERE
        inputs_raw=inputs.read_bytes();urls=helper.endpoints(self.expected())
        report={'schema_version':1,'status':'RETRIEVED_UNSETTLED','execution_admitted':False,'current_run':current,'expected':self.expected(),
            'inputs':{'path':str(inputs),'sha256':p.sha(inputs_raw),'bytes':len(inputs_raw)},
            'helper':{'path':str(fixed),'sha256':p.sha(fixed.read_bytes()),'bytes':fixed.stat().st_size,'pid':500,'pgid':500},
            'limits':{'total_seconds':helper.TOTAL_SECONDS,'request_seconds':helper.REQUEST_SECONDS,'json_bytes':helper.MAX_JSON,'archive_bytes':helper.MAX_ARCHIVE,'header_bytes':helper.MAX_HEADERS,'stderr_bytes':helper.MAX_STDERR},
            'request_order':list(urls),'requests':{}}
        for key,url in urls.items():
            report['requests'][key]={'method':'GET','url':url,'status':200,'sha256':p.sha(raw[key]),'bytes':len(raw[key]),'headers':{},
                'stdout':{'sha256':p.sha(b'HTTP headers'+raw[key]),'bytes':len(raw[key])+12},'stderr':{'sha256':p.sha(b''),'bytes':0},
                'command':{'argv':['gh','api','--method','GET','--include',url],'cwd':str(out),'returncode':0,'pid':501,'pgid':500,'leaderReaped':True,'pipesJoined':True}}
        receipts={'schema_version':1,'current_run':current,'helper_report_sha256':p.sha(encoded(report)),
            'outer_command':{'argv':[sys.executable,'-B',str(fixed),'--inputs',str(inputs),'--output-dir',str(out)],'cwd':str(work),'environment':{}},
            'outer_settlement':{'returncode':0,'terminationReturncode':0,'ownedProcessGroup':{'pgid':500,'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[],'signals':[],'reapedBeforeSignals':True,'postReapPolicy':'read-only-group-disappearance'}}}
        kwargs={'helper_raw':encoded(report),'inputs_path':inputs,'inputs_raw':inputs_raw,'work_root':work,'receipts_dir':out}
        return current,receipts,raw,environment,kwargs,report

    def test_current_transport_precheck_binds_outer_helper_and_body_hashes(self):
        current,receipts,raw,environment,kwargs,report=self.transport_fixture()
        with mock.patch.dict(os.environ,environment):self.assertEqual(len(p._validate_current_transport(current,receipts,raw,self.expected(),**kwargs)),64)

    def test_current_environment_attempt_or_branch_substitution_rejects(self):
        for name,value in (('GITHUB_RUN_ID','304'),('GITHUB_RUN_ATTEMPT','5'),('GITHUB_SHA','c'*40),('GITHUB_REF','refs/heads/main'),('GITHUB_REPOSITORY','attacker/LiveContainer')):
            current,receipts,raw,environment,kwargs,report=self.transport_fixture();environment[name]=value
            with self.subTest(name=name),mock.patch.dict(os.environ,environment),self.assertRaises(ValueError):p._validate_current_transport(current,receipts,raw,self.expected(),**kwargs)

    def test_outer_command_identity_settlement_and_helper_substitution_reject(self):
        changes=[lambda r:r['outer_settlement'].update(returncode=False),lambda r:r['outer_settlement'].update(terminationReturncode=False),lambda r:r['outer_settlement']['ownedProcessGroup'].update(signals=[15],reapedBeforeSignals=False),lambda r:r['outer_command'].update(argv=['arbitrary']),lambda r:r['outer_command'].update(cwd='/other'),
            lambda r:r['outer_settlement'].update(returncode=1),lambda r:r['outer_settlement']['ownedProcessGroup'].update(quiescent=False),
            lambda r:r['outer_settlement']['ownedProcessGroup'].update(pgid=999),lambda r:r.update(helper_report_sha256='f'*64),
            lambda r:r['outer_command']['environment'].update(GH_TOKEN='must-not-retain')]
        for index,change in enumerate(changes):
            current,receipts,raw,environment,kwargs,report=self.transport_fixture();change(receipts)
            with self.subTest(index=index),mock.patch.dict(os.environ,environment),self.assertRaises(ValueError):p._validate_current_transport(current,receipts,raw,self.expected(),**kwargs)

    def test_nested_endpoint_order_stream_and_owned_group_substitution_reject(self):
        changes=[lambda r:r['requests']['run_api']['stderr'].update(bytes=1,sha256=p.sha(b'x')),lambda r:r['requests']['run_api']['stdout'].update(bytes=1),lambda r:r['requests']['run_api']['stderr'].update(bytes=False),lambda r:r['requests']['run_api'].update(method='POST'),lambda r:r['requests']['run_api'].update(url='https://attacker.invalid'),
            lambda r:r['requests']['run_api'].update(sha256='f'*64),lambda r:r['requests']['run_api'].update(bytes=1),
            lambda r:r['requests']['run_api']['command'].update(returncode=1),lambda r:r['requests']['run_api']['command'].update(pgid=777),
            lambda r:r['requests']['run_api']['command'].update(pipesJoined=False),lambda r:r['requests']['run_api']['command'].update(argv=['gh','api','POST']),
            lambda r:r['requests'].pop('archive'),lambda r:r['request_order'].reverse(),lambda r:r['helper'].update(sha256='f'*64),
            lambda r:r['inputs'].update(sha256='e'*64),lambda r:r['requests']['run_api']['headers'].update(location='signed'),
            lambda r:r['requests']['run_api']['stderr'].update(bytes=999999)]
        for index,change in enumerate(changes):
            current,receipts,raw,environment,kwargs,report=self.transport_fixture();change(report);kwargs['helper_raw']=encoded(report);receipts['helper_report_sha256']=p.sha(kwargs['helper_raw'])
            with self.subTest(index=index),mock.patch.dict(os.environ,environment),self.assertRaises(ValueError):p._validate_current_transport(current,receipts,raw,self.expected(),**kwargs)

    def test_source_receipts_recompute_actual_immutable_objects(self):
        p._validate_source_receipts(self.source_fixture, self.gate, self.data, SOURCES)

    def test_source_count_gitlink_origin_status_and_metadata_corruption_reject(self):
        changes = [lambda proof: proof["SideSign"].update(tracked_entries=1),
            lambda proof: proof["LiveContainer"].update(gitlinks_unpopulated={}),
            lambda proof: proof["AnisetteKit"].update(origin={"kind": "direct", "repository": "https://attacker.invalid/"}),
            lambda proof: proof["SideSign"].update(status=" M Package.swift\n"),
            lambda proof: proof["SideStore"].update(tree="c" * 40),
            lambda proof: proof.pop("SideStore")]
        for index, change in enumerate(changes):
            files = dict(self.source_fixture)
            proof = p.parse(files["provenance/source-before.json"])
            change(proof)
            files["provenance/source-before.json"] = encoded(proof)
            with self.subTest(index=index), self.assertRaises(ValueError):
                p._validate_source_receipts(files, self.gate, self.data, SOURCES)
        files = dict(self.source_fixture)
        metadata = p.parse(files["metadata-units/result.json"])
        metadata["source_sha256"][next(iter(metadata["source_sha256"]))] = "f" * 64
        files["metadata-units/result.json"] = encoded(metadata)
        with self.assertRaisesRegex(ValueError, "metadata test source bytes differ"):
            p._validate_source_receipts(files, self.gate, self.data, SOURCES)

    def test_anisette_terminal_lock_must_equal_observed_bytes(self):
        files = dict(self.source_fixture)
        files["provenance/AnisetteKit.Package.resolved.observed"] = b"synthetic-observed"
        files["provenance/AnisetteKit.Package.resolved.final-observed"] = b"changed"
        with self.assertRaises(ValueError):
            p._validate_source_receipts(files, self.gate, self.data, SOURCES)

    def lock_fixture(self):
        # These bytes are manufactured only to exercise comparisons in memory.
        # They are never a real resolver capture or input to a descendant commit.
        lock = p.parse(self.original_lock)
        lock["originHash"] = "9" * 64
        for index, pin in enumerate(lock["pins"]):
            if pin["identity"] == "anisettekit":
                lock["pins"][index] = {"identity": "anisettekit", "kind": "remoteSourceControl",
                    "location": "https://github.com/NRG-Wardog/AnisetteKit.git",
                    "state": {"revision": self.data["owners"]["AnisetteKit"]["commit"]}}
        after = encoded(lock)
        checked = self.gate.check_lock(self.original_lock, after, self.data["owners"]["AnisetteKit"]["commit"])
        files = {"provenance/SideSign.Package.resolved.before": self.original_lock,
            "provenance/SideSign.Package.resolved.after": after,
            "provenance/SideSign.Package.resolved.final-observed": after,
            "provenance/result.json": encoded({"resolved_lock": checked})}
        expected = self.expected()
        expected["lock_sha256"] = p.sha(after)
        return files, expected

    def test_lock_precheck_returns_exact_in_memory_bytes(self):
        files, expected = self.lock_fixture()
        actual = p._validate_lock(files, self.gate, self.data, SOURCES, expected)
        self.assertEqual(actual, files["provenance/SideSign.Package.resolved.after"])

    def test_missing_partial_wrong_original_terminal_and_approved_lock_reject(self):
        changes = [lambda f, e: f.pop("provenance/SideSign.Package.resolved.after"),
            lambda f, e: f.update({"provenance/SideSign.Package.resolved.before": b"{}"}),
            lambda f, e: f.update({"provenance/SideSign.Package.resolved.final-observed": b"{}"}),
            lambda f, e: e.update(lock_sha256="a" * 64),
            lambda f, e: f.update({"provenance/result.json": encoded({"resolved_lock": {}})})]
        for index, change in enumerate(changes):
            files, expected = self.lock_fixture()
            change(files, expected)
            with self.subTest(index=index), self.assertRaises(ValueError):
                p._validate_lock(files, self.gate, self.data, SOURCES, expected)

    def test_non_anisette_pin_and_missing_origin_hash_reject_even_if_digest_refreshed(self):
        for mutation in ("unrelated", "origin", "anisette"):
            files, expected = self.lock_fixture()
            lock = p.parse(files["provenance/SideSign.Package.resolved.after"])
            if mutation == "origin":
                lock.pop("originHash")
            else:
                pin = next(pin for pin in lock["pins"]
                    if (pin["identity"] == "anisettekit") == (mutation == "anisette"))
                pin["state"]["revision"] = "c" * 40
            raw = encoded(lock)
            files["provenance/SideSign.Package.resolved.after"] = raw
            files["provenance/SideSign.Package.resolved.final-observed"] = raw
            expected["lock_sha256"] = p.sha(raw)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                p._validate_lock(files, self.gate, self.data, SOURCES, expected)

    def test_actual_success_artifact_and_original_review_precheck_without_live_transport(self):
        # The transport seam is explicitly mocked; this test is local evidence
        # parsing only, never a claim that current-run authenticated retrieval ran.
        prior,review,raw=self.review_fixture()
        prior['upload_identity_sha256']=p.sha((HOST/'upload-identity.json').read_bytes())
        capture=CAPTURE
        with tempfile.TemporaryDirectory() as t:
            receipts=Path(t).resolve()
            for name,source in {'run-api.json':'run.json','artifact-api.json':'artifact.json','commit-api.json':'host-commit.json','artifact.zip':'artifact.zip'}.items():
                shutil.copyfile(capture/source,receipts/name)
            for name in ('upload-identity.json','independent-review.json'):shutil.copyfile(HOST/name,receipts/name)
            (receipts/'retrieval-receipts.json').write_bytes(b'{}');(receipts/'retrieval-helper.json').write_bytes(b'{}')
            current={'repository':p.REPOSITORY,'run_id':303,'run_attempt':1,'host_commit':'b'*40}
            roots={name:SOURCES/name for name in ('AnisetteKit','SideSign','SideStore','LiveContainer')}
            with mock.patch.object(p,'_validate_current_transport',return_value='f'*64) as seam:
                result=p.verify_prior_capture(prior,receipts,HOST,roots,current,inputs_path=HERE.parent/'inputs-phase-b.json',inputs_raw=b'local-test-only',work_root=receipts)
            seam.assert_called_once()
            self.assertEqual(p.sha(result['lock_bytes']),prior['expected']['lock_sha256'])
            self.assertFalse(result['report']['execution_admitted'])
            self.assertEqual(result['report']['prerequisite_scope'],'EXACT_PHASE_B_LOCK_INPUT_ONLY')
            self.assertEqual(result['report']['independent_review_sha256'],prior['independent_review']['receipt_sha256'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
