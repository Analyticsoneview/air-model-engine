resource "random_id" "suffix" {
  byte_length = 4
}

resource "random_password" "database" {
  length  = 40
  special = false
}

resource "random_password" "redis" {
  length  = 40
  special = false
}

resource "random_password" "rabbitmq" {
  length  = 40
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "admin_api" {
  length  = 48
  special = false
}

resource "random_password" "admin_mfa" {
  length  = 48
  special = false
}

resource "random_id" "credential_key" {
  byte_length = 32
}

resource "aws_ecr_repository" "backend" {
  name                 = "${var.environment_name}-api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-api" })
}

resource "aws_ecr_repository" "pwa" {
  name                 = "${var.environment_name}-pwa"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-pwa" })
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain the newest 20 AIR API images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "pwa" {
  repository = aws_ecr_repository.pwa.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain the newest 20 AIR PWA images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_s3_bucket" "air_data" {
  bucket = "${var.environment_name}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}-data"
  tags   = merge(local.tags, { Name = "${var.environment_name}-data" })
}

resource "aws_s3_bucket_public_access_block" "air_data" {
  bucket                  = aws_s3_bucket.air_data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "air_data" {
  bucket = aws_s3_bucket.air_data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "air_data" {
  bucket = aws_s3_bucket.air_data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_db_subnet_group" "air" {
  name       = "${var.environment_name}-postgres"
  subnet_ids = aws_subnet.private[*].id
  tags       = merge(local.tags, { Name = "${var.environment_name}-postgres" })
}

resource "aws_db_instance" "air" {
  identifier                  = "${var.environment_name}-postgres"
  engine                      = "postgres"
  engine_version              = var.postgres_engine_version
  instance_class              = var.postgres_instance_class
  allocated_storage           = var.postgres_allocated_storage
  max_allocated_storage       = 200
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "air"
  username                    = "air"
  password                    = random_password.database.result
  port                        = 5432
  db_subnet_group_name        = aws_db_subnet_group.air.name
  vpc_security_group_ids      = [aws_security_group.postgres.id]
  parameter_group_name        = "default.postgres16"
  multi_az                    = var.postgres_multi_az
  publicly_accessible         = false
  backup_retention_period     = var.backup_retention_days
  copy_tags_to_snapshot       = true
  auto_minor_version_upgrade  = true
  deletion_protection         = var.postgres_deletion_protection
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${var.environment_name}-final-${random_id.suffix.hex}"
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  tags = merge(local.tags, { Name = "${var.environment_name}-postgres" })
}

resource "aws_elasticache_subnet_group" "air" {
  name       = "${var.environment_name}-redis"
  subnet_ids = aws_subnet.private[*].id
  tags       = merge(local.tags, { Name = "${var.environment_name}-redis" })
}

resource "aws_elasticache_replication_group" "air" {
  replication_group_id       = "${var.environment_name}-redis"
  description                = "Dedicated AIR Redis cache and coordination service."
  engine                     = "redis"
  engine_version             = var.redis_engine_version
  node_type                  = var.redis_node_type
  num_cache_clusters         = 2
  parameter_group_name       = "default.redis7"
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.air.name
  security_group_ids         = [aws_security_group.redis.id]
  auth_token                 = random_password.redis.result
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  automatic_failover_enabled = true
  multi_az_enabled           = true
  snapshot_retention_limit   = 7
  apply_immediately          = true
  tags = merge(local.tags, { Name = "${var.environment_name}-redis" })
}

resource "aws_mq_broker" "air" {
  broker_name                = "${var.environment_name}-rabbitmq"
  engine_type                = "RabbitMQ"
  engine_version             = var.rabbitmq_engine_version
  host_instance_type         = var.rabbitmq_instance_type
  deployment_mode            = "ACTIVE_STANDBY_MULTI_AZ"
  publicly_accessible        = false
  auto_minor_version_upgrade = true
  subnet_ids                 = aws_subnet.private[*].id
  security_groups            = [aws_security_group.rabbitmq.id]
  authentication_strategy    = "simple"
  user {
    username = "air"
    password = random_password.rabbitmq.result
  }
  logs {
    general = true
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-rabbitmq" })
}

resource "aws_efs_file_system" "air" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-data" })
}

resource "aws_efs_backup_policy" "air" {
  file_system_id = aws_efs_file_system.air.id
  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_efs_mount_target" "air" {
  count           = 2
  file_system_id  = aws_efs_file_system.air.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "air" {
  file_system_id = aws_efs_file_system.air.id
  posix_user {
    uid = 1000
    gid = 1000
  }
  root_directory {
    path = "/air"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0775"
    }
  }
  tags = merge(local.tags, { Name = "${var.environment_name}-air-ap" })
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.environment_name}/database-url"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://air:${random_password.database.result}@${aws_db_instance.air.address}:5432/air?sslmode=require"
}

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "${var.environment_name}/redis-url"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.air.primary_endpoint_address}:6379/0"
}

resource "aws_secretsmanager_secret" "rabbitmq_url" {
  name                    = "${var.environment_name}/rabbitmq-url"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "rabbitmq_url" {
  secret_id = aws_secretsmanager_secret.rabbitmq_url.id
  secret_string = "amqps://air:${random_password.rabbitmq.result}@${replace(aws_mq_broker.air.instances[0].endpoints[0], "amqps://", "")}/%2F"
}

resource "aws_secretsmanager_secret" "jwt_secret" {
  name                    = "${var.environment_name}/jwt-secret"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = random_password.jwt.result
}

resource "aws_secretsmanager_secret" "credential_key" {
  name                    = "${var.environment_name}/credential-key"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "credential_key" {
  secret_id     = aws_secretsmanager_secret.credential_key.id
  secret_string = random_id.credential_key.b64_url
}

resource "aws_secretsmanager_secret" "admin_api_key" {
  name                    = "${var.environment_name}/admin-api-key"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "admin_api_key" {
  secret_id     = aws_secretsmanager_secret.admin_api_key.id
  secret_string = random_password.admin_api.result
}

resource "aws_secretsmanager_secret" "admin_mfa_key" {
  name                    = "${var.environment_name}/admin-mfa-key"
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "admin_mfa_key" {
  secret_id     = aws_secretsmanager_secret.admin_mfa_key.id
  secret_string = random_password.admin_mfa.result
}
