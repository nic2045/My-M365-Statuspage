terraform {
  required_version = ">= 1.6.0"

  required_providers {
    # OpenBao is API-compatible with HashiCorp Vault - the vault provider talks
    # to it unchanged, just pointed at OPENBAO_ADDR instead of a Vault server.
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
}
