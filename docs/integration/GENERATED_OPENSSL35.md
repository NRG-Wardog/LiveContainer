# Generated OpenSSL 3.5 LTS input

The host now selects `GeneratedDependencies/OpenSSL35/OpenSSL.xcframework`.
The historical `OpenSSL` gitlink is retained, but is no longer linked or searched
by this Xcode project. No bytes under that old dependency pin are replaced.

The source is official OpenSSL 3.5.9, SHA256
`603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a`.
The SAR `ci/issue53-lts/build_ios.py` recipe generates iOS arm64 and simulator
arm64/x86_64 with default and legacy providers built in (`no-module enable-legacy`),
iOS minimum 15.0, matching dSYMs and a complete generated-byte receipt.
`install_ios.py` verifies that receipt against the exact source and recipe before
materializing the dedicated path. Both recipe and generated receipt must be
bound by the candidate compiler-input/provenance manifest.

The former external vendor signature assertion belongs to the old downloaded
framework, not this source-built input. This generated input has no external
vendor signature claim. Existing application `CodeSignOnCopy` remains unchanged.
There is no signing-identity discovery or new trust-store entry.

The same source passed native macOS synthetic provider/PKCS12/real ZSign CMS
and both-order coexistence tests (SAR run 40221594188). That is not iOS execution
proof. iOS/simulator compile, package identity, and runtime evidence are separate
gates. Embedded SideStore crypto is not deduplicated or silently replaced by this
host-only project change.
