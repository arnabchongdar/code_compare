############################################################
# variables.tf — Input variables for DR failover Terraform
############################################################

# ----------------------------------------------------------
# Your base domain name (must already exist in Route53 or
# will be created as a public hosted zone)
# ----------------------------------------------------------
variable "domain_name" {
  description = "The DNS domain name to use for failover setup."
  type        = string
  default     = "mydrdemo.com"
}

# ----------------------------------------------------------
# Primary region (active)
# ----------------------------------------------------------
variable "primary_region" {
  description = "Primary AWS region for Lambda and API Gateway."
  type        = string
  default     = "us-east-1"
}

# ----------------------------------------------------------
# Secondary region (disaster recovery)
# ----------------------------------------------------------
variable "secondary_region" {
  description = "Secondary AWS region for Lambda and API Gateway."
  type        = string
  default     = "us-east-2"
}

# ----------------------------------------------------------
# Lambda function names
# ----------------------------------------------------------
variable "primary_lambda_name" {
  description = "Name of the primary Lambda function."
  type        = string
  default     = "dr-primary"
}

variable "secondary_lambda_name" {
  description = "Name of the secondary Lambda function."
  type        = string
  default     = "dr-secondary"
}

# ----------------------------------------------------------
# API Gateway names
# ----------------------------------------------------------
variable "primary_api_name" {
  description = "Name of the primary API Gateway."
  type        = string
  default     = "dr-primary-api"
}

variable "secondary_api_name" {
  description = "Name of the secondary API Gateway."
  type        = string
  default     = "dr-secondary-api"
}

# ----------------------------------------------------------
# Health check settings
# ----------------------------------------------------------
variable "health_check_interval" {
  description = "Interval (seconds) between Route53 health checks."
  type        = number
  default     = 30
}

variable "health_check_failure_threshold" {
  description = "Number of failed checks before Route53 marks endpoint unhealthy."
  type        = number
  default     = 3
}

# ----------------------------------------------------------
# Tags
# ----------------------------------------------------------
variable "tags" {
  description = "Common tags applied to all resources."
  type        = map(string)
  default = {
    Project     = "AWS-DR-Failover"
    Environment = "Production"
    ManagedBy   = "Terraform"
  }
}
