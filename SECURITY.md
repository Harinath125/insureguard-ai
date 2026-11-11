# Security notes

InsureGuard AI is a local demonstration prototype and is not hardened for production use.

- Do not expose the development server to the public internet.
- Do not upload confidential, personal or regulated insurance data.
- The role selector/header is not authentication.
- The rating-engine worker is a separate process, not a security-grade sandbox.
- Do not run untrusted uploaded code with this prototype.

If you discover a security issue in this repository, do not publish sensitive exploit details in a public issue. Contact the repository maintainer privately once a contact method has been added to the repository profile.
