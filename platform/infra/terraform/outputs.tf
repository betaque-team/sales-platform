# =============================================================================
# Root outputs — everything you need after terraform apply
# =============================================================================

output "instance_public_ip" {
  description = "Public IP of the Oracle Cloud VM"
  value       = module.compute.public_ip
}

output "ssh_command" {
  description = "SSH command to connect to the VM"
  value       = "ssh -i ${var.ssh_private_key_path} ubuntu@${module.compute.public_ip}"
}

output "app_url" {
  description = "Application URL"
  value       = "https://${var.app_domain}"
}

output "tunnel_id" {
  description = "Cloudflare Tunnel ID"
  value       = module.cloudflare.tunnel_id
}

output "cloud_init_progress" {
  description = "Command to check cloud-init bootstrap progress"
  value       = "ssh -i ${var.ssh_private_key_path} ubuntu@${module.compute.public_ip} 'sudo tail -f /var/log/cloud-init-output.log'"
}

output "instance_id" {
  description = "OCI compute instance OCID"
  value       = module.compute.instance_id
}

output "postgres_password" {
  description = "Generated Postgres password (save securely!)"
  value       = module.secrets.postgres_password
  sensitive   = true
}

output "jwt_secret" {
  description = "Generated JWT secret (save securely!)"
  value       = module.secrets.jwt_secret
  sensitive   = true
}

output "monitoring_summary" {
  description = "Monitoring resources created"
  value       = "CPU alarm: ${module.monitoring.cpu_alarm_id}, Budget: ${module.monitoring.budget_id}"
}

output "github_deploy_key_public" {
  description = <<-EOT
    ──────────────────────────────────────────────────────
    ACTION REQUIRED: Add this deploy key to your GitHub repo
    GitHub repo → Settings → Deploy keys → Add deploy key
    Title: sales-platform-vm  |  Access: Read-only
    ──────────────────────────────────────────────────────
  EOT
  value = module.secrets.github_deploy_key_public
}
