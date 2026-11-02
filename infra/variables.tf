variable "tenancy_ocid" {
  description = "OCI tenancy OCID. Keep credentials in a local, ignored terraform.tfvars file."
  type        = string
  sensitive   = true
}

variable "user_ocid" {
  description = "OCI user OCID used by the Terraform provider."
  type        = string
  sensitive   = true
}

variable "fingerprint" {
  description = "Fingerprint for the OCI API signing key."
  type        = string
  sensitive   = true
}

variable "private_key_path" {
  description = "Path to the OCI API signing key on the machine running Terraform."
  type        = string
  sensitive   = true
}

variable "region" {
  description = "OCI home region, for example ap-mumbai-1."
  type        = string
}

variable "compartment_id" {
  description = "Compartment OCID in which the VCN and instance will be created."
  type        = string
  sensitive   = true
}

variable "ubuntu_image_ocid" {
  description = "Region-specific Canonical Ubuntu 24.04 aarch64 image OCID. Pin this value for repeatable applies."
  type        = string
}

variable "ssh_public_key" {
  description = "Public SSH key installed for the default Ubuntu user. Never put a private key here."
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "Public IPv4 CIDR allowed to SSH to the VM, ideally your current IP followed by /32."
  type        = string
}

variable "instance_ocpus" {
  description = "OCPUs for the flexible Ampere A1 VM."
  type        = number
  default     = 2
}

variable "instance_memory_gbs" {
  description = "Memory in GB for the flexible Ampere A1 VM."
  type        = number
  default     = 12
}

variable "instance_boot_volume_gbs" {
  description = "Boot volume size in GB. Keep total block storage within the account's Always Free allowance."
  type        = number
  default     = 50
}

variable "fault_domain" {
  description = "Optional fault domain (FAULT-DOMAIN-1/2/3). Null lets OCI choose. Pin one only to work around per-fault-domain 'Out of host capacity'."
  type        = string
  default     = null
}

variable "instance_name" {
  description = "Display name for the single newsroom VM."
  type        = string
  default     = "autonomous-newsroom"
}
