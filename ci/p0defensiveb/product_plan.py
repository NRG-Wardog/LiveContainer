"""Concrete unsigned product commands and retention contract, without execution.

The executable machinery reuses proven NativeBuildMixin with one isolated-environment
injection. Authentic Phase A bytes, source descendants and exact independent
input/overlay approval remain required before any execution side effect.
"""
from pathlib import Path
from native_build import app_commands, cargo_metadata_command, rust_command, RUST_TOOLCHAIN
from inventory import require

SANDBOX = '(version 1) (allow default) (deny network*)'
RETENTION = {
    'before': ['actual-source-git-trees-modes-origins','actual-commit-and-tree-objects','committed-manifests-and-locks',
        'actual-compiler-launchers-and-resolved-executables','selected-sdk','prior-authenticated-original-api-and-zip-bytes'],
    'consumer_nested_each_command': ['argv-cwd-finite-environment','raw-stdout-stderr','exit-timeout-result',
        'temporary-compiler-input-tree-before','temporary-compiler-output-tree-after'],
    'before_after_app_build': ['actual-xcode-workspace-state','actual-package-checkout-trees-and-origins',
        'actual-package-binary-archives-and-framework-trees','genuine-sidestore-lock','cargo-metadata-and-locked-source-graph',
        'compiler-generated-derived-data-inputs','complete-product-inventory'],
    'terminal': ['source-git-trees-and-cleanliness','SideSign-lock','SideStore-lock','toolchain-identity',
        'compiler-input-product-bytes','compiled-resource-results','owned-command-settlement','complete-evidence-index'],
}


def fixed_commands(adapter, roots, work, evidence, python='python3'):
    """Review template uses only named roots; never shell interpolation or execution."""
    require(set(roots) >= {'SideStore','LiveContainer','AnisetteKit','idevice'}, 'required command roots missing')
    adapter, work, evidence = map(Path,(adapter,work,evidence))
    roots = {name:Path(path) for name,path in roots.items()}
    consumer = [python,'-B',adapter/'run_consumer_tests.py','--root',roots['SideStore'],
        '--peer',roots['LiveContainer'],'--producer',roots['AnisetteKit'],
        '--output',evidence/'provenance/consumer-tests.json',
        '--observer-dir',evidence/'consumer-nested','--temporary',work/'consumer-temporary',
        '--remaining-budget-json',evidence/'provenance/consumer-budget.json']
    commands = [
        ('consumer-network-denial-probe',['/usr/bin/sandbox-exec','-p',SANDBOX,python,'-c',
            'import errno,socket\ns=socket.socket(); e=s.connect_ex(("127.0.0.1",9)); s.close()\nif e not in (errno.EPERM,errno.EACCES):raise SystemExit("network sandbox did not deny")']),
        ('consumer-exact38',['/usr/bin/sandbox-exec','-p',SANDBOX,*consumer]),
        *app_commands(roots,work),
    ]
    return [{'label':label,'argv':[str(value) for value in argv],'cwd':str(work),
             'timeout_seconds':120 if label.endswith('probe') else 1800 if label=='consumer-exact38' else 3600}
            for label,argv in commands]


def contract():
    roots={owner:Path('/REVIEWED/SOURCES')/owner for owner in ('SideStore','LiveContainer','AnisetteKit','idevice')}
    return {'schema_version':1,'status':'EXECUTABLE_ADAPTER_PENDING_GENUINE_BINDINGS','capture_deadline_seconds':7200,
        'workflow_deadline_minutes':150,'owned_group_settlement_required':True,
        'commands':fixed_commands(Path('/REVIEWED/HOST/ci/p0defensiveb'),roots,Path('/FRESH/WORK'),Path('/FRESH/EVIDENCE')),
        'native_product_implementation':'native_build.NativeBuildMixin',
        'native_prerequisites_and_transport':'retry5 product machinery with isolated base-environment injection; locked Cargo/Rustup and generated-header transition',
        'retention_checkpoints':RETENTION,'consumer_tests':38,'consumer_skips_permitted':0,
        'new_code_signing_allowed':False,'inherited_exact_signature_inventory_retained':True,
        'internal_sidebackup_resource_allowed':True,'distribution_ipa_allowed':False,
        'engine_or_provider_execution_allowed':False,'credentials_allowed':False,
        'missing_execution_integration':[],
        'pending_authentic_bindings':['genuine-reviewed-Phase-A-artifact-and-lock','published-SideSign-lock-only-child',
            'published-SideStore-gitlink-only-input','independent-complete-input-and-host-overlay-review']}
