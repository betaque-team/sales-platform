output "postgres_password" {
  description = "Postgres password (auto-generated or user-provided)"
  value       = local.postgres_password
  sensitive   = true
}

output "jwt_secret" {
  description = "JWT signing secret (auto-generated or user-provided)"
  value       = local.jwt_secret
  sensitive   = true
}

# Public key: add this to GitHub repo → Settings → Deploy keys (read-only)
output "github_deploy_key_public" {
  description = "GitHub deploy key public key — add to repo Settings > Deploy keys"
  value       = tls_private_key.github_deploy.public_key_openssh
}

# Private key: injected into VM via cloud-init. Never written to local disk.
output "github_deploy_key_private" {
  description = "GitHub deploy key private key (sensitive — VM only)"
  value       = tls_private_key.github_deploy.private_key_openssh
  sensitive   = true
}
