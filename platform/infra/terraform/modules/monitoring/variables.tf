variable "compartment_id" {
  description = "OCI compartment OCID"
  type        = string
}

variable "instance_id" {
  description = "OCID of the compute instance to monitor"
  type        = string
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "sales-platform"
}

variable "alert_email" {
  description = "Email for alarm and budget notifications"
  type        = string
  default     = ""
}

variable "cpu_alarm_threshold" {
  description = "CPU utilization % below which alarm fires (Oracle reclaims at <10% for 7d)"
  type        = number
  default     = 15
}

variable "budget_amount" {
  description = "Monthly budget in USD (alerts if forecast exceeds this)"
  type        = number
  default     = 1
}

variable "keepalive_enabled" {
  description = "Whether to include CPU keepalive cron in recommendations"
  type        = bool
  default     = true
}

variable "budget_enabled" {
  description = "Whether to create budget resources (requires IAM budget policy)"
  type        = bool
  default     = true
}
