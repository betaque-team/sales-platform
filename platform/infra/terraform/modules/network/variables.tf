variable "compartment_id" {
  description = "OCI compartment OCID (or tenancy OCID for root compartment)"
  type        = string
}

variable "project_name" {
  description = "Project name used for resource naming and DNS labels"
  type        = string
  default     = "sales-platform"
}

variable "vcn_cidr" {
  description = "CIDR block for the VCN"
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block for the public subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "allowed_ingress_ports" {
  description = "TCP ports to allow inbound (default: SSH only)"
  type        = list(number)
  default     = [22]
}
