output "policy_name" {
  description = "Name of the created OpenBao policy."
  value       = vault_policy.app.name
}

output "secret_path" {
  description = "KV v2 path the issued token can read/write - set as OPENBAO_SECRET_PATH on the requesting app."
  value       = local.secret_path
}

output "app_token" {
  description = "The issued token - set as OPENBAO_TOKEN on the requesting app. Hand it to the requester over your org's normal secure channel (never via a CI log, a ticket comment, or Slack in plaintext); do not commit it. Retrieve with: tofu output -raw app_token"
  value       = vault_token.app.client_token
  sensitive   = true
}
