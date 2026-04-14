terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
  }
}

# --- Notification topic for alarms ---
resource "oci_ons_notification_topic" "alerts" {
  compartment_id = var.compartment_id
  name           = "${var.project_name}-alerts"
  description    = "Alerts for ${var.project_name} (CPU, budget)"
}

# --- Email subscription (if alert_email provided) ---
resource "oci_ons_subscription" "email" {
  count          = var.alert_email != "" ? 1 : 0
  compartment_id = var.compartment_id
  topic_id       = oci_ons_notification_topic.alerts.id
  protocol       = "EMAIL"
  endpoint       = var.alert_email
}

# --- CPU utilization alarm (warns BEFORE Oracle reclaims) ---
resource "oci_monitoring_alarm" "cpu_low" {
  compartment_id        = var.compartment_id
  display_name          = "${var.project_name}-cpu-low"
  is_enabled            = true
  metric_compartment_id = var.compartment_id
  namespace             = "oci_computeagent"
  severity              = "CRITICAL"

  query = "CpuUtilization[1h]{resourceId = \"${var.instance_id}\"}.mean() < ${var.cpu_alarm_threshold}"

  body = <<-EOT
    WARNING: ${var.project_name} instance CPU utilization is below ${var.cpu_alarm_threshold}%.
    Oracle reclaims Always Free instances with <10% CPU over 7 days.
    The keepalive cron should prevent this, but check that it's running:
      ssh into the VM and run: crontab -l | grep keepalive
    If missing, re-add: 0 */6 * * * /opt/sales-platform/infra/scripts/keepalive.sh
  EOT

  destinations = [oci_ons_notification_topic.alerts.id]

  # Repeat every 6 hours while condition persists
  repeat_notification_duration = "PT6H"
  pending_duration             = "PT5M"
}

# --- Budget alert (catch any unexpected charges) ---
# Requires IAM budget policy — set budget_enabled = false to skip
resource "oci_budget_budget" "main" {
  count          = var.budget_enabled ? 1 : 0
  compartment_id = var.compartment_id
  amount         = var.budget_amount
  reset_period   = "MONTHLY"
  display_name   = "${var.project_name}-budget"
  description    = "Free tier budget guard for ${var.project_name}"
  target_type    = "COMPARTMENT"
  targets        = [var.compartment_id]
}

resource "oci_budget_alert_rule" "overspend" {
  count          = var.budget_enabled ? 1 : 0
  budget_id      = oci_budget_budget.main[0].id
  display_name   = "${var.project_name}-overspend-alert"
  type           = "FORECAST"
  threshold      = 100
  threshold_type = "PERCENTAGE"
  message        = "ALERT: ${var.project_name} is forecasted to exceed the $${var.budget_amount} monthly budget. Check for non-free-tier resources."
  recipients     = var.alert_email
}
