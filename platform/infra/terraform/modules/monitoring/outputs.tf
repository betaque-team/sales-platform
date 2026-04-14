output "cpu_alarm_id" {
  description = "OCID of the CPU utilization alarm"
  value       = oci_monitoring_alarm.cpu_low.id
}

output "budget_id" {
  description = "OCID of the monthly budget"
  value       = var.budget_enabled ? oci_budget_budget.main[0].id : "disabled"
}

output "notification_topic_id" {
  description = "OCID of the notification topic"
  value       = oci_ons_notification_topic.alerts.id
}

output "keepalive_cron_line" {
  description = "Cron line to add to the VM for CPU keepalive"
  value       = var.keepalive_enabled ? "0 */6 * * * /opt/sales-platform/infra/scripts/keepalive.sh >> /var/log/keepalive.log 2>&1" : ""
}
