variable "openbao_address" {
  description = "Base URL of the OpenBao instance. Only reachable over VPN."
  type        = string
  default     = "https://secrets-prod.pyur.com"
}

variable "kv_mount" {
  description = "KV v2 secrets engine mount OpenBao's Cloud Operator has already enabled (see ../../docs or README below) - this module only manages a policy + token scoped under it, never the mount itself."
  type        = string
  default     = "secret"
}

# ── Per-request fields (fill in from the Anforderer/requester issue form -
# see ../../.github/ISSUE_TEMPLATE/openbao-secret-request.yml) ────────────────

variable "app_name" {
  description = "Short, unique, DNS-safe name for the requesting app/team - becomes the policy name and part of the secret path. Example: m365-statuspage"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.app_name))
    error_message = "app_name must be lowercase alphanumeric with dashes only (used as a policy name and URL path segment)."
  }
}

variable "secret_name" {
  description = "Name of the specific secret under the app's own path prefix. Example: azure-client-secret. Full KV v2 path becomes {kv_mount}/data/{app_name}/{secret_name}."
  type        = string
  default     = "azure-client-secret"
}

variable "requested_by" {
  description = "Who/which team requested this (from the issue form) - stored as token metadata for audit, not used in the policy itself."
  type        = string
}

variable "ticket_reference" {
  description = "Issue/ticket URL or number this request came from - stored as token metadata for audit."
  type        = string
  default     = ""
}

variable "token_period_seconds" {
  description = "Renewal period for the issued token (a periodic token, renewable indefinitely via `bao token renew` within each window - but the app this module bootstraps does not self-renew today, so in practice this is the token's actual lifetime: re-run `tofu apply` before it lapses to reissue. 2592000s = 30 days by default; the README's Cloud-Operator checklist covers reissuing it."
  type        = number
  default     = 2592000 # 720h
}
