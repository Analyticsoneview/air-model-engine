variable "aws_region" {
  description = "AWS region for this dedicated AIR deployment."
  type        = string
}

variable "environment_name" {
  description = "Short lowercase name used to namespace AWS resources."
  type        = string
  default     = "air-private"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.environment_name))
    error_message = "environment_name must be 3-21 lowercase letters, digits or hyphens and start with a letter."
  }
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.50.0.0/24", "10.50.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "AIR private AWS deployment requires two public subnets in separate AZs."
  }
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.50.10.0/24", "10.50.11.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) == 2
    error_message = "AIR private AWS deployment requires two private subnets in separate AZs."
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.50.0.0/16"
}

variable "postgres_engine_version" {
  type    = string
  default = "16.4"
}

variable "postgres_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "postgres_allocated_storage" {
  type    = number
  default = 50
}

variable "postgres_multi_az" {
  type    = bool
  default = true
}

variable "postgres_deletion_protection" {
  type    = bool
  default = true
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "redis_engine_version" {
  type    = string
  default = "7.1"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "rabbitmq_engine_version" {
  type    = string
  default = "3.13.7"
}

variable "rabbitmq_instance_type" {
  type    = string
  default = "mq.m7g.large"
}

variable "acm_certificate_arn" {
  description = "Optional ACM certificate ARN for the public ALB HTTPS listener."
  type        = string
  default     = ""
}

variable "allow_http" {
  description = "Explicitly allow plain HTTP when no ACM certificate is supplied. Use only for temporary testing."
  type        = bool
  default     = false
}

variable "air_public_url" {
  description = "Optional customer-facing HTTPS URL used for CORS and the PWA API base."
  type        = string
  default     = ""
}

variable "deploy_services" {
  description = "Create ECS task definitions and services after ECR images have been built and pushed."
  type        = bool
  default     = false

  validation {
    condition     = !var.deploy_services || var.acm_certificate_arn != "" || var.allow_http
    error_message = "ECS services require an ACM certificate, or explicit allow_http=true for temporary non-production testing."
  }
}

variable "backend_image_uri" {
  type    = string
  default = ""
}

variable "pwa_image_uri" {
  type    = string
  default = ""
}

variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
}

variable "pwa_cpu" {
  type    = number
  default = 256
}

variable "pwa_memory" {
  type    = number
  default = 512
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "deployment_profile" {
  description = "AIR deployment profile hosted by this shared AWS stack."
  type        = string
  default     = "aws-private-single"
  validation {
    condition     = contains(["aws-private-single", "aws-saas-multi"], var.deployment_profile)
    error_message = "deployment_profile must be aws-private-single or aws-saas-multi."
  }
}

variable "tenancy_mode" {
  description = "Tenant isolation mode for the selected AIR deployment profile."
  type        = string
  default     = "single"
  validation {
    condition     = (var.deployment_profile == "aws-private-single" && var.tenancy_mode == "single") || (var.deployment_profile == "aws-saas-multi" && var.tenancy_mode == "multi")
    error_message = "aws-private-single requires tenancy_mode=single; aws-saas-multi requires tenancy_mode=multi."
  }
}
