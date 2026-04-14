output "vcn_id" {
  description = "OCID of the VCN"
  value       = oci_core_vcn.main.id
}

output "subnet_id" {
  description = "OCID of the public subnet"
  value       = oci_core_subnet.main.id
}

output "security_list_id" {
  description = "OCID of the security list"
  value       = oci_core_security_list.main.id
}
