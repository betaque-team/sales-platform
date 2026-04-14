output "tunnel_id" {
  description = "Cloudflare Tunnel ID"
  value       = cloudflare_zero_trust_tunnel_cloudflared.app.id
}

output "tunnel_token" {
  description = "Cloudflare Tunnel token for cloudflared connector"
  value       = cloudflare_zero_trust_tunnel_cloudflared.app.tunnel_token
  sensitive   = true
}

output "tunnel_cname" {
  description = "CNAME target for the tunnel"
  value       = "${cloudflare_zero_trust_tunnel_cloudflared.app.id}.cfargotunnel.com"
}

output "app_fqdn" {
  description = "Full domain name of the app"
  value       = var.domain
}

output "dns_record_id" {
  description = "Cloudflare DNS record ID"
  value       = cloudflare_record.tunnel_cname.id
}
