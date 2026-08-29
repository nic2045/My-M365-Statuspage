# OpenBao bootstrap (OpenTofu)

Issues one app's OpenBao access in one `tofu apply`: a policy scoped to exactly that
app's own KV v2 secret path, plus a token carrying that policy. Built for the
Azure-client-secret flow in [`docs/azure-secret-openbao.md`](../../docs/azure-secret-openbao.md)
(PR #150), but the module is generic - `app_name`/`secret_name` work for any app that
needs one OpenBao-backed secret with the same read/write-your-own-path shape.

## Who does what

- **Anforderer (requester):** opens an issue with
  [`.github/ISSUE_TEMPLATE/openbao-secret-request.yml`](../../.github/ISSUE_TEMPLATE/openbao-secret-request.yml) -
  fills in app name, which secret, and why. That's their one manual step.
- **Cloud Operator:** the only one who runs this module - needs VPN connectivity to
  `secrets-prod.pyur.com` and an OpenBao token with rights to create policies and
  tokens (an admin/root token, not the app's own eventual token). Copies the issue's
  fields into `terraform.tfvars`, runs `tofu apply` (their approval gate - review the
  plan before confirming), then hands the output token to the requester over your
  org's normal secure channel. That is the entire manual surface once this module and
  the issue form exist - no hand-written `bao policy write`/`bao token create` calls.

## Usage

```bash
cd infra/openbao
cp terraform.tfvars.example terraform.tfvars   # fill in from the requester's issue
export VAULT_ADDR=https://secrets-prod.pyur.com   # same as openbao_address default
export VAULT_TOKEN=<your own privileged OpenBao token>   # never put this in a file
tofu init
tofu plan   # review before applying - this is the approval step
tofu apply
tofu output -raw app_token   # hand this to the requester out of band; never log it
```

Give the requester `tofu output -raw app_token` as `OPENBAO_TOKEN`, and
`tofu output secret_path` as `OPENBAO_SECRET_PATH`, on their app.

## Prerequisites this module does NOT set up

- The `secret` KV v2 mount itself (`bao secrets enable -path=secret -version=2 kv`) -
  one-time, whole-instance setup, out of scope for a per-app bootstrap. If it's not
  enabled yet, `tofu apply` fails with a clear "no handler for route" error from
  OpenBao - enable the mount once, then re-run.
- Your own privileged `VAULT_TOKEN` - this module creates OTHER apps' tokens, it
  doesn't create yours.

## Known limitations (read before relying on this)

- **State holds the live token in plaintext** (`vault_token.app.client_token`, marked
  `sensitive` in Terraform/OpenTofu's own output but NOT encrypted at rest in state).
  Local state (the default if you don't configure a `backend` block) is fine for a
  one-off bootstrap run from a throwaway checkout, but do **not** commit `*.tfstate`
  (already gitignored) and do not leave it lying around on a shared machine. For
  repeated use, configure a remote backend with encryption at rest (e.g. an Azure
  Storage container with encryption enabled, if this org already uses one for other
  Terraform/OpenTofu state) rather than local files.
- **No self-renewal today.** The issued token is periodic (renewable via
  `bao token renew` within each `token_period_seconds` window), but the app this
  bootstraps doesn't call that itself yet - see `app/openbao_client.py` in the main
  repo. In practice, re-run `tofu apply` with the same `terraform.tfvars` before the
  period lapses to reissue a fresh token (OpenTofu will show a diff only on the token,
  the policy stays unchanged). Put a reminder on whatever cadence matches
  `token_period_seconds` (2592000s / 30 days by default).
- **One token per app, not per environment.** If an app needs separate dev/prod
  OpenBao access, run this module twice with different `app_name` values (e.g.
  `m365-statuspage-dev`, `m365-statuspage-prod`) rather than sharing one token.
