# Security and privacy

Location data can be highly sensitive. Treat this service as processing sensitive personal information even if the surrounding product has broader access.

## Data minimization

- Store only fields required for the product purpose.
- Do not persist full chat history just to support the MVP.
- Prefer upstream message IDs + bounded evidence over duplicate raw message storage where possible.
- If raw text must be stored, define retention and encryption policy.

## Access control

- Database access must follow least privilege.
- Administrative/review APIs must require authentication and authorization.
- Do not expose cross-conversation search by default.
- Future person/location lookup tools must enforce tenant/conversation boundaries.

## Logging

Never log by default:

- full message body;
- complete person-location pairs in plaintext;
- API keys/tokens;
- authorization headers.

Prefer:

- message id;
- conversation id if non-sensitive/opaque;
- text length;
- hashes;
- outcome enums;
- latency;
- extractor version;
- redacted evidence only when necessary.

## Provider boundary

When sending message text to an external LLM provider:

- make provider use explicit/configurable;
- document the data flow;
- send only the current message in MVP, not unnecessary history;
- avoid adding unrelated account/profile metadata;
- keep secrets in environment/secret manager;
- configure retention/privacy settings according to deployment requirements.

## Retention and deletion

Design records so data associated with a conversation/user can be deleted or reprocessed without orphaned hidden copies. Provenance must not become an excuse to retain data indefinitely.

## Encryption

- TLS in transit.
- Database/storage encryption at rest according to platform standards.
- If application-level encryption is required for message/evidence text, keep keys outside DB.

## Abuse considerations

Do not build hidden continuous tracking behavior into the extraction layer. The extractor processes authorized application inputs; collection, consent, retention, and product access rules belong to the surrounding system and must be explicit before production rollout.

## Test data

Use synthetic/anonymized examples. Do not copy production chats into fixtures without an approved sanitization process.
