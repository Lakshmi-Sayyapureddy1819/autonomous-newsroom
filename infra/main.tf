data "oci_identity_availability_domains" "home_region" {
  compartment_id = var.tenancy_ocid
}

resource "oci_core_vcn" "newsroom" {
  compartment_id = var.compartment_id
  cidr_blocks    = ["10.42.0.0/16"]
  display_name   = "newsroom-vcn"
  dns_label      = "newsroom"
}

resource "oci_core_internet_gateway" "newsroom" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.newsroom.id
  display_name   = "newsroom-internet-gateway"
  enabled        = true
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.newsroom.id
  display_name   = "newsroom-public-routes"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.newsroom.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.newsroom.id
  display_name   = "newsroom-public-security"

  ingress_security_rules {
    protocol    = "6"
    source      = var.ssh_allowed_cidr
    source_type = "CIDR_BLOCK"
    stateless   = false
    tcp_options {
      min = 22
      max = 22
    }
  }

  dynamic "ingress_security_rules" {
    for_each = toset([80, 443])
    content {
      protocol    = "6"
      source      = "0.0.0.0/0"
      source_type = "CIDR_BLOCK"
      stateless   = false
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }

  egress_security_rules {
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
    protocol         = "all"
    stateless        = false
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.newsroom.id
  cidr_block                 = "10.42.1.0/24"
  display_name               = "newsroom-public-subnet"
  dns_label                  = "public"
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.public.id]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_instance" "newsroom" {
  compartment_id      = var.compartment_id
  availability_domain = data.oci_identity_availability_domains.home_region.availability_domains[0].name
  display_name        = var.instance_name
  fault_domain        = var.fault_domain
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  create_vnic_details {
    assign_public_ip = true
    subnet_id        = oci_core_subnet.public.id
    display_name     = "newsroom-primary-vnic"
  }

  source_details {
    source_type             = "image"
    source_id               = var.ubuntu_image_ocid
    boot_volume_size_in_gbs = var.instance_boot_volume_gbs
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  freeform_tags = {
    Project   = "autonomous-newsroom"
    ManagedBy = "terraform"
  }
}

data "oci_core_vnic_attachments" "newsroom" {
  compartment_id = var.compartment_id
  instance_id    = oci_core_instance.newsroom.id
}

data "oci_core_vnic" "newsroom" {
  vnic_id = data.oci_core_vnic_attachments.newsroom.vnic_attachments[0].vnic_id
}
