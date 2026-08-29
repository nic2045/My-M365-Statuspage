# Bootstraps the OpenBao access one requesting app needs: a policy scoped to
# exactly its own KV v2 secret path, plus a token carrying that policy.
#
# Run by the Cloud Operator only (needs VPN + an OpenBao admin/root token in
# VAULT_TOKEN - see README.md in this directory). Never run from CI: OpenBao
# is VPN-only and not continuously reachable, and the resulting token is a
# live credential that must be handed to the requester out of band, not
# printed into a pipeline log.

provider "vault" {
  # Address only - auth comes from the VAULT_TOKEN environment variable
  # (the operator's own privileged OpenBao token), never from a .tf file.
  address = var.openbao_address
}

locals {
  secret_path          = "${var.kv_mount}/data/${var.app_name}/${var.secret_name}"
  secret_metadata_path = "${var.kv_mount}/metadata/${var.app_name}/${var.secret_name}"
  policy_name          = "${var.app_name}-secret-access"
}

resource "vault_policy" "app" {
  name = local.policy_name

  policy = <<-EOT
    path "${local.secret_path}" {
      capabilities = ["create", "read", "update"]
    }
    path "${local.secret_metadata_path}" {
      capabilities = ["read"]
    }
  EOT
}

resource "vault_token" "app" {
  policies = [vault_policy.app.name]
  period = "${var.token_period_seconds}s"
  renewable = true
  no_default_policy = true

  metadata = {
    app_name         = var.app_name
    requested_by     = var.requested_by
    ticket_reference = var.ticket_reference
    managed_by       = "opentofu:infra/openbao"
  }
}
